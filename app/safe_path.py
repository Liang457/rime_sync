"""路径与设备名安全校验。

所有来自客户端/控制台的路径必须先过 safe_relpath()，再拼到存储根目录之下。
规则：posix 相对路径；拒绝绝对路径、盘符、.. 段、Windows 非法字符与保留名。
"""
from __future__ import annotations

import re

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_FORBIDDEN_CHARS = re.compile(r'[<>:"|?*\'\x00-\x1f]')
_DRIVE = re.compile(r"^[A-Za-z]:")


def safe_relpath(raw: str) -> str:
    """把任意输入规范化为安全的 posix 相对路径；非法抛 ValueError。"""
    if raw is None:
        raise ValueError("路径为空")
    p = str(raw).replace("\\", "/").strip()
    p = p.lstrip("/")
    if not p:
        raise ValueError("路径为空")
    if _DRIVE.match(p):
        raise ValueError(f"非法路径（盘符）: {raw!r}")
    segments = p.split("/")
    for seg in segments:
        if seg in ("", ".", ".."):
            raise ValueError(f"非法路径段: {raw!r}")
        if len(seg) > 255:
            raise ValueError("路径段过长")
        if _FORBIDDEN_CHARS.search(seg):
            raise ValueError(f"路径含非法字符: {seg!r}")
        if seg.endswith(".") or seg.endswith(" "):
            raise ValueError(f"路径段以点/空格结尾: {seg!r}")
        stem = seg.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise ValueError(f"路径段为 Windows 保留名: {seg!r}")
    joined = "/".join(segments)
    if len(joined) > 1024:
        raise ValueError("路径过长")
    return joined


def safe_device_name(raw: str) -> str:
    """设备名 = 单段安全路径（installation_id）。"""
    name = safe_relpath(raw)
    if "/" in name:
        raise ValueError(f"非法设备名: {raw!r}")
    return name
