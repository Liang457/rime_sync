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


def extract_dict_body(filepath: Path) -> bytes:
    """提取词库文件正文（剔除 YAML 头部），返回归一化后的 UTF-8 字节。

    归一化规则：
    - 剥离 UTF-8 BOM
    - 统一换行符 \r\n / \r → \n
    - 逐行去除尾部空白
    - 删除末尾空行

    头部识别：若首个非空行 strip 后为 '---'，则向后扫描首个 strip 后等于
    '...' 或 '---' 的行作为头部结束，正文取其之后的内容；
    未找到结束符或无 '---' 头部时，整个文件视为正文。
    """
    try:
        raw = filepath.read_bytes()
    except Exception as e:
        logger.error(f"读取词库文件失败: {filepath}, 错误: {e}")
        from utils.error_handler import APIError
        raise APIError(f"读取词库文件失败: {str(e)}", 500)

    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]

    text = raw.decode('utf-8', errors='replace')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')

    body_start = 0
    first_non_empty = None
    for i, line in enumerate(lines):
        if line.strip():
            first_non_empty = i
            break
    if first_non_empty is not None and lines[first_non_empty].strip() == '---':
        for j in range(first_non_empty + 1, len(lines)):
            if lines[j].strip() in ('---', '...'):
                body_start = j + 1
                break

    body_lines = [line.rstrip() for line in lines[body_start:]]
    while body_lines and body_lines[-1] == '':
        body_lines.pop()

    return '\n'.join(body_lines).encode('utf-8')


def compute_dict_body_hash(filepath: Path) -> str:
    """计算词库正文（剔除 YAML 头部）的 SHA3-256 哈希，返回格式: 'sha3-256:hexdigest'"""
    body = extract_dict_body(filepath)
    hash_obj = hashlib.sha3_256()
    hash_obj.update(body)
    return f"{HASH_ALGORITHM}:{hash_obj.hexdigest()}"


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
