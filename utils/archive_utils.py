"""tar 打包与 since 时间筛选的公共工具，供各 Manager 复用。"""

import tarfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from utils.error_handler import APIError
from utils.hash_utils import safe_parse_iso


def parse_since(since: Optional[str]) -> Optional[datetime]:
    """解析 since 时间戳，返回 naive 本地时间；无效格式抛 APIError(400)。"""
    if not since:
        return None
    try:
        return safe_parse_iso(since)
    except (ValueError, TypeError):
        raise APIError("无效的时间格式，请使用ISO格式", 400)


def create_tar_file(prefix: str, build_tar: Callable[[tarfile.TarFile], None]) -> Path:
    """在 tar 缓存目录创建临时 tar 文件；失败时清理临时文件并抛 APIError。"""
    import uuid

    from utils.tar_cache import get_tar_cache_dir

    tar_path = get_tar_cache_dir() / f"{prefix}_{uuid.uuid4().hex[:8]}.tar"
    try:
        with tarfile.open(tar_path, 'w') as tarf:
            build_tar(tarf)
        return tar_path
    except Exception as e:
        try:
            tar_path.unlink()
        except Exception:
            pass
        raise APIError(f"创建tar文件失败: {str(e)}", 500)
