import logging
import os
import tarfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def safe_tar_member_path(member_name: str, extract_dir: Path) -> Path:
    target_path = (extract_dir / member_name).resolve()
    extract_dir_resolved = extract_dir.resolve()
    if not str(target_path).startswith(str(extract_dir_resolved) + os.sep) and target_path != extract_dir_resolved:
        raise ValueError(f"拒绝解压: 路径遍历攻击 {member_name}")
    return target_path


def extract_tar(tar_path: Path, extract_dir: Path) -> List[str]:
    extracted_files = []

    try:
        with tarfile.open(tar_path, "r") as tar_ref:
            for member in tar_ref.getmembers():
                if member.isfile():
                    target_path = safe_tar_member_path(member.name, extract_dir)
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                        target.write(source.read())

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
