"""「常用设置」表单注册表：描述每个可表单化的 patch 键。

首版只覆盖 default.custom.yaml（方案列表/菜单/中英切换/以词定字）——
这些全部 patch 自基座 default.yaml；rime_ice.custom.yaml、weasel.custom.yaml
暂走源码模式，后续按需在 TARGETS 里加组。

每项带类型标签，模板按类型渲染控件；表单值约定见 console.configs_patch_save。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


@dataclass(frozen=True)
class Option:
    key: str                    # slash 路径，如 ascii_composer/switch_key/Shift_L
    label: str
    type: str                   # bool | int | enum | keyname | hotkeys | schema_list
    choices: tuple[tuple[str, str], ...] = ()   # enum/keyname 可选值
    int_min: int = 1
    int_max: int = 10
    help: str = ""


@dataclass(frozen=True)
class Group:
    title: str
    options: tuple[Option, ...]


@dataclass(frozen=True)
class TargetSpec:
    patch_file: str             # 如 default.custom.yaml
    source_file: str            # 被补丁覆盖的基座文件，如 default.yaml
    groups: tuple[Group, ...] = field(default_factory=tuple)


_SWITCH_KEY = (
    ("commit_code", "commit_code · 上屏已输入的编码"),
    ("commit_text", "commit_text · 上屏拼出的词句"),
    ("inline_ascii", "inline_ascii · 临时英文模式"),
    ("clear", "clear · 清除未上屏内容"),
    ("noop", "noop · 不切换"),
    ("set_ascii_mode", "set_ascii_mode · 切到英文"),
    ("unset_ascii_mode", "unset_ascii_mode · 切到中文"),
)

_KEYS = (
    ("bracketleft", "[ 左中括号"),
    ("bracketright", "] 右中括号"),
    ("minus", "- 减号"),
    ("equal", "= 等号"),
    ("comma", ", 逗号"),
    ("period", ". 句号"),
    ("semicolon", "; 分号"),
    ("apostrophe", "' 单引号"),
    ("slash", "/ 斜杠"),
    ("grave", "` 反引号"),
    ("Tab", "Tab"),
)

_HOTKEY_CHOICES = (
    ("F4", "F4"),
    ("Control+grave", "Ctrl+`"),
    ("Control+Shift+grave", "Ctrl+Shift+`"),
    ("Alt+grave", "Alt+`"),
)

_DEFAULT_TARGET = TargetSpec(
    patch_file="default.custom.yaml",
    source_file="default.yaml",
    groups=(
        Group("方案列表", (
            Option("schema_list", "启用的输入方案", "schema_list",
                   help="勾选并排序，第一项为默认方案；方案文件来自文件库"),
        )),
        Group("菜单与方案选单", (
            Option("menu/page_size", "候选词个数", "int", int_min=1, int_max=10),
            Option("switcher/fold_options", "方案选单折叠选项", "bool",
                   help="多方案时建议折叠；单方案建议展开"),
            Option("switcher/hotkeys", "呼出方案选单快捷键", "hotkeys",
                   choices=_HOTKEY_CHOICES),
        )),
        Group("中英切换", (
            Option("ascii_composer/good_old_caps_lock", "CapsLock 行为", "bool",
                   help="开=切换大写（传统）；关=切换中英文"),
            Option("ascii_composer/switch_key/Caps_Lock", "CapsLock 键", "enum",
                   choices=tuple(c for c in _SWITCH_KEY if c[0] != "set_ascii_mode"
                                 and c[0] != "unset_ascii_mode")),
            Option("ascii_composer/switch_key/Shift_L", "左 Shift", "enum",
                   choices=_SWITCH_KEY),
            Option("ascii_composer/switch_key/Shift_R", "右 Shift", "enum",
                   choices=_SWITCH_KEY),
            Option("ascii_composer/switch_key/Control_L", "左 Ctrl", "enum",
                   choices=_SWITCH_KEY),
            Option("ascii_composer/switch_key/Control_R", "右 Ctrl", "enum",
                   choices=_SWITCH_KEY),
        )),
        Group("以词定字", (
            Option("key_binder/select_first_character", "取词首字快捷键", "keyname",
                   choices=_KEYS, help="上屏当前词句的第一个字"),
            Option("key_binder/select_last_character", "取词尾字快捷键", "keyname",
                   choices=_KEYS, help="上屏当前词句的最后一个字"),
        )),
    ),
)

# 按补丁文件名索引；rime_ice.custom.yaml 等后续要表单化时往这里加
TARGETS: dict[str, TargetSpec] = {
    t.patch_file: t for t in (_DEFAULT_TARGET,)
}


def target_for(path: str) -> TargetSpec | None:
    """按补丁文件路径（清单里的 rel，可能带目录前缀）找注册表。"""
    name = re.sub(r".*/", "", path)
    return TARGETS.get(name)


def option_map(spec: TargetSpec) -> dict[str, Option]:
    return {o.key: o for g in spec.groups for o in g.options}


# ---- 基座默认值与方案清单 -----------------------------------------------------

def base_yaml_data(store, rel: str) -> dict:
    """读基座 yaml（如 default.yaml）为 dict；不存在/解析失败返回 {}。"""
    meta = store.manifest()["files"].get(rel)
    if not meta or meta.get("source") != "base":
        return {}
    path = store.get_path(rel)
    if path is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def walk_path(data: dict, dotted: str):
    """按 a/b/c 路径取嵌套值；取不到返回 None。"""
    node = data
    for part in dotted.split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


_SCHEMA_RE = re.compile(r"([\w-]+)\.schema\.yaml$")


def available_schemas(store) -> list[dict]:
    """文件库根目录里的全部方案：[{id, name, source}]，供方案列表勾选。"""
    out: list[dict] = []
    for rel in store.all_rels():
        if "/" in rel:
            continue
        m = _SCHEMA_RE.search(rel)
        if not m:
            continue
        meta = store.manifest()["files"].get(rel, {})
        name = m.group(1)
        path = store.get_path(rel)
        if path is not None:
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                nick = (data.get("schema") or {}).get("name")
                if isinstance(nick, str) and nick.strip():
                    name = nick.strip()
            except (OSError, yaml.YAMLError):
                pass
        out.append({"id": m.group(1), "name": name,
                    "source": meta.get("source", "")})
    return out
