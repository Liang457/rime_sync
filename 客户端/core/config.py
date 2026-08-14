import copy
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from core.errors import ConfigError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "client_config.json"

DEFAULTS = {
    "server": {
        "url": "http://localhost:10032",
        "timeout": 30,
        "retry_count": 3,
        "verify_ssl": False,
        "api_token": "",
        "sync_all_timeout": 1800,
    },
    "rime": {
        "config_dir": ".",
        "platform": "windows",
        "android_trime_config": "",
    },
    "sync": {
        "device_name": "",
    },
    "logging": {
        "level": "INFO",
        "file": "logs/rime_client.log",
        "max_size_mb": 10,
        "archive_enabled": True,
        "archive_retention_days": 90,
    },
}


class ConfigManager:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config: Dict[str, Any] = {}
        self.load()

    def load(self):
        if not self.config_path.exists():
            logger.error(f"配置文件不存在: {self.config_path}")
            logger.info("正在创建默认配置文件...")
            self.create_default()
            raise ConfigError(
                f"默认配置文件已创建: {self.config_path}\n请编辑配置文件后重新运行"
            )

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            raw_config = copy.deepcopy(config)
            config = self._migrate(config)
            self._apply_defaults(config)

            if not config["sync"]["device_name"]:
                config["sync"]["device_name"] = self._read_device_from_installation(config)

            self.config = config
            # 旧配置文件缺少新增选项时自动补充并写回，保证向后兼容
            if self.config != raw_config:
                logger.info("配置文件缺少选项，已自动补充默认值并保存")
                self.save()
        except json.JSONDecodeError as e:
            raise ConfigError(f"配置文件格式错误: {e}")
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(f"加载配置文件失败: {e}")

    def _migrate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if "rime" in config and "sync" in config:
            return config

        new_config = {"server": {}, "rime": {}, "sync": {}, "logging": {}}

        if "server" in config:
            new_config["server"] = config["server"]

        new_config["rime"] = {
            "config_dir": config.get("paths", {}).get("local_rime_dir", "."),
            "platform": "windows",
            "android_trime_config": "",
        }

        new_config["sync"] = {
            "device_name": config.get("device", {}).get("name", ""),
        }

        if "logging" in config:
            new_config["logging"] = config["logging"]

        return new_config

    @staticmethod
    def _merge_defaults(defaults: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        """递归合并默认配置：data 中已有的值优先，缺失的键由 defaults 补充。"""
        if isinstance(defaults, dict) and isinstance(data, dict):
            result = dict(data)
            for key, value in defaults.items():
                if key in result:
                    result[key] = ConfigManager._merge_defaults(value, result[key])
                else:
                    result[key] = copy.deepcopy(value)
            return result
        return data

    def _apply_defaults(self, config: Dict[str, Any]):
        for section, values in DEFAULTS.items():
            config[section] = self._merge_defaults(values, config.get(section, {}))

    def create_default(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(copy.deepcopy(DEFAULTS), f, indent=2, ensure_ascii=False)

        logger.info(f"已创建默认配置文件: {self.config_path}")
        logger.info("请编辑配置文件并设置正确的服务器URL和Rime配置目录")

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {self.config_path}")
        except Exception as e:
            raise ConfigError(f"保存配置失败: {e}")

    def _read_device_from_installation(self, config: Dict[str, Any]) -> str:
        config_dir = Path(config["rime"]["config_dir"])
        installation_path = config_dir / "installation.yaml"

        if not installation_path.exists():
            logger.warning(f"installation.yaml文件不存在: {installation_path}")
            return "unknown"

        try:
            with open(installation_path, "r", encoding="utf-8") as f:
                installation_data = yaml.safe_load(f)

            device_name = installation_data.get("installation_id")
            if not device_name:
                logger.warning("installation.yaml中没有找到installation_id字段")
                return "unknown"

            logger.debug(f"从installation.yaml获取到设备名: {device_name}")
            return device_name

        except yaml.YAMLError as e:
            logger.warning(f"解析installation.yaml失败: {e}")
            return "unknown"
        except Exception as e:
            logger.warning(f"读取installation.yaml失败: {e}")
            return "unknown"

    @property
    def server_url(self) -> str:
        return self.config["server"]["url"]

    @property
    def config_dir(self) -> Path:
        return Path(self.config["rime"]["config_dir"])

    @property
    def timeout(self) -> int:
        return self.config["server"]["timeout"]

    @property
    def retry_count(self) -> int:
        return self.config["server"].get("retry_count", 3)

    @property
    def sync_all_timeout(self) -> int:
        return self.config["server"].get("sync_all_timeout", 1800)

    @property
    def verify_ssl(self) -> bool:
        return self.config["server"].get("verify_ssl", False)

    @property
    def api_token(self) -> str:
        return self.config["server"].get("api_token", "")

    @property
    def platform(self) -> str:
        return self.config["rime"]["platform"]

    @property
    def log_config(self) -> Dict[str, Any]:
        return self.config.get("logging", {})

    @property
    def sync_config(self) -> Dict[str, Any]:
        return self.config.get("sync", {})

    @property
    def device_name(self) -> str:
        device_name = self.config["sync"]["device_name"]
        if not device_name or device_name == "unknown":
            device_name = self._read_device_from_installation(self.config)
            self.config["sync"]["device_name"] = device_name
        return device_name
