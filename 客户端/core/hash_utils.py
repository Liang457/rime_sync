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


def compute_bytes_hash(data: bytes) -> str:
    hash_obj = hashlib.sha3_256()
    hash_obj.update(data)
    return f"{HASH_ALGORITHM}:{hash_obj.hexdigest()}"


def safe_parse_iso(iso_str: str) -> datetime:
    s = iso_str.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    return datetime.fromisoformat(s)
