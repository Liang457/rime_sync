import hashlib
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

HASH_ALGORITHM = "sha3-256"


def compute_file_hash(filepath: Path) -> str:
    """计算文件 SHA3-256 哈希，返回格式: 'sha3-256:hexdigest'"""
    hash_obj = hashlib.sha3_256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_obj.update(chunk)
        return f"{HASH_ALGORITHM}:{hash_obj.hexdigest()}"
    except Exception as e:
        logger.error(f"计算文件哈希失败: {filepath}, 错误: {e}")
        from utils.error_handler import APIError
        raise APIError(f"计算文件哈希失败: {str(e)}", 500)


def compute_bytes_hash(data: bytes) -> str:
    """计算字节数据的 SHA3-256 哈希"""
    hash_obj = hashlib.sha3_256()
    hash_obj.update(data)
    return f"{HASH_ALGORITHM}:{hash_obj.hexdigest()}"


def safe_parse_iso(iso_str: str) -> datetime:
    """安全解析 ISO 时间字符串，正确处理 Z 后缀和已有时区偏移"""
    s = iso_str.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    return datetime.fromisoformat(s)
