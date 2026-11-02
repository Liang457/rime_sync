"""Web 控制台：页面 + 表单动作（htmx 局部刷新）。

认证：settings.password_hash 非空时整站走 session 登录；为空时免登录
（信任局域网模式，仪表盘会提示设置密码）。
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.parse
from pathlib import Path

from flask import (
    Blueprint, current_app, redirect, render_template, request, send_file,
    session, url_for,
)

from .safe_path import safe_relpath
from .services.store import AddItem, FileStore
from .services.upstream import BaseManager, GitError
from .services.userdb import UserDbStore

ASSET_PREFIXES = ("cn_dicts", "en_dicts", "lua", "opencc")


def console_bp(
    store: FileStore, userdb: UserDbStore, upstream: BaseManager,
    settings, data_root: Path,
) -> Blueprint:
    bp = Blueprint("console", __name__)

    # ---- 认证 ---------------------------------------------------------------

    @bp.before_request
    def _auth():
        if not settings.password_hash:
            return None
        if request.endpoint in ("console.login", "console.logout"):
            return None
        if session.get("authed"):
            return None
        return redirect(url_for("console.login", next=request.path))

    @bp.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            if settings.check_password(request.form.get("password", "")):
                session["authed"] = True
                target = request.form.get("next") or url_for("console.dashboard")
                return redirect(target)
            error = "密码不对"
        return render_template("login.html", error=error,
                               next=request.values.get("next", ""))

    @bp.route("/logout")
    def logout():
        session.pop("authed", None)
        return redirect(url_for("console.login"))

    # ---- 模板环境 -----------------------------------------------------------

    @bp.app_context_processor
    def _inject():
        return {"console_protected": bool(settings.password_hash)}

    @bp.app_template_filter("human_size")
    def _human_size(n) -> str:
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def toast(message: str | None, tone: str = "ok", **extra_events) -> dict:
        """htmx 动作反馈：中文 toast 数据走 percent-encoded X-Toast-Data 头
        （HTTP 头仅 latin-1，不能直接放中文），HX-Trigger 只承载 ASCII 事件名。"""
        headers: dict = {}
        if message is not None:
            headers["X-Toast-Data"] = urllib.parse.quote(
                json.dumps({"message": message, "tone": tone},
                           ensure_ascii=False))
        if extra_events:
            headers["HX-Trigger"] = json.dumps(extra_events)
        return headers

    def respond(template: str, ctx: dict, message: str | None = None,
                tone: str = "ok", **extra_events):
        """htmx 动作统一出口：渲染局部模板 + 顺带吐 toast。"""
        headers = toast(message, tone, **extra_events)
        return render_template(template, **ctx), 200, headers

    def file_rows(prefix: str = "all", source: str = "all", q: str = "") -> list[dict]:
        rows = []
        for rel, meta in sorted(store.manifest()["files"].items()):
            top = rel.split("/", 1)[0] if "/" in rel else "（根目录）"
            if prefix == "root":
                if "/" in rel:
                    continue
            elif prefix != "all" and top != prefix:
                continue
            if source != "all" and meta.get("source") != source:
                continue
            if q and q.lower() not in rel.lower():
                continue
            rows.append({
                "path": rel,
                "version": meta.get("version", ""),
                "source": meta.get("source", ""),
                "size": meta.get("size", 0),
                "sha3": meta.get("sha3", "")[:20],
                "mtime": meta.get("mtime", 0),
            })
        return rows

    # ---- 仪表盘 -----------------------------------------------------------

    @bp.route("/")
    def dashboard():
        stats = store.stats()
        usage = shutil.disk_usage(data_root)
        uptime_s = round(time.time() - float(current_app.config.get(
            "STARTED", time.time())), 1)
        return render_template(
            "dashboard.html",
            stats=stats,
            devices=userdb.devices(),
            activity=store.recent_activity(12),
            disk={"free": usage.free, "total": usage.total},
            base_status=upstream.status(),
            uptime_s=uptime_s,
        )

    # ---- 词库文件 -----------------------------------------------------------

    def _prefix_options() -> list[str]:
        tops = set()
        for rel in store.all_rels():
            if "/" in rel:
                tops.add(rel.split("/", 1)[0])
        ordered = [p for p in ("cn_dicts", "en_dicts", "lua", "opencc") if p in tops]
        ordered += sorted(t for t in tops if t not in ordered)
        return ordered

    @bp.route("/files")
    def files_page():
        prefix = request.args.get("prefix", "all")
        source = request.args.get("source", "all")
        q = request.args.get("q", "")
        return render_template(
            "files.html",
            rows=file_rows(prefix, source, q),
            prefix=prefix,
            source=source,
            q=q,
            prefix_options=_prefix_options(),
            sources=store.stats()["sources"],
        )

    @bp.route("/files/table")
    def files_table():
        return respond("partials/files_table.html", {
            "rows": file_rows(request.args.get("prefix", "all"),
                              request.args.get("source", "all"),
                              request.args.get("q", "")),
        })

    @bp.route("/files/upload", methods=["POST"])
    def files_upload():
        uploads = request.files.getlist("files")
        if not uploads or uploads[0].filename == "":
            return respond("partials/files_table.html",
                           {"rows": _upload_view_rows()}, "没有选择文件", "err")
        prefix = request.form.get("prefix", "").strip().strip("/")
        version = request.form.get("version", "").strip()
        source = request.form.get("source", "upload").strip() or "upload"
        items: list[AddItem] = []
        skipped: list[str] = []
        for f in uploads:
            name = Path(f.filename).name
            try:
                rel = safe_relpath(f"{prefix}/{name}" if prefix else name)
            except ValueError as e:
                skipped.append(f"{name}（{e}）")
                continue
            items.append(AddItem(rel, f.stream.read(), source=source, version=version))
        results = store.add_many(items, detail=f"控制台上传 {len(items)} 个文件")
        created = sum(r["status"] == "created" for r in results)
        updated = sum(r["status"] == "updated" for r in results)
        unchanged = sum(r["status"] == "unchanged" for r in results)
        msg = f"新增 {created}，更新 {updated}，不变 {unchanged}"
        if skipped:
            msg += f"；非法路径跳过 {len(skipped)}"
        return respond("partials/files_table.html",
                       {"rows": _upload_view_rows()},
                       msg, "ok" if not skipped else "err")

    def _upload_view_rows() -> list[dict]:
        return file_rows(request.form.get("prefix_f", "all"),
                         request.form.get("source_f", "all"),
                         request.form.get("q_f", ""))

    @bp.route("/files/delete", methods=["POST"])
    def files_delete():
        rel = request.form.get("path", "")
        try:
            ok = store.delete(rel, detail=f"控制台删除 {rel}")
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        if not ok:
            return "", 200, toast(f"清单中没有 {rel}", "err")
        return "", 200, toast(f"已删除 {rel}（移入回收站）")

    @bp.route("/files/download/<path:rel>")
    def files_download(rel: str):
        path = store.get_path(rel)
        if path is None:
            return "文件不存在", 404
        return send_file(path, download_name=Path(rel).name)

    # ---- 配置管理 -----------------------------------------------------------

    def _config_rels() -> list[str]:
        return [rel for rel in store.all_rels()
                if rel.split("/", 1)[0] not in ASSET_PREFIXES]

    def _editor_ctx(path: str, saved: bool) -> dict | None:
        try:
            path = safe_relpath(path)
        except ValueError:
            return None
        meta = store.manifest()["files"].get(path)
        if meta is None:
            return None
        disk = store.get_path(path)
        content = disk.read_text(encoding="utf-8", errors="replace") if disk else ""
        return {"path": path, "content": content, "meta": meta, "saved": saved,
                "revision": store.revision}

    @bp.route("/configs")
    def configs_page():
        path = request.args.get("path", "")
        editor = _editor_ctx(path, saved=False) if path else None
        return render_template(
            "configs.html", config_rels=_config_rels(), editor=editor,
            current_path=path,
        )

    @bp.route("/configs/editor")
    def configs_editor():
        ctx = _editor_ctx(request.args.get("path", ""), saved=False)
        if ctx is None:
            return "文件不存在或不在清单中", 404
        return render_template("partials/editor.html", **ctx)

    @bp.route("/configs/save", methods=["POST"])
    def configs_save():
        path = request.form.get("path", "")
        content = request.form.get("content", "")
        try:
            path = safe_relpath(path)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        meta = store.manifest()["files"].get(path)
        if meta is None:
            return "", 200, toast(f"清单中没有 {path}，请用「新建文件」", "err")
        store.add_many(
            [AddItem(path, content.encode("utf-8"), source="console",
                     version=meta.get("version", ""))],
            detail=f"控制台编辑 {path}",
        )
        return respond("partials/editor.html",
                       _editor_ctx(path, saved=True),
                       f"已保存 {path}（revision {store.revision}）")

    @bp.route("/configs/create", methods=["POST"])
    def configs_create():
        path = request.form.get("path", "")
        content = request.form.get("content", "")
        try:
            path = safe_relpath(path)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        if path in store.manifest()["files"]:
            return "", 200, toast(f"{path} 已存在，请直接编辑", "err")
        store.add_many(
            [AddItem(path, content.encode("utf-8"), source="console")],
            detail=f"控制台新建 {path}",
        )
        return "", 200, toast(f"已创建 {path}")

    @bp.route("/configs/upload", methods=["POST"])
    def configs_upload():
        path = request.form.get("path", "")
        f = request.files.get("file")
        if f is None or f.filename == "":
            return "", 200, toast("没有选择文件", "err")
        try:
            path = safe_relpath(path)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        meta = store.manifest()["files"].get(path)
        if meta is None:
            return "", 200, toast(f"清单中没有 {path}", "err")
        store.add_many(
            [AddItem(path, f.stream.read(), source="console",
                     version=meta.get("version", ""))],
            detail=f"控制台上传覆盖 {path}",
        )
        return respond("partials/editor.html", _editor_ctx(path, saved=True),
                       f"已覆盖 {path}")

    # ---- 上游基座 -----------------------------------------------------------

    def _base_rows() -> list[dict]:
        return [
            {"path": rel, "version": meta.get("version", ""),
             "size": meta.get("size", 0)}
            for rel, meta in sorted(store.manifest()["files"].items())
            if meta.get("source") == "base"
        ]

    @bp.route("/base")
    def base_page():
        return render_template("base_repo.html", status=upstream.status(),
                               base_rows=_base_rows())

    @bp.route("/base/table")
    def base_table():
        return render_template("partials/base_table.html",
                               base_rows=_base_rows(), status=upstream.status())

    @bp.route("/base/update", methods=["POST"])
    def base_update():
        force = request.form.get("force") == "on"
        try:
            report = upstream.update_and_rebuild(force=force)
        except GitError as e:
            return respond("partials/base_report.html",
                           {"report": None, "error": str(e)},
                           f"基座更新失败：{e}", "err")
        rb = report["rebuild"]
        commit = report["git"]["commit"][:24]
        msg = (f"基座 {commit}：新增 {rb['added']}，更新 {rb['updated']}，"
               f"移除 {rb['removed']}，保护 {len(rb['skipped'])}")
        return respond("partials/base_report.html",
                       {"report": report, "error": None}, msg, baseUpdated={})

    # ---- 设备 ---------------------------------------------------------------

    @bp.route("/devices")
    def devices_page():
        return render_template("devices.html", devices=userdb.devices())

    @bp.route("/devices/table")
    def devices_table():
        return respond("partials/devices_table.html",
                       {"devices": userdb.devices()})

    @bp.route("/devices/delete", methods=["POST"])
    def devices_delete():
        name = request.form.get("device", "")
        try:
            ok = userdb.delete_device(name)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        if not ok:
            return "", 200, toast(f"设备 {name} 不存在", "err")
        store.activity("userdb", f"删除设备 {name}")
        return respond("partials/devices_table.html",
                       {"devices": userdb.devices()}, f"已删除设备 {name}")

    return bp
