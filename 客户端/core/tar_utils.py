import logging
import shutil
import tarfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def safe_join(base_dir: Path, name: str) -> Path:
    """将（可能来自服务端的）相对路径安全地拼接在 base_dir 下。
    拒绝绝对路径、'..' 穿越、以及通过符号链接逃逸出 base_dir 的路径。"""
    base = base_dir.resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"拒绝路径: 路径遍历攻击 {name}")
    return target


def save_bytes(base_dir: Path, filename: str, data: bytes) -> Path:
    """将字节数据安全地保存到 base_dir 下的 filename 路径，返回最终路径。"""
    local_path = safe_join(base_dir, filename)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    return local_path


def extract_tar(tar_path: Path, extract_dir: Path) -> List[str]:
    extracted_files = []

    try:
        with tarfile.open(tar_path, "r") as tar_ref:
            for member in tar_ref.getmembers():
                if member.isfile():
                    target_path = safe_join(extract_dir, member.name)
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target, length=64 * 1024)

                    extracted_files.append(str(target_path))
                    logger.debug(f"解压文件: {member.name} -> {target_path}")

            logger.info(f"从tar解压了 {len(extracted_files)} 个文件")
            return extracted_files

    except tarfile.ReadError:
        raise RuntimeError(f"tar文件损坏: {tar_path}")
    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(f"解压tar文件失败: {e}")
