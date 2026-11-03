"""「常用设置」表单注册表：描述每个可表单化的 patch 键。

首版只覆盖 default.custom.yaml（方案列表/菜单/中英切换）——这些全部 patch
自基座 default.yaml；rime_ice/weasel/squirrel/trime 等走源码模式
（见 PRESETS），后续按需在 TARGETS 里加组。

每项带类型标签，模板按类型渲染控件；表单值约定见 console.configs_patch_save。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from . import custom_yaml


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
    ),
)

# 按补丁文件名索引；要表单化更多文件时往这里加
TARGETS: dict[str, TargetSpec] = {
    t.patch_file: t for t in (_DEFAULT_TARGET,)
}

# ---- 预设定制文件：配置页一键创建，缺失时也可从基座文件警示条直接补建 ----------

def _starter(hints: str) -> str:
    body = hints.strip("\n")
    return (custom_yaml.HEADER_COMMENT
            + ("\n" + body + "\n" if body else "") + "\npatch: {}\n")


_PRESET_WEASEL_HINTS = """
# 小狼毫（Windows）界面定制，常用键（值要与 weasel.yaml 里的定义对应）：
#   patch/style/color_scheme: 鸦青     # 配色方案名（preset_color_schemes 键）
#   patch/style/color_scheme_dark: 幽蓝
#   patch/style/horizontal: true       # 候选横排
#   patch/style/font_face: 微软雅黑
#   patch/style/font_point: 12
"""

_PRESET_SQUIRREL_HINTS = """
# 鼠须管（macOS）界面定制，常用键（值要与 squirrel.yaml 里的定义对应）：
#   patch/style/color_scheme: clean_white     # 配色方案名（preset_color_schemes 键）
#   patch/style/horizontal: true              # 候选横排
#   patch/style/font_face: PingFangSC-Regular
#   patch/style/font_point: 16
#   patch/app_options/com.apple.Terminal/ascii_mode: true
"""

_PRESET_TRIME_HINTS = """
# 同文（Android）定制补丁。注意：trime.yaml 默认内置在 APK 里，
# 手机用户目录可能没有它——没有基座文件时补丁不生效，留作备用。
# 常用键（源码手写，值要与 trime.yaml 里的定义对应）：
#   patch/style/color_scheme: default_theme
#   patch/style/keyboards: default
#   patch/style/horizontal: false
"""

_PRESET_RIME_ICE_HINTS = """
# 雾凇拼音方案级定制（rime_ice.custom.yaml 覆盖 rime_ice.schema.yaml /
# rime_ice.dict.yaml），常用键：
#   patch/translator/enable_sentence: true
#   patch/speller/algebra/__patch: ...     # 拼写运算等高级定制
"""

PRESETS: dict[str, dict] = {
    "default.custom.yaml": {
        "desc": "全局配置：方案列表/候选数/中英切换，支持「常用设置」表单",
        "starter": custom_yaml.HEADER_COMMENT + "\npatch: {}\n",
    },
    "rime_ice.custom.yaml": {
        "desc": "雾凇拼音方案级定制（源码手写）",
        "starter": _starter(_PRESET_RIME_ICE_HINTS),
    },
    "weasel.custom.yaml": {
        "desc": "Windows 小狼毫界面定制（源码手写）",
        "starter": _starter(_PRESET_WEASEL_HINTS),
    },
    "squirrel.custom.yaml": {
        "desc": "macOS 鼠须管界面定制（源码手写）",
        "starter": _starter(_PRESET_SQUIRREL_HINTS),
    },
    "trime.custom.yaml": {
        "desc": "Android 同文定制（源码手写；trime.yaml 内置在 APK，留作备用）",
        "starter": _starter(_PRESET_TRIME_HINTS),
    },
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
