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


def safe_parse_iso(iso_str: str) -> datetime:
    """安全解析 ISO 时间字符串，正确处理 Z 后缀和已有时区偏移。
    始终返回 naive 本地时间，以便与 datetime.fromtimestamp() 的结果直接比较。"""
    s = iso_str.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        # 转换为本地时间后去除时区信息
        dt = dt.astimezone().replace(tzinfo=None)
    return dt
