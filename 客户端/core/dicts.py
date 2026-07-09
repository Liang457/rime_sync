import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from core.config import ConfigManager
from core.api import APIClient
from core.tar_utils import extract_tar
from core.hash_utils import compute_file_hash

logger = logging.getLogger(__name__)


CATEGORY_PREFIXES = {
    "cn": "cn_dicts/",
    "en": "en_dicts/",
    "lua": "lua/",
    "opencc": "opencc/",
}


class SyncState:
    def __init__(self, config_dir: Path):
        self.state_file = config_dir / ".sync_state.json"
        self.state: Dict[str, str] = self._load()

    def _load(self) -> Dict[str, str]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_file.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self.state_file)

    def get_last_sync(self, key: str = "all") -> Optional[str]:
        return self.state.get(key)

    def set_last_sync(self, key: str, timestamp: str):
        self.state[key] = timestamp
        self.save()


def _filter_files(files: List[Dict], category: Optional[str]) -> List[Dict]:
    if not category or category == "all":
        return files

    prefix = CATEGORY_PREFIXES.get(category)
    if not prefix:
        logger.warning(f"未知类别: {category}，将同步全部")
        return files

    return [f for f in files if f.get("path", "").startswith(prefix)]


def _check_changes(config_dir: Path, server_files: List[Dict]) -> List[str]:
    changed = []
    for remote in server_files:
        rel_path = remote.get("path", "")
        remote_hash = remote.get("hash", "")
        local_path = config_dir / rel_path

        if not local_path.exists():
            changed.append(rel_path)
            continue

        try:
            local_hash = compute_file_hash(local_path)
            if local_hash != remote_hash:
                changed.append(rel_path)
        except Exception:
            changed.append(rel_path)

    return changed


def sync_dicts(config: ConfigManager, api: APIClient,
               category: Optional[str] = None,
               since: Optional[str] = None):
    state = SyncState(config.config_dir)
    state_key = category or "all"

    if since is None:
        since = state.get_last_sync(state_key)

    logger.info(f"检查配置更新（类别: {state_key}）...")

    info = api.get_full_sync_info(since=since)
    data = info.get("data", {})
    server_files = data.get("files", [])

    server_files = _filter_files(server_files, category)

    if not server_files:
        logger.info(f"类别 '{state_key}': 服务端无文件")
        return {"files": 0, "changed": 0}

    changed_files = _check_changes(config.config_dir, server_files)

    if not changed_files:
        logger.info(f"类别 '{state_key}': 所有文件已是最新 ({len(server_files)} 个文件)")
        return {"files": len(server_files), "changed": 0}

    logger.info(f"类别 '{state_key}': {len(changed_files)}/{len(server_files)} 个文件需要更新")

    data_bytes = api.download_full_sync(since=since)

    config_dir = config.config_dir
    tar_path = config_dir / "runtime_sync.tar"
    with open(tar_path, "wb") as f:
        f.write(data_bytes)
    logger.info(f"配置tar已下载: {tar_path}")

    extracted = extract_tar(tar_path, config_dir)
    logger.info(f"解压完成: {len(extracted)} 个文件")

    tar_path.unlink(missing_ok=True)
    state.set_last_sync(state_key, datetime.now().isoformat())

    return {"files": len(server_files), "changed": len(changed_files), "extracted": len(extracted)}


def download_dict_tar(config: ConfigManager, api: APIClient,
                      category: Optional[str] = None,
                      since: Optional[str] = None):
    logger.info("下载词库tar包...")

    data = api.download_dict_tar(category, since)

    config_dir = config.config_dir
    tar_path = config_dir / "dicts_update.tar"
    with open(tar_path, "wb") as f:
        f.write(data)
    logger.info(f"词库tar已下载: {tar_path}")

    extracted_files = extract_tar(tar_path, config_dir)
    logger.info(f"解压完成，共 {len(extracted_files)} 个文件")

    tar_path.unlink(missing_ok=True)
    return extracted_files


def download_dict_file(config: ConfigManager, api: APIClient,
                       filename: str, category: Optional[str] = None):
    logger.info(f"下载词库文件: {filename}")

    data = api.download_dict_file(filename, category)

    config_dir = config.config_dir
    if category == "cn":
        target_dir = config_dir / "cn_dicts"
    elif category == "en":
        target_dir = config_dir / "en_dicts"
    else:
        target_dir = config_dir

    target_dir.mkdir(parents=True, exist_ok=True)
    local_path = target_dir / filename

    with open(local_path, "wb") as f:
        f.write(data)
    logger.info(f"文件已保存: {local_path}")
    return local_path
