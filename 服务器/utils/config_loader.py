import os
import json
import logging
import copy
from datetime import datetime
from pathlib import Path

class ConfigManager:
    def __init__(self, config_dir="config"):
        self.config_dir = Path(config_dir)
        self.configs = {}
        self.logger = logging.getLogger(__name__)
        self.load_all_configs()

    def load_config(self, filename):
        config_path = self.config_dir / filename
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning(f"配置文件 {filename} 不存在，使用默认配置")
            return self.get_default_config(filename)
        except json.JSONDecodeError as e:
            self.logger.error(f"配置文件 {filename} JSON 格式错误: {e}")
            return self.get_default_config(filename)

    def get_default_config(self, filename):
        defaults = {
            "server.json": {
                "server": {
                    "host": "0.0.0.0",
                    "port": 10032,
                    "debug": False,
                    "log_level": "INFO",
                    "log_file": "logs/server.log",
                    "log_max_bytes": 10485760,
                    "log_backup_count": 5,
                    "max_upload_size_mb": 100,
                    "allowed_extensions": [".yaml", ".txt", ".dict.yaml", ".tar"]
                },
                "paths": {
                    "rime_ice_original": "rime_ice_original/",
                    "runtime": "runtime/",
                    "makedict": "makedict/",
                    "sync": "sync/",
                    "backups": "backups/"
                },
                "git": {
                    "rime_ice_repo": "https://github.com/MarkLux/rime-ice.git",
                    "rime_ice_branch": "main",
                    "update_check_interval": 3600
                },
                "log_archive": {
                    "enabled": True,
                    "retention_days": 90
                }
            },
            "sync.json": {
                "sync": {
                    "auto_cleanup_days": 30,
                    "max_files_per_device": 100,
                    "max_total_size_mb": 1024,
                    "conflict_resolution": "latest",
                    "hash_algorithm": "sha3-256",
                    "manifest_file": "_manifest.json"
                },
                "devices": {}
            },
            "dict.json": {
                "dict": {
                    "cn_dicts_path": "runtime/cn_dicts/",
                    "en_dicts_path": "runtime/en_dicts/",
                    "allowed_extensions": [".dict.yaml", ".txt"],
                    "auto_update_scripts": {}
                }
            },
            "script.json": {
                "scripts": {
                    "max_execution_time": 300,
                    "max_memory_mb": 512,
                    "allow_network_access": True,
                    "allowed_hosts": ["*"],
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
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.configs[config_name], f, indent=2, ensure_ascii=False)
            self.logger.info(f"配置文件 {config_file} 已保存")
            return True
        except Exception as e:
            self.logger.error(f"保存配置文件 {config_file} 失败: {e}")
            return False

    def reload(self):
        """重新加载所有配置文件（失败时自动回滚）"""
        self.logger.info("重新加载所有配置文件")
        old_configs = copy.deepcopy(self.configs)
        try:
            self.load_all_configs()
        except Exception as e:
            self.logger.error(f"配置重载失败，回滚到旧配置: {e}")
            self.configs = old_configs
            return False
        return self.configs != old_configs

config_manager = ConfigManager()