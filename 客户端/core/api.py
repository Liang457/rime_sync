import logging
import time
from typing import Dict, Any, Optional, List

import requests

from core.config import ConfigManager
from core.errors import APIError

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.session = requests.Session()

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        url = f"{self.config.server_url}{endpoint}"
        kwargs.setdefault("timeout", self.config.timeout)
        kwargs.setdefault("verify", self.config.verify_ssl)

        for attempt in range(1, self.config.retry_count + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < self.config.retry_count:
                    wait = 2 ** attempt
                    logger.warning(f"请求失败 (尝试 {attempt}/{self.config.retry_count})，{wait}秒后重试: {e}")
                    time.sleep(wait)
                    continue
                raise APIError(f"请求失败，已达最大重试次数: {url}")

            except requests.exceptions.HTTPError as e:
                error_msg = str(e)
                status_code = response.status_code
                try:
                    if response.headers.get("content-type", "").startswith("application/json"):
                        error_data = response.json()
                        error_msg = error_data.get('error', str(e))
                except Exception:
                    pass
                logger.warning(f"HTTP错误 {status_code}: {error_msg}")
                raise APIError(error_msg)

            except Exception as e:
                raise APIError(f"请求失败: {e}")

    def _request_json(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        return self._request(method, endpoint, **kwargs).json()

    def _request_bytes(self, method: str, endpoint: str, **kwargs) -> bytes:
        return self._request(method, endpoint, **kwargs).content

    def get_status(self) -> Dict[str, Any]:
        logger.info("获取服务器状态...")
        return self._request_json("GET", "/api/status")

    def update_rime_ice(self, force: bool = False) -> Dict[str, Any]:
        logger.info("请求更新rime-ice仓库...")
        return self._request_json("POST", "/api/rime_ice/update", json={"force": force})

    def run_script(self, script_name: str, version: str,
                   extra_params: Optional[Dict] = None) -> Dict[str, Any]:
        logger.info(f"运行词库生成脚本: {script_name}")
        data = {"version": version}
        if extra_params:
            data["extra_params"] = extra_params
        return self._request_json("POST", f"/api/makedict/run/{script_name}", json=data)

    def edit_file(self, path: str, line: int, content: str,
                  action: str = "insert") -> Dict[str, Any]:
        logger.info(f"编辑文件: {path}")
        return self._request_json("POST", "/api/file/edit", json={
            "path": path, "line": line, "content": content, "action": action
        })

    def upload_config(self, file_path: str, device: str,
                      overwrite: bool = False) -> Dict[str, Any]:
        from pathlib import Path
        upload_path = Path(file_path)
        if not upload_path.exists():
            raise FileNotFoundError(f"上传文件不存在: {upload_path}")

        logger.info(f"上传配置文件: {upload_path}")
        with open(upload_path, 'rb') as f:
            return self._request_json("POST", "/api/config/upload", files={
                'file': (upload_path.name, f, 'application/octet-stream')
            }, data={
                'device': device,
                'overwrite': str(overwrite).lower()
            })

    def get_sync_info(self, device: Optional[str] = None,
                      since: Optional[str] = None) -> Dict[str, Any]:
        logger.info("获取同步信息...")
        params = {}
        if device:
            params["device"] = device
        if since:
            params["since"] = since
        return self._request_json("GET", "/api/sync/info", params=params)

    def get_device_list(self) -> Dict[str, Any]:
        logger.info("获取设备列表...")
        return self._request_json("GET", "/api/device/list")

    def get_device_names(self) -> List[str]:
        result = self.get_device_list()
        if not result.get("success"):
            return []

        devices = result.get("data", {}).get("devices", [])
        device_names = []
        for device in devices:
            if isinstance(device, str):
                device_names.append(device)
            elif isinstance(device, dict):
                name = device.get('name')
                if name:
                    device_names.append(name)
        return device_names

    def check_health(self) -> Dict[str, Any]:
        logger.info("执行健康检查...")
        return self._request_json("GET", "/api/health")

    def check_connection(self) -> bool:
        try:
            result = self._request_json("GET", "/api/status")
            return result.get("success", False)
        except Exception:
            return False

    def get_dict_info(self, category: Optional[str] = None,
                      since: Optional[str] = None) -> Dict[str, Any]:
        logger.info("获取词库信息...")
        params = {}
        if category:
            params["category"] = category
        if since:
            params["since"] = since
        return self._request_json("GET", "/api/dict/info", params=params)

    def get_full_sync_info(self, exclude: Optional[str] = None,
                           since: Optional[str] = None) -> Dict[str, Any]:
        logger.info("获取完整配置包信息...")
        params = {}
        if exclude:
            params["exclude"] = exclude
        if since:
            params["since"] = since
        return self._request_json("GET", "/api/full_sync/info", params=params)

    def download_dict_tar(self, category: Optional[str] = None,
                          since: Optional[str] = None) -> bytes:
        logger.info("下载词库tar包...")
        params = {}
        if category:
            params["category"] = category
        if since:
            params["since"] = since
        return self._request_bytes("GET", "/api/dict/get/tar", params=params)

    def download_dict_file(self, filename: str,
                           category: Optional[str] = None) -> bytes:
        logger.info(f"下载词库文件: {filename}")
        params = {}
        if category:
            params["category"] = category
        return self._request_bytes("GET", f"/api/dict/get/file/{filename}", params=params)

    def download_full_sync(self, exclude: Optional[str] = None,
                           since: Optional[str] = None) -> bytes:
        logger.info("下载完整配置包...")
        params = {}
        if exclude:
            params["exclude"] = exclude
        if since:
            params["since"] = since
        return self._request_bytes("GET", "/api/full_sync/download", params=params)

    def upload_full_sync(self, file_path: str, overwrite: bool = False) -> Dict[str, Any]:
        from pathlib import Path
        upload_path = Path(file_path)
        if not upload_path.exists():
            raise FileNotFoundError(f"上传文件不存在: {upload_path}")

        logger.info(f"上传完整配置包: {upload_path}")
        with open(upload_path, 'rb') as f:
            return self._request_json("POST", "/api/full_sync/upload", files={
                'file': (upload_path.name, f, 'application/x-tar')
            }, data={'overwrite': str(overwrite).lower()})

    def upload_sync_tar(self, tar_path, device: str) -> Dict[str, Any]:
        logger.info(f"上传用户词库tar包（设备: {device}）...")
        with open(tar_path, 'rb') as f:
            return self._request_json("POST", "/api/sync/upload/tar", files={
                'file': (f"sync_{device}.tar", f, 'application/x-tar')
            }, data={'device': device})

    def upload_sync_file(self, file_path: str, filename: str,
                         device: str) -> Dict[str, Any]:
        upload_path = file_path
        logger.info(f"上传用户词库文件: {filename}（设备: {device}）...")
        with open(upload_path, 'rb') as f:
            return self._request_json("POST", "/api/sync/upload/file", files={
                'file': (filename, f, 'application/octet-stream')
            }, data={'device': device, 'filename': filename})

    def download_sync_tar(self, device: str,
                          since: Optional[str] = None) -> bytes:
        logger.info(f"下载用户词库tar包（设备: {device}）...")
        params = {}
        if since:
            params["since"] = since
        return self._request_bytes("GET", f"/api/sync/get/{device}/tar", params=params)

    def download_sync_file(self, filename: str, device: str) -> bytes:
        logger.info(f"下载用户词库文件: {filename}（设备: {device}）...")
        return self._request_bytes("GET", f"/api/sync/get/{device}/file/{filename}")

    def copy_rime_ice_to_runtime(self) -> Dict[str, Any]:
        return self._request_json("POST", "/api/rime_ice/copy_to_runtime")

    def list_scripts(self) -> Dict[str, Any]:
        logger.info("获取可用脚本列表...")
        return self._request_json("GET", "/api/makedict/list")
