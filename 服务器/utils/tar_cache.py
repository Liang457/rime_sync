"""
临时 tar 缓存目录管理
- 目录位于系统临时目录（如 /tmp）下，可能被系统随时清理
- 每次使用前都必须确认目录存在（mkdir exist_ok）
- 退出清理只删除缓存文件，不删除目录本身，避免影响其他实例
"""

import tempfile
from pathlib import Path


def get_tar_cache_dir() -> Path:
    """返回 tar 缓存目录，并确保其存在。"""
    cache_dir = Path(tempfile.gettempdir()) / "rime_server_tar_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def cleanup_stale_files() -> int:
    """删除缓存目录内的残留文件，返回删除数量。目录不存在时视为已清理。"""
    cache_dir = get_tar_cache_dir()
    removed = 0
    for stale in cache_dir.iterdir():
        try:
            stale.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def cleanup_tar_cache() -> None:
    """进程退出时清理缓存文件，保留目录本身。"""
    try:
        cache_dir = get_tar_cache_dir()
    except OSError:
        return
    for stale in cache_dir.iterdir():
        try:
            stale.unlink()
        except OSError:
            pass
