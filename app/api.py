"""面向客户端的同步 API。所有响应 JSON（除文件/tar 下载）。

认证：token_ok(got) 为假时（除 /api/health 外）一律 401；token 支持多个，
在控制台设备页管理。
"""
from __future__ import annotations

import io
import re
import shutil
import tarfile
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from .safe_path import safe_device_name, safe_relpath
from .services import rime_ice
from .services.publish import publish_files
from .services.store import FileStore
from .services.upstream import BaseManager
from .services.userdb import UserDbStore

SERVER_VERSION = "0.1.0"


def api_bp(
    store: FileStore, userdb: UserDbStore, upstream: BaseManager,
    token_ok, data_root: Path,
) -> Blueprint:
    bp = Blueprint("api", __name__, url_prefix="/api")
    started = time.time()

    @bp.before_request
    def _auth():
        if request.path == "/api/health":
            return None
        if not token_ok(request.headers.get("X-Api-Token", "")):
            return jsonify({"ok": False, "error": "缺少或错误的 X-Api-Token"}), 401
        return None

    @bp.errorhandler(413)
    def _too_large(_e):
        return jsonify({"ok": False, "error": "请求体超过服务器上传上限"}), 413

    # ---- 清单 ---------------------------------------------------------------

    @bp.get("/manifest")
    def manifest():
        m = store.manifest()
        return jsonify(
            {"revision": m["revision"], "updated_at": m["updated_at"],
             "files": m["files"]}
        )

    # ---- 文件下载 -----------------------------------------------------------

    @bp.get("/files/get/<path:rel>")
    def get_file(rel: str):
        try:
            path = store.get_path(rel)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if path is None:
            return jsonify({"ok": False, "error": f"清单中没有该文件: {rel}"}), 404
        return send_file(path, download_name=rel.replace("/", "_"))

    @bp.get("/files/get")
    def get_files_tar():
        """打包下载：?paths=a,b,c 或 ?all=1（首装/重建用）。"""
        if request.args.get("all"):
            rels = store.all_rels()
        else:
            rels = []
            for chunk in request.args.getlist("paths"):
                rels.extend(s for s in chunk.split(",") if s)
        rels = list(dict.fromkeys(rels))
        if not rels:
            return jsonify({"ok": False, "error": "缺少 paths 或 all 参数"}), 400
        try:
            data, missing = store.tar_bytes(rels)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if missing:
            return jsonify({"ok": False, "error": "部分文件不在清单中",
                            "missing": missing}), 404
        return send_file(
            io.BytesIO(data), mimetype="application/gzip", as_attachment=True,
            download_name="rime-files.tar.gz",
        ), {
            "X-File-Count": str(len(rels)),
            "X-Manifest-Revision": str(store.revision),
        }

    # ---- 发布 ---------------------------------------------------------------

    @bp.post("/publish")
    def publish():
        uploads = request.files.getlist("file") + request.files.getlist("files")
        if not uploads:
            return jsonify({"ok": False, "error": "没有收到文件字段 file/files"}), 400
        version = request.form.get("version", "")
        source = request.form.get("source", "publish")
        path_override = request.form.get("path", "").strip()
        if path_override and len(uploads) > 1:
            return jsonify({"ok": False, "error": "path 参数只能配单个文件"}), 400
        files = []
        for f in uploads:
            rel = path_override or f.filename
            try:
                rel = safe_relpath(rel)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            files.append((rel, f.stream.read()))
        results = publish_files(store, files, source=source, version=version,
                                detail=f"publish {len(files)} 个文件")
        # cn_dicts 词库发布后自动联动 rime_ice.dict.yaml 的 import_tables
        linkage = None
        if any(re.fullmatch(r"cn_dicts/.+\.dict\.yaml", r["path"]) and
               r["status"] != "unchanged" for r in results):
            linkage = rime_ice.sync_import_tables(store)
        return jsonify({"ok": True, "revision": store.revision, "results": results,
                        "rime_ice": linkage})

    # ---- 用户词库 -----------------------------------------------------------

    @bp.post("/userdb/push")
    def userdb_push():
        device = request.form.get("device") or request.args.get("device") or ""
        if not device:
            return jsonify({"ok": False, "error": "缺少 device 参数"}), 400
        try:
            device = safe_device_name(device)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        tar_file = request.files.get("tar") or next(iter(request.files.values()), None)
        if tar_file is None:
            return jsonify({"ok": False, "error": "没有收到 tar 文件字段"}), 400
        try:
            info = userdb.push(device, tar_file.stream)
        except (ValueError, tarfile.TarError) as e:
            return jsonify({"ok": False, "error": f"tar 解析失败: {e}"}), 400
        store.activity("userdb", f"{device} push {info['files']} 个文件")
        return jsonify({"ok": True, **info})

    @bp.get("/userdb/pull")
    def userdb_pull():
        exclude = request.args.get("device") or None
        try:
            data, count = userdb.pull_tar_bytes(exclude=exclude)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        resp = send_file(
            io.BytesIO(data), mimetype="application/gzip", as_attachment=True,
            download_name="userdb-sync.tar.gz",
        )
        resp.headers["X-Sync-File-Count"] = str(count)
        return resp

    # ---- 健康与状态 -----------------------------------------------------------

    @bp.get("/health")
    def health():
        usage = shutil.disk_usage(data_root)
        return jsonify(
            {
                "status": "ok",
                "server_version": SERVER_VERSION,
                "uptime_s": round(time.time() - started, 1),
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "disk": {"free": usage.free, "total": usage.total, "used": usage.used},
            }
        )

    @bp.get("/status")
    def status():
        stats = store.stats()
        return jsonify(
            {
                "server_version": SERVER_VERSION,
                "revision": stats["revision"],
                "updated_at": stats["updated_at"],
                "file_count": stats["file_count"],
                "total_size": stats["total_size"],
                "sources": stats["sources"],
                "devices": len(userdb.devices()),
                "base": upstream.status(),
            }
        )

    return bp
