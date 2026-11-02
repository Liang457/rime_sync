"""服务器配置：config/server.json，缺项自动补默认值并写回。"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from pathlib import Path

DEFAULTS: dict = {
    "server": {
        "host": "0.0.0.0",
        "port": 10033,
        "api_token": "",
    },
    "console": {
        # sha3-256 hex；空 = 控制台免登录（仅建议在可信局域网这么做）
        "password_hash": "",
    },
    "base": {
        "repo_url": "https://github.com/iDvel/rime-ice",
    },
    "limits": {
        "max_upload_mb": 512,
    },
}


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()

    # ---- 加载与保存 ------------------------------------------------------

    def _load(self) -> dict:
        data: dict = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        merged = json.loads(json.dumps(DEFAULTS))  # 深拷贝默认值
        for section, values in data.items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
            else:
                merged[section] = values
        merged.setdefault("secret_key", secrets.token_hex(32))
        changed = merged != data
        if changed or not self.path.exists():
            self._write(merged)
        return merged

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def save(self) -> None:
        with self._lock:
            self._write(self.data)

    # ---- 便捷访问 --------------------------------------------------------

    @property
    def host(self) -> str:
        return self.data["server"]["host"]

    @property
    def port(self) -> int:
        return int(self.data["server"]["port"])

    @property
    def api_token(self) -> str:
        return self.data["server"]["api_token"]

    @property
    def password_hash(self) -> str:
        return self.data["console"]["password_hash"]

    @property
    def secret_key(self) -> str:
        return self.data["secret_key"]

    @property
    def max_upload_bytes(self) -> int:
        return int(self.data["limits"]["max_upload_mb"]) * 1024 * 1024

    @property
    def base_repo_url(self) -> str:
        return self.data["base"]["repo_url"]

    # ---- 控制台密码 ------------------------------------------------------

    @staticmethod
    def hash_password(plain: str) -> str:
        return hashlib.sha3_256(plain.encode("utf-8")).hexdigest()

    def set_password(self, plain: str) -> None:
        with self._lock:
            self.data["console"]["password_hash"] = self.hash_password(plain)
        self.save()

    def clear_password(self) -> None:
        with self._lock:
            self.data["console"]["password_hash"] = ""
        self.save()

    def check_password(self, plain: str) -> bool:
        stored = self.password_hash
        if not stored:
            return True
        return hmac.compare_digest(self.hash_password(plain), stored)
