import json
import logging
import copy
from pathlib import Path

class ConfigManager:
    def __init__(self, config_dir="config"):
        self.config_dir = Path(config_dir)
        # 相对路径基于本文件所在目录（服务器/utils/ 的上一级），
        # 避免依赖进程启动时的工作目录
        if not self.config_dir.is_absolute():
            self.config_dir = (Path(__file__).resolve().parent.parent / self.config_dir).resolve()
        # 服务器根目录（config_dir 的父目录），用于解析相对路径
        self.base_dir = self.config_dir.parent
        self.configs = {}
        self.load_errors = {}
        self.logger = logging.getLogger(__name__)
        self.load_all_configs()

    @staticmethod
    def _merge_defaults(defaults, data):
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

    def load_config(self, filename):
        config_path = self.config_dir / filename
        defaults = self.get_default_config(filename)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            self.load_errors.pop(filename, None)
            self.logger.warning(f"配置文件 {filename} 不存在，使用默认配置")
            return defaults
        except json.JSONDecodeError as e:
            # 记录错误供 reload 回滚判断；启动时仍回退默认配置保持可用
            self.load_errors[filename] = str(e)
            self.logger.error(f"配置文件 {filename} JSON 格式错误: {e}")
            return defaults

        self.load_errors.pop(filename, None)
        if not isinstance(data, dict):
            self.load_errors[filename] = "配置根节点不是字典"
            self.logger.error(f"配置文件 {filename} 根节点不是字典，使用默认配置")
            return defaults

        merged = self._merge_defaults(defaults, data)
        if merged != data:
            # 旧配置文件缺少新增选项时自动补充并写回，保证向后兼容
            self.logger.info(f"配置文件 {filename} 缺少选项，已自动补充默认值并保存")
            self._write_config(config_path, merged)
        return merged

    def get_default_config(self, filename):
        defaults = {
            "server.json": {
                "server": {
                    "host": "0.0.0.0",
                    "port": 10032,
                    "log_level": "INFO",
                    "log_file": "logs/server.log",
                    "log_max_bytes": 10485760,
                    "log_backup_count": 5,
                    "max_upload_size_mb": 100,
                    "allowed_extensions": [".yaml", ".txt", ".dict.yaml"],
                    "api_token": ""
                },
                "paths": {
                    "rime_ice_original": "rime_ice_original/",
                    "runtime": "runtime/",
                    "makedict": "makedict/",
                    "sync": "sync/",
                    "backups": "backups/"
                },
                "git": {
                    "rime_ice_repo": "https://github.com/iDvel/rime-ice.git",
                    "rime_ice_branch": "main"
                },
                "log_archive": {
                    "enabled": True,
                    "retention_days": 90
                }
            },
            "sync.json": {
                "sync": {
                    "max_files_per_device": 100,
                    "max_total_size_mb": 1024,
                    "manifest_file": "_manifest.json"
                },
                "devices": {}
            },
            "dict.json": {
                "dict": {
                    "cn_dicts_path": "runtime/cn_dicts/",
                    "en_dicts_path": "runtime/en_dicts/",
                    "allowed_extensions": [".dict.yaml", ".txt"]
                }
            },
            "script.json": {
                "scripts": {
                    "max_execution_time": 300,
                    "trusted_users": ["admin"],
                    "log_execution": True
                }
            },
            "devices.json": {
                "devices": {}
            }
        }
        return defaults.get(filename, {})

    def load_all_configs(self):
        config_files = ["server.json", "sync.json", "dict.json", "script.json", "devices.json"]
        for config_file in config_files:
            config_name = config_file.replace('.json', '')
            self.configs[config_name] = self.load_config(config_file)
        
        self.logger.info("所有配置文件加载完成")
        self.validate_configs()

    def validate_configs(self):
        for config_name, config_data in self.configs.items():
            if not isinstance(config_data, dict):
                self.logger.warning(f"配置 {config_name} 不是有效的字典格式")

    def get(self, config_name, key=None, default=None):
        config = self.configs.get(config_name)
        if config is None:
            return default
        
        if key is None:
            return config
        
        keys = key.split('.')
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        
        return value

    def resolve_path(self, path_str: str) -> str:
        """将相对路径解析为基于服务器根目录的绝对路径"""
        p = Path(path_str)
        if p.is_absolute():
            return str(p)
        return str(self.base_dir / p)

    def update(self, config_name, data):
        if config_name in self.configs:
            self.configs[config_name].update(data)
            self.save_config(config_name)
            return True
        return False

    def save_config(self, config_name):
        config_file = f"{config_name}.json"
        config_path = self.config_dir / config_file
        try:
            self._write_config(config_path, self.configs[config_name])
            self.logger.info(f"配置文件 {config_file} 已保存")
            return True
        except Exception as e:
            self.logger.error(f"保存配置文件 {config_file} 失败: {e}")
            return False

    def _write_config(self, config_path, data):
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def reload(self):
        """重新加载所有配置文件（解析失败时回滚到旧配置）"""
        self.logger.info("重新加载所有配置文件")
        old_configs = copy.deepcopy(self.configs)
        try:
            self.load_all_configs()
        except Exception as e:
            self.logger.error(f"配置重载失败，回滚到旧配置: {e}")
            self.configs = old_configs
            return False
        if self.load_errors:
            self.logger.error(f"配置重载时存在解析错误，回滚到旧配置: {self.load_errors}")
            self.configs = old_configs
            return False
        return self.configs != old_configs

config_manager = ConfigManager()