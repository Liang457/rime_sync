import logging
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from core.config import ConfigManager
from core.api import APIClient
from core.tar_utils import extract_tar
from core.errors import APIError
from core.hash_utils import compute_file_hash, safe_parse_iso

logger = logging.getLogger(__name__)


def compute_local_state(config: ConfigManager, device: str) -> Dict[str, Dict]:
    sync_dir = config.config_dir / "sync" / device
    if not sync_dir.exists():
        return {}

    state = {}
    for file_path in sync_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name == "_manifest.json":
            continue

        rel_path = str(file_path.relative_to(sync_dir)).replace("\\", "/")
        try:
            stat = file_path.stat()
            state[rel_path] = {
                "hash": compute_file_hash(file_path),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
        except Exception as e:
            logger.warning(f"无法计算文件哈希: {rel_path}: {e}")
            continue

    return state


def diff_sync_state(local: Dict[str, Dict], remote: Dict[str, Dict]) -> Tuple[List[str], List[str]]:
    to_upload = []
    to_download = []

    local_files = set(local.keys())
    remote_files = set(remote.keys())

    for fname in local_files - remote_files:
        to_upload.append(fname)

    for fname in remote_files - local_files:
        to_download.append(fname)

    for fname in local_files & remote_files:
        local_hash = local[fname].get("hash", "")
        remote_hash = remote[fname].get("hash", "")

        if local_hash == remote_hash:
            continue

        try:
            local_mtime = safe_parse_iso(local[fname].get("modified", ""))
            remote_mtime = safe_parse_iso(remote[fname].get("modified", ""))

            if local_mtime > remote_mtime:
                to_upload.append(fname)
            elif local_mtime < remote_mtime:
                to_download.append(fname)
            else:
                to_upload.append(fname)
                to_download.append(fname)
        except Exception:
            to_upload.append(fname)
            to_download.append(fname)

    return to_upload, to_download


def create_sync_tar(config: ConfigManager, device_name: str) -> Path:
    sync_dir = config.config_dir / "sync" / device_name

    if not sync_dir.exists():
        raise FileNotFoundError(
            f"sync文件夹不存在: {sync_dir}\n"
            f"请确保 {sync_dir} 目录存在并包含用户词库文件"
        )

    temp_dir = Path(tempfile.gettempdir())
    tar_path = temp_dir / f"sync_{device_name}_{int(time.time())}.tar"

    try:
        with tarfile.open(tar_path, "w") as tarf:
            for file_path in sync_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(sync_dir)
                    tarf.add(file_path, arcname=relative_path)
                    logger.debug(f"添加到tar: {relative_path}")

        logger.info(f"创建tar包: {tar_path} (包含 {sync_dir} 目录内容)")
        return tar_path

    except Exception as e:
        if tar_path.exists():
            tar_path.unlink(missing_ok=True)
        raise RuntimeError(f"创建tar包失败: {e}")


def upload_sync_tar(config: ConfigManager, api: APIClient,
                    device: Optional[str] = None):
    if not device:
        device = config.device_name

    logger.info(f"上传用户词库tar包（设备: {device}）...")

    tar_path = create_sync_tar(config, device)

    try:
        result = api.upload_sync_tar(str(tar_path), device)
        if result.get("success"):
            logger.info(f"tar上传成功: {result.get('data', {})}")
            return result
        else:
            logger.warning(f"tar上传失败: {result.get('error', '未知错误')}")
            logger.info("回退到逐个文件上传模式...")
            _fallback_upload_files(config, api, device, tar_path)
            return {"success": True, "message": "通过逐个文件上传完成"}
    finally:
        if tar_path.exists():
            tar_path.unlink(missing_ok=True)
            logger.debug(f"临时tar文件已删除: {tar_path}")


def _fallback_upload_files(config: ConfigManager, api: APIClient,
                           device: str, tar_path: Path):
    import shutil
    temp_dir = Path(tempfile.mkdtemp())

    try:
        with tarfile.open(tar_path, "r") as tar_ref:
            tar_ref.extractall(path=temp_dir, filter='data')

        file_paths = [f for f in temp_dir.rglob("*") if f.is_file()]

        if not file_paths:
            logger.warning("tar文件中没有文件可上传")
            return

        logger.info(f"开始逐个上传 {len(file_paths)} 个文件...")

        success_count = 0
        fail_count = 0

        for file_path in file_paths:
            try:
                relative_path = str(file_path.relative_to(temp_dir)).replace("\\", "/")
                api.upload_sync_file(str(file_path), relative_path, device)
                success_count += 1
            except Exception as e:
                logger.warning(f"上传文件 {relative_path} 失败: {e}")
                fail_count += 1

        logger.info(f"逐个文件上传完成: {success_count} 成功, {fail_count} 失败")

    except Exception as e:
        raise RuntimeError(f"回退上传过程中出错: {e}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def upload_sync_file(config: ConfigManager, api: APIClient,
                     file_path: str, filename: Optional[str] = None,
                     device: Optional[str] = None):
    if not device:
        device = config.device_name

    upload_path = Path(file_path)
    if not upload_path.exists():
        raise FileNotFoundError(f"上传文件不存在: {upload_path}")

    if not filename:
        filename = upload_path.name

    result = api.upload_sync_file(str(upload_path), filename, device)
    if result.get("success"):
        logger.info(f"上传成功: {filename}")
        return result
    else:
        raise APIError(f"上传失败: {filename}")


def download_sync_tar(config: ConfigManager, api: APIClient,
                      device: Optional[str] = None,
                      since: Optional[str] = None):
    if not device:
        device = config.device_name

    data = api.download_sync_tar(device, since)

    temp_dir = Path(tempfile.gettempdir())
    tar_path = temp_dir / f"sync_download_{device}_{int(time.time())}.tar"

    with open(tar_path, "wb") as f:
        f.write(data)
    logger.info(f"用户词库tar已下载: {tar_path}")

    sync_dir = config.config_dir / "sync" / device
    extracted_files = extract_tar(tar_path, sync_dir)
    logger.info(f"用户词库解压完成，共 {len(extracted_files)} 个文件到 {sync_dir}")

    tar_path.unlink(missing_ok=True)
    logger.info("临时tar文件已删除")

    return extracted_files


def download_sync_file(config: ConfigManager, api: APIClient,
                       filename: str, device: Optional[str] = None):
    if not device:
        device = config.device_name

    data = api.download_sync_file(filename, device)

    sync_dir = config.config_dir / "sync" / device
    local_path = sync_dir / filename
    local_path.parent.mkdir(parents=True, exist_ok=True)

    with open(local_path, "wb") as f:
        f.write(data)
    logger.info(f"文件已保存: {local_path}")
    return local_path


def _remote_state_from_info(data: Dict) -> Dict[str, Dict]:
    files = data.get("files", [])
    state = {}
    for f in files:
        fname = f.get("name", "")
        if fname:
            state[fname] = {
                "hash": f.get("hash", ""),
                "size": f.get("size", 0),
                "modified": f.get("modified", "")
            }
    return state


def sync_userdb(config: ConfigManager, api: APIClient,
                action: str = "upload", filename: Optional[str] = None):
    device_name = config.device_name
    sync_dir = config.config_dir / "sync"

    if action == "download":
        if filename:
            logger.info(f"下载用户词库文件: {filename}")
            return download_sync_file(config, api, filename, device_name)

        logger.info(f"增量下载其他设备的用户词库（当前设备: {device_name}）...")

        try:
            all_devices = api.get_device_names()
        except Exception:
            sync_info_result = api.get_sync_info()
            sync_info_data = sync_info_result.get("data", {})
            all_devices = [dev.get('name') for dev in sync_info_data.get('devices', [])
                           if dev.get('name')]

        if not all_devices:
            raise RuntimeError("无法获取设备列表")

        other_devices = [d for d in all_devices if d != device_name]

        if not other_devices:
            logger.info("没有其他设备需要同步")
            return {"devices": 0, "downloaded": 0, "skipped": 0}

        logger.info(f"发现 {len(other_devices)} 个其他设备: {', '.join(other_devices)}")

        total_downloaded = 0
        for other_device in other_devices:
            try:
                logger.info(f"增量同步设备 {other_device}...")

                result = api.get_sync_info(device=other_device)
                remote_data = result.get("data", {})
                remote_state = _remote_state_from_info(remote_data)
                local_state = compute_local_state(config, other_device)
                _, to_download = diff_sync_state(local_state, remote_state)

                if not to_download:
                    logger.info(f"设备 {other_device}: 所有文件已是最新")
                    continue

                logger.info(f"设备 {other_device}: {len(to_download)} 个文件需要下载")
                device_sync_dir = sync_dir / other_device
                device_sync_dir.mkdir(parents=True, exist_ok=True)

                for fname in to_download:
                    try:
                        download_sync_file(config, api, fname, other_device)
                        total_downloaded += 1
                    except Exception as e:
                        logger.warning(f"下载文件 {other_device}/{fname} 失败: {e}")

            except Exception as e:
                logger.warning(f"处理设备 {other_device} 时出错: {e}，跳过此设备")
                continue

        logger.info(f"增量下载完成: 共 {total_downloaded} 个文件")
        return {"downloaded": total_downloaded}

    elif action == "upload":
        logger.info(f"增量上传用户词库（设备: {device_name}）...")

        try:
            result = api.get_sync_info(device=device_name)
        except Exception as e:
            logger.warning(f"无法获取服务端同步信息，回退到全量tar上传: {e}")
            return upload_sync_tar(config, api, device_name)

        remote_data = result.get("data", {})
        remote_state = _remote_state_from_info(remote_data)
        local_state = compute_local_state(config, device_name)

        if not local_state:
            logger.info("本地无用户词库文件")
            return {"uploaded": 0, "skipped": 0}

        to_upload, _ = diff_sync_state(local_state, remote_state)

        if not to_upload:
            logger.info(f"所有文件已是最新 ({len(local_state)} 个文件)，无需上传")
            return {"uploaded": 0, "skipped": len(local_state)}

        logger.info(f"发现 {len(to_upload)} 个文件需要上传（共 {len(local_state)} 个本地文件）")

        success = 0
        failed = []
        for fname in to_upload:
            try:
                file_path = config.config_dir / "sync" / device_name / fname
                api.upload_sync_file(str(file_path), fname, device_name)
                success += 1
            except Exception as e:
                logger.warning(f"上传文件 {fname} 失败: {e}")
                failed.append(fname)

        logger.info(f"增量上传完成: {success}/{len(to_upload)}，失败: {failed}")
        return {"uploaded": success, "failed": len(failed), "total": len(to_upload)}

    else:
        raise ValueError(f"未知操作: {action}")
