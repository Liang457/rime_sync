"""统一文件库：store/files/ 下的一切文件 + 一份 manifest.json。

词库、lua、opencc、方案配置全部走同一个模型；客户端只对 manifest 做差量。
manifest 结构：
{
  "revision": int,          # 每次有实际变更 +1
  "updated_at": iso 时间,
  "files": {
    "<rel path>": {"sha3": "sha3-256:<hex>", "size": int, "mtime": float,
                    "version": str, "source": str}
  }
}
source 语义：base=上游基座 / publish=rime_dict 发布 / console=控制台 /
upload=控制台上传 / migrate=旧数据迁移。source 即 overlay 归属——基座重建时
非 base 来源的文件受保护不被覆盖。
"""
from __future__ import annotations

import io
import json
import shutil
import tarfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..hash_utils import hash_tag, sha3_256_bytes, sha3_256_file
from ..safe_path import safe_relpath


@dataclass
class AddItem:
    rel: str
    data: Path | bytes
    source: str = "publish"
    version: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class FileStore:
    def __init__(self, root: Path):
        self.root = root
        self.files_dir = root / "files"
        self.manifest_path = root / "manifest.json"
        self.trash_dir = root / "trash"
        self.activity_path = root / "activity.json"
        self._lock = threading.RLock()
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._manifest: dict = self._load_manifest()

    # ---- manifest 基础 ---------------------------------------------------

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            try:
                m = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                m.setdefault("revision", 0)
                m.setdefault("updated_at", "")
                m.setdefault("files", {})
                return m
            except (json.JSONDecodeError, OSError):
                pass
        return {"revision": 0, "updated_at": _now_iso(), "files": {}}

    def _save_manifest(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(self.manifest_path)

    @property
    def revision(self) -> int:
        return self._manifest["revision"]

    def manifest(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._manifest))

    def activity(self, kind: str, detail: str) -> None:
        with self._lock:
            entries = []
            if self.activity_path.exists():
                try:
                    entries = json.loads(self.activity_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    entries = []
            entries.insert(0, {"time": _now_iso(), "kind": kind, "detail": detail})
            self.activity_path.write_text(
                json.dumps(entries[:100], ensure_ascii=False, indent=1), encoding="utf-8"
            )

    def recent_activity(self, n: int = 20) -> list[dict]:
        if not self.activity_path.exists():
            return []
        try:
            entries = json.loads(self.activity_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return entries[:n]

    # ---- 写入 ------------------------------------------------------------

    def _disk_path(self, rel: str) -> Path:
        rel = safe_relpath(rel)
        path = (self.files_dir / rel).resolve()
        root = self.files_dir.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"路径越界: {rel}")
        return path

    def _write_file(self, rel: str, data: Path | bytes) -> tuple[str, int]:
        """落盘并返回 (hash标签, size)。"""
        path = self._disk_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
            digest = sha3_256_bytes(data)
        else:
            shutil.copyfile(data, path)
            digest = sha3_256_file(path)
        return hash_tag(digest), path.stat().st_size

    def add_many(self, items: list[AddItem], detail: str = "") -> list[dict]:
        """批量入库，整个批次最多 revision +1，原子更新 manifest。"""
        results: list[dict] = []
        with self._lock:
            changed = False
            for item in items:
                rel = safe_relpath(item.rel)
                tag, size = self._write_file(rel, item.data)
                old = self._manifest["files"].get(rel)
                if old and old["sha3"] == tag:
                    status = "unchanged"
                    # 内容不变但来源/版本标注变了也算一次 manifest 修订
                    if old.get("source") != item.source or old.get("version") != item.version:
                        old["source"] = item.source
                        old["version"] = item.version
                        changed = True
                else:
                    status = "updated" if old else "created"
                    self._manifest["files"][rel] = {
                        "sha3": tag,
                        "size": size,
                        "mtime": self._disk_path(rel).stat().st_mtime,
                        "version": item.version,
                        "source": item.source,
                    }
                    changed = True
                results.append({"path": rel, "status": status, "sha3": tag, "size": size})
            if changed:
                self._manifest["revision"] += 1
                self._manifest["updated_at"] = _now_iso()
                self._save_manifest()
            if any(r["status"] != "unchanged" for r in results):
                summary = detail or f"{len(items)} 个文件"
                self.activity("files", summary)
        return results

    def get_path(self, rel: str) -> Path | None:
        rel = safe_relpath(rel)
        if rel not in self._manifest["files"]:
            return None
        path = self._disk_path(rel)
        return path if path.is_file() else None

    def delete(self, rel: str, detail: str = "") -> bool:
        rel = safe_relpath(rel)
        with self._lock:
            if rel not in self._manifest["files"]:
                return False
            path = self._disk_path(rel)
            if path.is_file():
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = self.trash_dir / stamp / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
            del self._manifest["files"][rel]
            self._manifest["revision"] += 1
            self._manifest["updated_at"] = _now_iso()
            self._save_manifest()
            self.activity("delete", detail or rel)
        return True

    # ---- 基座重建 --------------------------------------------------------

    def rebuild_base(
        self, incoming: dict[str, Path], version: str, force: bool = False,
        detail: str = "",
    ) -> dict:
        """用基座目录重建 store：base 来源直接覆盖，其他来源受保护。

        incoming: rel -> 基座内文件路径。上一轮 base 来源但本轮缺席的文件会被移除。
        """
        report = {"added": 0, "updated": 0, "unchanged": 0, "skipped": [], "removed": 0}
        with self._lock:
            changed = False
            for rel in sorted(incoming):
                old = self._manifest["files"].get(rel)
                if old and old.get("source") != "base" and not force:
                    report["skipped"].append(
                        {"path": rel, "reason": f"已被 {old.get('source')} 占用"}
                    )
                    continue
                tag, size = self._write_file(rel, incoming[rel])
                if old and old["sha3"] == tag:
                    if old.get("source") != "base" or old.get("version") != version:
                        old["source"] = "base"
                        old["version"] = version
                        changed = True
                    report["unchanged"] += 1
                else:
                    report["updated" if old else "added"] += 1
                    self._manifest["files"][rel] = {
                        "sha3": tag,
                        "size": size,
                        "mtime": self._disk_path(rel).stat().st_mtime,
                        "version": version,
                        "source": "base",
                    }
                    changed = True
            for rel in [
                r for r, m in self._manifest["files"].items()
                if m.get("source") == "base" and r not in incoming
            ]:
                path = self._disk_path(rel)
                if path.is_file():
                    path.unlink(missing_ok=True)
                del self._manifest["files"][rel]
                report["removed"] += 1
                changed = True
            if changed:
                self._manifest["revision"] += 1
                self._manifest["updated_at"] = _now_iso()
                self._save_manifest()
            self.activity(
                "base-rebuild",
                detail or (
                    f"+{report['added']} ~{report['updated']} ={report['unchanged']} "
                    f"-{report['removed']} 跳过{len(report['skipped'])}"
                ),
            )
        return report

    # ---- zip 导入 --------------------------------------------------------

    def import_zip(
        self, fileobj, *, strip_top: bool = False, force: bool = False,
        source: str = "upload", version: str = "",
    ) -> dict:
        """把 zip 包内的文件按包内相对路径入库；strip_top 剥掉一层顶层目录。

        与 rebuild_base 相同的保护规则：非本来源已占用的文件默认跳过，force 才接管。
        """
        items: list[AddItem] = []
        skipped: list[dict] = []
        with self._lock, zipfile.ZipFile(fileobj) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            tops = {m.filename.split("/", 1)[0] for m in members if "/" in m.filename}
            single_top = tops.pop() if len(tops) == 1 and strip_top else None
            for m in members:
                rel = m.filename
                if single_top and rel.startswith(single_top + "/"):
                    rel = rel[len(single_top) + 1:]
                if not rel or rel.endswith("/"):
                    continue
                try:
                    rel = safe_relpath(rel)
                except ValueError as e:
                    skipped.append({"path": m.filename, "reason": str(e)})
                    continue
                old = self._manifest["files"].get(rel)
                if old and old.get("source") != source and not force:
                    skipped.append(
                        {"path": rel, "reason": f"已被 {old.get('source')} 占用"})
                    continue
                items.append(AddItem(rel, zf.read(m), source=source, version=version))
        results = self.add_many(items, detail=f"zip 导入 {len(items)} 个文件")
        report = {
            "added": sum(r["status"] == "created" for r in results),
            "updated": sum(r["status"] == "updated" for r in results),
            "unchanged": sum(r["status"] == "unchanged" for r in results),
            "skipped": skipped,
            "results": results,
        }
        return report

    # ---- 打包 ------------------------------------------------------------

    def tar_bytes(self, rels: list[str]) -> tuple[bytes, list[str]]:
        """把指定文件打成 tar.gz（包内路径 = manifest 相对路径）。"""
        buf = io.BytesIO()
        missing: list[str] = []
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for rel in rels:
                path = self.get_path(rel)
                if path is None:
                    missing.append(rel)
                    continue
                tf.add(str(path), arcname=rel, recursive=False)
        return buf.getvalue(), missing

    def all_rels(self) -> list[str]:
        return sorted(self._manifest["files"])

    # ---- 统计 ------------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            files = self._manifest["files"]
            by_prefix: dict[str, dict] = {}
            sources: set[str] = set()
            total = 0
            for rel, meta in files.items():
                prefix = rel.split("/", 1)[0] if "/" in rel else "（根目录）"
                bucket = by_prefix.setdefault(prefix, {"count": 0, "size": 0})
                bucket["count"] += 1
                bucket["size"] += meta.get("size", 0)
                total += meta.get("size", 0)
                sources.add(meta.get("source", ""))
            return {
                "revision": self._manifest["revision"],
                "updated_at": self._manifest["updated_at"],
                "file_count": len(files),
                "total_size": total,
                "by_prefix": by_prefix,
                "sources": sorted(s for s in sources if s),
            }
