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
        # 基座自动更新：默认关，在「上游基座」页开启；cron 为服务器本地时间
        "auto_update": False,
        "cron": "0 4 * * *",
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

    @property
    def base_auto_update(self) -> bool:
        return bool(self.data["base"].get("auto_update"))

    @property
    def base_cron(self) -> str:
        return str(self.data["base"].get("cron", ""))

    def set_base_repo_url(self, url: str) -> None:
        url = (url or "").strip().rstrip("/")
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError("仓库地址必须是 http(s):// 开头")
        with self._lock:
            self.data["base"]["repo_url"] = url
        self.save()

    def set_base_schedule(self, enabled: bool, cron: str) -> None:
        """保存自动更新开关与 cron 表达式；开启时表达式必须合法。"""
        cron = (cron or "").strip()
        if enabled:
            try:
                from croniter import croniter

                croniter(cron)  # 仅校验格式
            except Exception as e:
                raise ValueError(f"cron 表达式无效：{cron or '（空）'}") from e
        with self._lock:
            self.data["base"]["auto_update"] = bool(enabled)
            self.data["base"]["cron"] = cron
        self.save()

    # ---- API token（可多个，设备页管理） -----------------------------------

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @property
    def tokens(self) -> list[dict]:
        return self.data["server"].setdefault("tokens", [])

    def add_token(self, label: str = "") -> dict:
        entry = {
            "token": "rs_" + secrets.token_hex(16),
            "label": label.strip(),
            "created": self._now_iso(),
        }
        with self._lock:
            self.tokens.append(entry)
        self.save()
        return entry

    def remove_token(self, token: str) -> bool:
        with self._lock:
            before = len(self.tokens)
            self.data["server"]["tokens"] = [
                t for t in self.tokens if t.get("token") != token
            ]
            removed = len(self.tokens) < before
        if removed:
            self.save()
        return removed

    def record_token_use(self, got: str, device: str = "") -> None:
        """API 鉴权命中后记录使用痕迹：last_used 时间与（带 device 参数时）
        上次使用的设备 id。命中旧版 api_token（无条目）不记录；
        内容没变化不落盘，避免每次 API 请求都写 server.json。"""
        entry = None
        for t in self.tokens:
            if hmac.compare_digest(got, t.get("token", "")):
                entry = t
                break
        if entry is None:
            return
        device = (device or "").strip()
        now = self._now_iso()
        with self._lock:
            changed = False
            if entry.get("last_used") != now:
                entry["last_used"] = now
                changed = True
            if device and entry.get("last_used_device") != device:
                entry["last_used_device"] = device
                changed = True
        if changed:
            self.save()

    def token_ok(self, got: str) -> bool:
        """未配置任何 token 时视为不启用认证；否则须命中旧 api_token 或任一 token。"""
        if not self.api_token and not self.tokens:
            return True
        if not got:
            return False
        if hmac.compare_digest(got, self.api_token):
            return True
        return any(
            hmac.compare_digest(got, t.get("token", "")) for t in self.tokens
        )

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
