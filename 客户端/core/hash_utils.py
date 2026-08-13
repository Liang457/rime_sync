import hashlib
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

HASH_ALGORITHM = "sha3-256"


def compute_file_hash(filepath: Path) -> str:
    hash_obj = hashlib.sha3_256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_obj.update(chunk)
        return f"{HASH_ALGORITHM}:{hash_obj.hexdigest()}"
    except Exception as e:
        logger.error(f"计算文件哈希失败: {filepath}, 错误: {e}")
        raise RuntimeError(f"计算文件哈希失败: {str(e)}")


def safe_parse_iso(iso_str: str) -> datetime:
    """安全解析 ISO 时间字符串，始终返回 naive 本地时间。"""
    s = iso_str.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt
