"""路径安全工具：在指定基目录下解析并校验路径不越界。"""

from pathlib import Path


def safe_resolve(base_dir, name) -> Path:
    """将 name 拼接到 base_dir 下并校验不越界，返回解析后的绝对路径。
    越界时抛 ValueError。"""
    base = Path(base_dir).resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"无效的路径: {name}")
    return target
