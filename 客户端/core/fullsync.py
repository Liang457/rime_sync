import logging
from pathlib import Path
from typing import Optional

from core.config import ConfigManager
from core.api import APIClient
from core.tar_utils import extract_tar
from core.platform import stop_weasel, start_weasel

logger = logging.getLogger(__name__)


def download_full_sync(config: ConfigManager, api: APIClient,
                       exclude: Optional[str] = None,
                       since: Optional[str] = None):
    logger.info("下载完整配置包...")

    data = api.download_full_sync(exclude, since)

    config_dir = config.config_dir
    tar_path = config_dir / "full_sync.tar"
    with open(tar_path, "wb") as f:
        f.write(data)
    logger.info(f"完整配置包已下载: {tar_path}")

    is_windows = config.platform == "windows"
    weasel_path = stop_weasel() if is_windows else None

    try:
        extracted_files = extract_tar(tar_path, config_dir)
        logging.info(f"解压完成，共 {len(extracted_files)} 个文件")
    finally:
        if weasel_path is not None:
            start_weasel(weasel_path)

    tar_path.unlink(missing_ok=True)
    logger.info("临时tar文件已删除")

    return extracted_files


def upload_full_sync(config: ConfigManager, api: APIClient,
                     file_path: str, overwrite: bool = False):
    upload_path = Path(file_path)
    if not upload_path.exists():
        raise FileNotFoundError(f"上传文件不存在: {upload_path}")

    logger.info(f"上传完整配置包: {upload_path}")
    logger.warning("此操作会覆盖服务器现有配置，请谨慎操作！")

    return api.upload_full_sync(str(upload_path), overwrite)
