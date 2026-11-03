"""*.custom.yaml patch 读写：配置表单的唯一落盘通道。

统一规范：patch 使用 librime 的 slash 路径风格（menu/page_size: 6），
读取时把嵌套写法展开为 slash 路径；写回保序输出。
只做文本解析/序列化（PyYAML safe_load/safe_dump），不执行任何内容。

librime 语义：`X.custom.yaml` 的 patch 段覆盖 `X.yaml` 的对应配置；
表单里某项留空/选「跟随基座默认」= 从 patch 删除该键 = 恢复基座默认。
"""
from __future__ import annotations

import yaml

HEADER_COMMENT = (
    "# RIME 定制补丁（由控制台生成/管理）\n"
    "# 规范：patch 用 slash 路径风格；删除某键 = 恢复基座默认。\n"
    "# 可手改，表单保存时会保留这里的手写键。\n"
)


def parse_patch(text: str) -> dict[str, object]:
    """解析 .custom.yaml → {slash路径: 值}。无 patch 段/空文件返回 {}。

    嵌套写法（menu: {page_size: 6}）展开为 menu/page_size；同一个键同时以
    嵌套与 slash 两种写法出现视为冲突，抛 ValueError（让用户先去源码里统一）。
    """
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict) or "patch" not in data:
        return {}
    patch = data["patch"]
    if patch is None:
        return {}
    if not isinstance(patch, dict):
        raise ValueError("patch 段不是映射，请先在源码模式下修正")
    flat: dict[str, object] = {}
    _walk("", patch, flat)
    return flat


def _walk(prefix: str, node, flat: dict[str, object]) -> None:
    for k, v in node.items():
        key = f"{prefix}/{k}" if prefix else str(k)
        if isinstance(v, dict):
            if key in flat:
                raise ValueError(f"补丁里同时存在嵌套与 slash 写法：{key}")
            _walk(key, v, flat)
        else:
            if key in flat:
                raise ValueError(f"补丁里键重复：{key}")
            flat[key] = v


def dump_patch(patch: dict[str, object]) -> str:
    """{slash路径: 值} → .custom.yaml 文本（含说明头，键保持给定顺序）。"""
    body = yaml.safe_dump(
        {"patch": dict(patch)},
        allow_unicode=True, default_flow_style=False, sort_keys=False,
    )
    return HEADER_COMMENT + body


def apply_patch(current_text: str, updates: dict[str, object] | None = None,
                removes: list[str] | None = None) -> str:
    """在现有补丁上合并更新/删除键，返回新文件文本。

    只动给出的键，用户手写的其他键原样保留；补丁清空时输出占位 patch: {}。
    """
    patch = parse_patch(current_text)
    for k, v in (updates or {}).items():
        if v is None:
            patch.pop(k, None)
        else:
            patch[k] = v
    for k in removes or []:
        patch.pop(k, None)
    if not patch:
        return HEADER_COMMENT + "patch: {}\n"
    return dump_patch(patch)
