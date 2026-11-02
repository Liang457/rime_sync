"""设备用户词库快照中转。

各设备跑 librime 的 sync_user_data 生成 sync/<installation_id>/ 文本快照；
服务器只按设备分桶存放与转发，合并永远在客户端由 librime UserDbMerger 完成。
"""
from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from ..safe_path import safe_device_name

_REGISTRY = "_devices.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class UserDbStore:
    def __init__(self, root: Path):
        self.root = root
        self.registry_path = root / _REGISTRY
        self.root.mkdir(parents=True, exist_ok=True)
        self._registry: dict = self._load_registry()

    # ---- 注册表 ----------------------------------------------------------

    def _load_registry(self) -> dict:
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_registry(self) -> None:
        self.registry_path.write_text(
            json.dumps(self._registry, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---- 设备 ------------------------------------------------------------

    def devices(self) -> list[dict]:
        """磁盘目录 ∪ 注册表；目录存在但注册表缺失的设备当场补录。"""
        result: list[dict] = []
        seen: set[str] = set()
        for d in sorted(self.root.iterdir()) if self.root.exists() else []:
            if not d.is_dir() or d.name.startswith("_"):
                continue
            seen.add(d.name)
            info = self._device_dir_info(d)
            reg = self._registry.get(d.name, {})
            result.append(
                {
                    "device": d.name,
                    "files": info["files"],
                    "size": info["size"],
                    "last_push": reg.get("last_push", ""),
                }
            )
        for name, reg in sorted(self._registry.items()):
            if name not in seen:
                result.append(
                    {
                        "device": name,
                        "files": reg.get("files", 0),
                        "size": reg.get("size", 0),
                        "last_push": reg.get("last_push", ""),
                    }
                )
        return result

    @staticmethod
    def _device_dir_info(d: Path) -> dict:
        files = 0
        size = 0
        for p in d.rglob("*"):
            if p.is_file():
                files += 1
                size += p.stat().st_size
        return {"files": files, "size": size}

    def delete_device(self, name: str) -> bool:
        name = safe_device_name(name)
        d = self.root / name
        existed = d.is_dir()
        if existed:
            import shutil

            shutil.rmtree(d)
        self._registry.pop(name, None)
        self._save_registry()
        return existed or name in self._registry

    # ---- 推 / 拉 ---------------------------------------------------------

    def push(self, device: str, tar_fileobj) -> dict:
        """接收本机快照 tar.gz（包内为相对路径文件），落到 sync/<device>/。"""
        device = safe_device_name(device)
        dest = self.root / device
        dest.mkdir(parents=True, exist_ok=True)
        count = 0
        with tarfile.open(fileobj=tar_fileobj, mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.isdev() or not member.isfile():
                    continue
                rel = member.name.replace("\\", "/")
                if any(part in ("", ".", "..") for part in rel.split("/")):
                    raise ValueError(f"tar 内出现非法路径: {member.name}")
                out = dest / rel
                if not (dest.resolve() in out.resolve().parents):
                    raise ValueError(f"tar 内路径越界: {member.name}")
                out.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                out.write_bytes(src.read())
                count += 1
        info = self._device_dir_info(dest)
        self._registry[device] = {
            "last_push": _now_iso(),
            "files": info["files"],
            "size": info["size"],
        }
        self._save_registry()
        return {"device": device, "files": info["files"], "size": info["size"]}

    def pull_tar_bytes(self, exclude: str | None = None) -> tuple[bytes, int]:
        """打包其他设备的快照，包内路径 = <device>/<文件>；本地 librime 负责合并。"""
        if exclude:
            exclude = safe_device_name(exclude)
        buf = io.BytesIO()
        count = 0
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for d in sorted(self.root.iterdir()) if self.root.exists() else []:
                if not d.is_dir() or d.name.startswith("_") or d.name == exclude:
                    continue
                for p in sorted(d.rglob("*")):
                    if p.is_file():
                        tf.add(str(p), arcname=f"{d.name}/{p.relative_to(d).as_posix()}",
                               recursive=False)
                        count += 1
        return buf.getvalue(), count
