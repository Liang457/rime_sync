"""rime_ice.dict.yaml 联动：词库发布/删除/「词库开关」/基座重建后维护 import_tables。

规则（幂等，以 manifest + imports.json 为事实来源）：
- 纳管名单 = store 里 cn_dicts/<名>.dict.yaml 且 source != base 的文件（即
  rime_dict 发布与控制台上传的词库）；条目以 `cn_dicts/<名>` 路径形写进
  import_tables——裸名 librime 解析到配置根目录，挂不住 cn_dicts 下的文件
  （rime-ice 官方示例亦用此前缀），旧版写过的裸名条目在读取时统一升级；
- imports.json 存三份名单：managed=上次由本联动写入的条目（文件删了 → 引用撤掉）；
  disabled=用户显式关闭的条目；enabled=用户显式启用的条目（基座默认注释态的，
  如 41448——重建打回原样后由重放补回；只补文件在库的，避免悬空引用）；
- 基座自带条目（8105 等）只有被显式关闭才移除，联动永不主动动它们；
- 解析/改写是行级的：条目行尾注释（`- cn_dicts/8105    # 字表`）与块内注释行
  （`#- cn_dicts/41448`）原样保留，开关只增删条目行本身；
- 字表类（纯数字名，如 41448）启用时紧跟 8105 之后，其余条目追加在末尾
  （rime-ice 约定：字表优先级靠前，扩展词库垫底）；
- rime_ice.dict.yaml 不存在时跳过（基座还没导入）；
- 改写保留原 source/version 元数据（不改 overlay 归属）。
"""
from __future__ import annotations

import json
import re

from .store import AddItem, FileStore

MAIN_DICT = "rime_ice.dict.yaml"
# import_tables 段：行内形式 [..] 或下面跟着若干缩进行（条目/注释都算段内）
_BLOCK_RE = re.compile(
    r"^(import_tables[ \t]*:[ \t]*)(\[[^\]]*\]|[^\n]*)\n((?:[ \t]+[^\n]*\n?)*)",
    re.MULTILINE,
)
# 条目行：缩进 + "- " + 条目 token（不含空白与 #，行尾注释不碍事）+ 其余
_LINE_RE = re.compile(r"^([ \t]+)-[ \t]*([^\s#]+)(.*)$")
# 关闭开关校验用的条目名（cn_dicts/ 单层）
_TABLE_RE = re.compile(r"^cn_dicts/[\w.-]+$")

# 基座自带词库的展示名（「词库开关」页用，其余回落到条目名本身）
_DICT_LABELS = {
    "8105": "字表",
    "41448": "大字表（按需启用）",
    "base": "基础词库",
    "ext": "扩展词库",
    "tencent": "腾讯词向量（部署时间较长）",
    "others": "杂项",
}


def _label(table: str) -> str:
    return _DICT_LABELS.get(table.split("/", 1)[-1], "")


def managed_tables(store: FileStore) -> list[str]:
    """自管词库条目（cn_dicts/<名> 路径形），基座来源不算。"""
    out: list[str] = []
    for rel, meta in sorted(store.manifest()["files"].items()):
        m = re.fullmatch(r"(cn_dicts/.+)\.dict\.yaml", rel)
        if m and meta.get("source") != "base" and m.group(1) not in out:
            out.append(m.group(1))
    return out


# ---- imports.json：managed / disabled 两份名单 --------------------------------

def _state_path(store: FileStore):
    return store.root / "imports.json"


def _upgrade(names: list[str]) -> list[str]:
    """旧版存过裸名条目，读取时统一升级为 cn_dicts/ 前缀。"""
    return [n if "/" in n else f"cn_dicts/{n}" for n in names]


def _load_state(store: FileStore) -> dict:
    """imports.json → {"managed": [...], "disabled": [...], "enabled": [...]}。
    兼容旧版纯列表格式（全是 managed）。"""
    try:
        data = json.loads(_state_path(store).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = None
    if isinstance(data, dict):
        managed = [x for x in data.get("managed", []) if isinstance(x, str)]
        disabled = [x for x in data.get("disabled", []) if isinstance(x, str)]
        enabled = [x for x in data.get("enabled", []) if isinstance(x, str)]
    elif isinstance(data, list):
        managed, disabled, enabled = [x for x in data if isinstance(x, str)], [], []
    else:
        managed, disabled, enabled = [], [], []
    return {"managed": _upgrade(managed), "disabled": _upgrade(disabled),
            "enabled": _upgrade(enabled)}


def _save_state(store: FileStore, managed: list[str], disabled: list[str],
                enabled: list[str] | None = None) -> None:
    payload = {"managed": managed, "disabled": disabled}
    if enabled is not None:
        payload["enabled"] = enabled
    _state_path(store).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- import_tables 解析（行级，注释原样保留）-----------------------------------

def _normalize(store: FileStore, token: str) -> str:
    """裸名条目 → cn_dicts/ 前缀，但仅当该词库文件确实在 cn_dicts 下
    （根目录手挂的 mydict1 等裸名保持原样）。"""
    if "/" not in token and f"cn_dicts/{token}.dict.yaml" in store.manifest()["files"]:
        return f"cn_dicts/{token}"
    return token


def _parse(store: FileStore, text: str):
    """解析 import_tables 段。

    返回 (匹配或 None, 行内形式文本或 "", 行列表)。行列表元素：
    {"raw": 原始行(含换行), "entry": 归一化条目或 None(注释/空行), "token":
    原始 token, "indent": 缩进, "rest": token 后的残余(含行尾注释)}。
    """
    m = _BLOCK_RE.search(text)
    if not m:
        return None, "", []
    inline = m.group(2).strip()
    if inline.startswith("["):
        return m, inline, []
    lines = []
    for raw in m.group(3).splitlines(True):
        lm = _LINE_RE.match(raw.rstrip("\n"))
        if lm:
            token = lm.group(2)
            lines.append({"raw": raw, "entry": _normalize(store, token),
                          "token": token, "indent": lm.group(1),
                          "rest": lm.group(3)})
        else:
            lines.append({"raw": raw, "entry": None, "token": None,
                          "indent": "", "rest": ""})
    return m, "", lines


def _entry_seq(store: FileStore, m, inline: str, lines: list[dict]) -> list[str]:
    if inline:
        return [_normalize(store, t) for t in re.findall(r"[^\s#\[\],]+", inline)]
    return [l["entry"] for l in lines if l["entry"]]


def _render_section(entries: list[str], inline: str, indent: str) -> str:
    """按原书写风格（行内 [ ] 或块列表）渲染 import_tables 段（行内形式专用）。"""
    if inline:
        return f"import_tables: [{', '.join(entries)}]\n" if entries else ""
    return ("import_tables:\n" + "".join(f"{indent}- {n}\n" for n in entries)
            if entries else "")


def _insert_lines(lines: list[dict], entries: list[str]) -> list[dict]:
    """把新条目行插进行列表：字表类（纯数字名）紧跟 8105 行之后，其余追加末尾。"""
    out = list(lines)
    entry_idx = [i for i, l in enumerate(out) if l["entry"]]
    indent = out[entry_idx[-1]]["indent"] if entry_idx else "  "
    anchor = next((i for i, l in enumerate(out)
                   if l["entry"] and l["entry"].split("/")[-1] == "8105"), None)
    for e in entries:
        line = {"raw": f"{indent}- {e}\n", "entry": e, "token": e,
                "indent": indent, "rest": ""}
        if anchor is not None and e.split("/")[-1].isdigit():
            out.insert(anchor + 1, line)
            anchor += 1
        else:
            out.insert((entry_idx[-1] + 1) if entry_idx else len(out), line)
            if entry_idx:
                entry_idx[-1] += 1
            else:
                entry_idx.append(len(out) - 1)
    return out


def current_entries(store: FileStore) -> list[str] | None:
    """当前 import_tables 条目（归一化后）；主词典不在库返回 None。"""
    path = store.get_path(MAIN_DICT)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    m, inline, lines = _parse(store, text)
    return _entry_seq(store, m, inline, lines)


def sync_import_tables(store: FileStore) -> dict | None:
    """把 manifest 里的词库状况同步进 rime_ice.dict.yaml 的 import_tables。

    返回 None 表示无需/无法修改；否则返回 {"added": [...], "removed": [...],
    "changed": bool}。
    """
    path = store.get_path(MAIN_DICT)
    if path is None:
        return None
    meta = store.manifest()["files"][MAIN_DICT]
    text = path.read_text(encoding="utf-8", errors="replace")

    managed = managed_tables(store)
    state = _load_state(store)
    prev_managed = state["managed"]
    disabled, explicit_on = set(state["disabled"]), set(state["enabled"])
    m, inline, lines = _parse(store, text)
    current = _entry_seq(store, m, inline, lines)

    # 移除两类：上次联动写入、这次文件已不在的；以及用户显式关闭的。
    # 重放显式启用（基座默认注释态的条目，如 41448）：只补文件在库的，避免悬空引用
    drop = (set(prev_managed) - set(managed)) | disabled
    removed = [e for e in current if e in drop]
    files = store.manifest()["files"]
    added = [e for e in managed
             if e not in current and e not in disabled]
    added += [e for e in sorted(explicit_on)
              if e not in current and e not in added
              and f"{e}.dict.yaml" in files]

    if m is None and not added:
        _save_state(store, managed, sorted(disabled), sorted(explicit_on))
        return {"added": [], "removed": [], "changed": False}

    if m is None:
        entries = [e for e in managed if e not in disabled] + added
        if not text.endswith("\n"):
            text += "\n"
        new_text = text + "\n" + _render_section(entries, "", "  ")
    elif inline:
        merged = [e for e in current if e not in drop] + added
        if merged == current and set(managed) == set(prev_managed):
            _save_state(store, managed, sorted(disabled), sorted(explicit_on))
            return {"added": [], "removed": [], "changed": False}
        new_text = (text[: m.start()] + _render_section(merged, inline, "  ")
                    + text[m.end():])
    else:
        # 行级改写：删 drop 条目行、插新增行，注释与其余行原样保留
        new_lines = []
        for l in lines:
            if l["entry"] and l["token"] != l["entry"]:
                # 裸名条目升级为 cn_dicts/ 前缀，行尾注释原样保留
                eol = "\n" if l["raw"].endswith("\n") else ""
                l = dict(l, raw=f"{l['indent']}- {l['entry']}{l['rest']}{eol}")
            if not (l["entry"] and l["entry"] in drop):
                new_lines.append(l)
        new_lines = _insert_lines(new_lines, added)
        new_text = (text[: m.start(3)] + "".join(l["raw"] for l in new_lines)
                    + text[m.end(3):])
        if new_text == text:
            _save_state(store, managed, sorted(disabled), sorted(explicit_on))
            return {"added": [], "removed": [], "changed": False}

    result = _write_back(store, meta, text, new_text, added, removed)
    _save_state(store, managed, sorted(disabled), sorted(explicit_on))
    return result


def toggle_table(store: FileStore, table: str, enabled: bool) -> dict:
    """「词库开关」：开/关一个 import_tables 条目并把选择持久化
    （imports.json 的 disabled/enabled 名单，基座重建后由 sync_import_tables 重放）。

    table 形如 cn_dicts/tencent；关闭允许处理悬空条目（文件已不在的），
    启用要求词库文件在库。返回 {"added": [...], "removed": [...], "changed": bool}。
    """
    if not _TABLE_RE.fullmatch(table):
        raise ValueError("非法词库条目")
    path = store.get_path(MAIN_DICT)
    if path is None:
        raise ValueError("rime_ice.dict.yaml 不在文件库，先更新基座")
    if enabled and f"{table}.dict.yaml" not in store.manifest()["files"]:
        raise ValueError(f"文件库里没有 {table}.dict.yaml，无法启用")
    meta = store.manifest()["files"][MAIN_DICT]
    text = path.read_text(encoding="utf-8", errors="replace")

    state = _load_state(store)
    disabled = set(state["disabled"])
    explicit_on = set(state["enabled"])
    m, inline, lines = _parse(store, text)
    current = _entry_seq(store, m, inline, lines)

    if enabled:
        disabled.discard(table)
        explicit_on.add(table)
    else:
        disabled.add(table)
        explicit_on.discard(table)

    # 文件里的实际增删；只记录意图（disabled 名单变化）时为空
    added, removed = [], []
    if m is None:
        if enabled:
            if not text.endswith("\n"):
                text += "\n"
            new_text = text + "\n" + _render_section([table], "", "  ")
            added = [table]
        else:
            new_text = text  # 段不存在，无事可写
    elif enabled and table not in current:
        added = [table]
        if inline:
            new_text = (text[: m.start()] + _render_section(
                _insert_after(current, table), inline, "  ") + text[m.end():])
        else:
            new_lines = _insert_lines(lines, [table])
            new_text = (text[: m.start(3)] + "".join(l["raw"] for l in new_lines)
                        + text[m.end(3):])
    elif not enabled and table in current:
        removed = [table]
        if inline:
            merged = [e for e in current if e != table]
            new_text = (text[: m.start()] + _render_section(merged, inline, "  ")
                        + text[m.end():])
        else:
            new_lines = [l for l in lines if l["entry"] != table]
            new_text = (text[: m.start(3)] + "".join(l["raw"] for l in new_lines)
                        + text[m.end(3):])
    else:
        new_text = text  # 只更新 disabled 名单，文件不用动

    _write_back(store, meta, text, new_text, added, removed)
    _save_state(store, state["managed"], sorted(disabled), sorted(explicit_on))
    return {"added": added, "removed": removed, "changed": new_text != text}


def _insert_after(entries: list[str], table: str) -> list[str]:
    """行内形式的插入位置：字表类紧跟 8105 之后，其余追加末尾。"""
    if table.split("/", 1)[-1].isdigit():
        for i, e in enumerate(entries):
            if e.split("/", 1)[-1] == "8105":
                return entries[: i + 1] + [table] + entries[i + 1:]
    return entries + [table]


def toggle_rows(store: FileStore) -> list[dict]:
    """「词库开关」页数据：当前 import_tables 顺序优先，其后是已关闭的
    和未登记的词库文件。"""
    files = store.manifest()["files"]
    disabled = set(_load_state(store)["disabled"])
    rows: list[dict] = []
    seen: set[str] = set()

    def row_for(table: str, enabled: bool) -> dict:
        name = table.split("/", 1)[-1]
        meta = files.get(f"{table}.dict.yaml")
        return {
            "table": table,
            "name": name,
            "label": _label(table),
            "source": meta.get("source", "") if meta else "",
            "enabled": enabled,
            "dangling": meta is None,
        }

    for e in current_entries(store) or []:
        if e in seen:
            continue
        seen.add(e)
        rows.append(row_for(e, e not in disabled))
    for d in sorted(disabled):
        if d not in seen:
            seen.add(d)
            rows.append(row_for(d, False))
    for rel in sorted(files):
        m = re.fullmatch(r"(cn_dicts/.+)\.dict\.yaml", rel)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            rows.append(row_for(m.group(1), False))
    return rows


def _write_back(
    store: FileStore, meta: dict, old_text: str, new_text: str,
    added: list[str], removed: list[str],
) -> dict:
    if old_text == new_text:
        return {"added": added, "removed": removed, "changed": False}
    store.add_many(
        [AddItem(MAIN_DICT, new_text.encode("utf-8"),
                 source=meta.get("source", "base"),
                 version=meta.get("version", ""))],
        detail=f"rime_ice.dict.yaml import_tables 联动（+{len(added)} -{len(removed)}）",
    )
    return {"added": added, "removed": removed, "changed": True}
