"""rime_ice.dict.yaml 联动：词库文件的发布/删除/基座重建后自动维护 import_tables。

规则（幂等，以 manifest 为唯一事实来源）：
- 纳管名单 = store 里 cn_dicts/<名字>.dict.yaml 且 source != base 的文件（即
  rime_dict 发布与控制台上传的词库）；上次纳管名单存 store/imports.json；
- import_tables 里只有「上次由本联动加入、这次已不在纳管名单」的条目会被移除
  （删词库 → 移除引用，避免悬空）；基座自带条目（8105 等）永不被碰；
- rime_ice.dict.yaml 不存在时跳过（基座还没导入）；
- 改写后保留该文件原有的 source/version 元数据（不改 overlay 归属）。
"""
from __future__ import annotations

import json
import re

from .store import AddItem, FileStore

MAIN_DICT = "rime_ice.dict.yaml"
_BLOCK_RE = re.compile(
    r"^(import_tables[ \t]*:[ \t]*)(\[[^\]]*\]|[^\n]*)\n((?:[ \t]+-[^\n]*\n)*)",
    re.MULTILINE,
)
_ENTRY_RE = re.compile(r"^[ \t]+-[ \t]*(\S+)[ \t]*$", re.MULTILINE)


def managed_names(store: FileStore) -> list[str]:
    names: list[str] = []
    for rel, meta in sorted(store.manifest()["files"].items()):
        m = re.fullmatch(r"cn_dicts/(.+)\.dict\.yaml", rel)
        if m and meta.get("source") != "base" and m.group(1) not in names:
            names.append(m.group(1))
    return names


def _read_prev_managed(store: FileStore) -> set[str]:
    path = store.root / "imports.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def _write_prev_managed(store: FileStore, names: list[str]) -> None:
    path = store.root / "imports.json"
    path.write_text(json.dumps(names, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def _parse(text: str) -> tuple[str | None, str, list[str], str]:
    """返回 (匹配整段或 None, 缩进, 现有名列表, 行内形式原样文本)。"""
    m = _BLOCK_RE.search(text)
    if not m:
        return None, "  ", [], ""
    inline = m.group(2).strip()
    if inline.startswith("["):
        names = re.findall(r"[-\w]+", inline)
        return m, "  ", names, inline
    names = _ENTRY_RE.findall(m.group(3))
    indent_m = re.search(r"^([ \t]+)-", m.group(3), re.MULTILINE)
    indent = indent_m.group(1) if indent_m else "  "
    return m, indent, names, inline


def sync_import_tables(store: FileStore) -> dict | None:
    """把 manifest 里的 cn_dicts 词库状况同步进 rime_ice.dict.yaml。

    返回 None 表示无需/无法修改；否则返回 {"added": [...], "removed": [...],
    "changed": bool}。
    """
    path = store.get_path(MAIN_DICT)
    if path is None:
        return None
    meta = store.manifest()["files"][MAIN_DICT]
    text = path.read_text(encoding="utf-8", errors="replace")

    managed = managed_names(store)
    prev_managed = _read_prev_managed(store)
    m, indent, current, inline = _parse(text)

    # 只移除「上次由本联动加入、这次已不在纳管名单」的条目
    drop = prev_managed - set(managed)
    keep = [n for n in current if n not in drop]
    added = [n for n in managed if n not in keep]
    merged = keep + added

    if merged == current and not added:
        _write_prev_managed(store, managed)
        return {"added": [], "removed": [], "changed": False}

    if m is None:
        if not managed:
            _write_prev_managed(store, managed)
            return None
        block = "import_tables:\n" + "".join(f"{indent}- {n}\n" for n in managed)
        if not text.endswith("\n"):
            text += "\n"
        new_text = text + "\n" + block
    else:
        if inline:
            new_section = (f"import_tables: [{', '.join(merged)}]\n"
                           if merged else "")
        else:
            new_section = ("import_tables:\n" +
                           "".join(f"{indent}- {n}\n" for n in merged)
                           if merged else "")
        new_text = text[: m.start()] + new_section + text[m.end():]

    removed = [n for n in current if n not in merged]
    result = _write_back(store, meta, text, new_text, added, removed)
    _write_prev_managed(store, managed)
    return result


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
