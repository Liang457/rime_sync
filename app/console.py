"""Web 控制台：页面 + 表单动作（htmx 局部刷新）。

认证：settings.password_hash 非空时整站走 session 登录；为空时免登录
（信任局域网模式，仪表盘会提示设置密码）。
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, current_app, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)

from .api import SERVER_VERSION
from .safe_path import safe_relpath
from .services import config_options, custom_yaml, rime_ice
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
        return {"console_protected": bool(settings.password_hash),
                "server_version": SERVER_VERSION}

    @bp.app_template_filter("human_size")
    def _human_size(n) -> str:
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    @bp.app_template_filter("epoch_fmt")
    def _epoch_fmt(ts) -> str:
        if not ts:
            return "—"
        try:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            return "—"

    def _device_labels() -> dict[str, str]:
        """installation_id → token 备注名；同设备多条 token 时取最近使用的。
        依据 token 条目上的 last_used_device（API 鉴权时记录），纯显示层映射。"""
        used = [t for t in settings.tokens
                if t.get("label") and t.get("last_used_device")]
        used.sort(key=lambda t: t.get("last_used") or "", reverse=True)
        return {t["last_used_device"]: t["label"] for t in used}

    def _dev_show(name: str) -> str:
        """设备的显示名：有备注名给 备注(id)，没有就裸 id。"""
        label = _device_labels().get(name)
        return f"{label}({name})" if label else name

    @bp.app_template_filter("dev_label")
    def _dev_label(text: str) -> str:
        """把文本里出现的设备 id 替换为 备注(id)——最近动态、confirm
        文案等历史内容也能在显示层受益。"""
        for dev, label in _device_labels().items():
            if dev in text:
                text = text.replace(dev, f"{label}({dev})")
        return text

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

    def file_rows(prefix: str = "all", source: str = "all", q: str = "",
                  include_base: bool = False) -> list[dict]:
        """词库文件页行数据。base 来源（rime-ice 基座）不属于本页——
        基座文件的全览在「上游基座」页，这里默认只看自定义内容。"""
        rows = []
        for rel, meta in sorted(store.manifest()["files"].items()):
            if not include_base and meta.get("source") == "base":
                continue
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
            device_labels=_device_labels(),
            activity=store.recent_activity(12),
            disk={"free": usage.free, "total": usage.total},
            base_status=upstream.status(),
            uptime_s=uptime_s,
        )

    # ---- 关于 ---------------------------------------------------------------

    @bp.route("/about")
    def about_page():
        started = float(current_app.config.get("STARTED", time.time()))
        return render_template(
            "about.html",
            started=started,
            uptime_s=round(time.time() - started, 1),
            py_version=platform.python_version(),
            os_name=f"{platform.system()} {platform.release()}",
            hostname=platform.node(),
            server_host=settings.host,
            server_port=settings.port,
            data_root=data_root,
            base_repo_url=settings.base_repo_url,
            base_auto_update=settings.base_auto_update,
            base_cron=settings.base_cron,
        )

    # ---- 词库文件（自定义内容；基座文件在「上游基座」页） ---------------------

    def _prefix_options() -> list[str]:
        tops = set()
        for rel, meta in store.manifest()["files"].items():
            if meta.get("source") == "base":
                continue
            if "/" in rel:
                tops.add(rel.split("/", 1)[0])
        ordered = [p for p in ("cn_dicts", "en_dicts", "lua", "opencc") if p in tops]
        ordered += sorted(t for t in tops if t not in ordered)
        return ordered

    def _source_options() -> list[str]:
        return [s for s in store.stats()["sources"] if s != "base"]

    @bp.route("/files")
    def files_page():
        prefix = request.args.get("prefix", "all")
        source = request.args.get("source", "all")
        q = request.args.get("q", "")
        return render_template(
            "files.html",
            rows=file_rows(prefix, source, q),
            toggle_rows=rime_ice.toggle_rows(store),
            prefix=prefix,
            source=source,
            q=q,
            prefix_options=_prefix_options(),
            sources=_source_options(),
        )

    @bp.route("/files/table")
    def files_table():
        return respond("partials/files_table.html", {
            "rows": file_rows(request.args.get("prefix", "all"),
                              request.args.get("source", "all"),
                              request.args.get("q", "")),
        })

    @bp.route("/files/toggles")
    def files_toggles():
        """词库开关卡片局部刷新（togglesUpdated 事件触发）。"""
        return respond("partials/toggles.html",
                       {"rows": rime_ice.toggle_rows(store)})

    @bp.route("/files/toggle", methods=["POST"])
    def files_toggle():
        """词库开关：开/关 rime_ice.dict.yaml 里的一个 import_tables 条目。"""
        table = request.form.get("table", "").strip()
        enabled = request.form.get("enabled") == "1"
        try:
            report = rime_ice.toggle_table(store, table, enabled)
        except ValueError as e:
            resp = jsonify({"ok": False, "error": str(e)})
            resp.headers.update(toast(str(e), "err"))
            return resp, 400
        msg = f"已启用 {table}" if enabled else f"已关闭 {table}"
        if report["changed"]:
            msg += "，import_tables 已更新（设备同步后重新部署生效）"
        resp = jsonify({"ok": True, "changed": report["changed"],
                        "revision": store.revision})
        resp.headers.update(toast(msg))
        return resp

    @bp.route("/files/upload", methods=["POST"])
    def files_upload():
        """简化上传：只选目标目录（默认 cn_dicts）+ 拖文件；同名文件先报告，
        前端确认后带 replace=1 批量替换。响应 JSON，前端 fetch 消费。"""
        uploads = [f for f in request.files.getlist("files") if f.filename]
        if not uploads:
            resp = jsonify({"ok": False, "error": "没有选择文件"})
            resp.headers.update(toast("没有选择文件", "err"))
            return resp, 400
        prefix = request.form.get("prefix", "").strip().strip("/")
        replace = request.form.get("replace") == "1"
        existing = store.manifest()["files"]
        items: list[AddItem] = []
        conflicts: list[str] = []
        skipped: list[str] = []
        for f in uploads:
            name = Path(f.filename).name
            try:
                rel = safe_relpath(f"{prefix}/{name}" if prefix else name)
            except ValueError as e:
                skipped.append(f"{name}（{e}）")
                continue
            if rel in existing and not replace:
                conflicts.append(rel)
                continue
            items.append(AddItem(rel, f.stream.read(), source="upload"))
        results = store.add_many(items, detail=f"控制台上传 {len(items)} 个文件")
        linkage = None
        if any(re.fullmatch(r"cn_dicts/.+\.dict\.yaml", r["path"])
               for r in results):
            linkage = rime_ice.sync_import_tables(store)
        resp = jsonify({
            "ok": True,
            "saved": results,
            "conflicts": conflicts,
            "skipped": skipped,
            "revision": store.revision,
            "rime_ice": linkage,
        })
        if conflicts:
            resp.headers["X-Upload-Conflicts"] = urllib.parse.quote(
                json.dumps(conflicts, ensure_ascii=False))
        return resp

    @bp.route("/files/delete", methods=["POST"])
    def files_delete():
        rel = request.form.get("path", "")
        try:
            ok = store.delete(rel, detail=f"控制台删除 {rel}")
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        if not ok:
            return "", 200, toast(f"清单中没有 {rel}", "err")
        msg = f"已删除 {rel}（移入回收站）"
        if re.fullmatch(r"cn_dicts/.+\.dict\.yaml", rel):
            linkage = rime_ice.sync_import_tables(store)
            if linkage and linkage["changed"]:
                msg += "，已同步 rime_ice.dict.yaml"
        return "", 200, toast(msg)

    @bp.route("/files/download/<path:rel>")
    def files_download(rel: str):
        path = store.get_path(rel)
        if path is None:
            return "文件不存在", 404
        return send_file(path, download_name=Path(rel).name)

    # ---- 配置管理（定制补丁 *.custom.yaml 表单 + 源码编辑） -------------------

    def _config_rels() -> list[str]:
        return [rel for rel in store.all_rels()
                if rel.split("/", 1)[0] not in ASSET_PREFIXES]

    def _custom_form_ctx(path: str, content: str) -> dict | None:
        """*.custom.yaml 的表单上下文；未注册的目标文件返回 None（只显示源码）。"""
        spec = config_options.target_for(path)
        if spec is None:
            return None
        ctx: dict = {"spec": spec, "error": "", "patch": {}, "base_values": {},
                     "schemas": []}
        try:
            ctx["patch"] = custom_yaml.parse_patch(content)
        except ValueError as e:
            ctx["error"] = str(e)
            return ctx
        sl = ctx["patch"].get("schema_list")
        ctx["schema_order"] = [
            e.get("schema") for e in sl
            if isinstance(e, dict) and e.get("schema")
        ] if isinstance(sl, list) else []
        base_data = config_options.base_yaml_data(store, spec.source_file)
        ctx["base_values"] = {
            opt.key: config_options.walk_path(base_data, opt.key)
            for g in spec.groups for opt in g.options
        }
        for opt in (o for g in spec.groups for o in g.options):
            if opt.type == "schema_list":
                ctx["schemas"] = config_options.available_schemas(store)
        return ctx

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
        ctx = {"path": path, "content": content, "meta": meta, "saved": saved,
               "revision": store.revision, "preset_custom": None}
        if meta.get("source") == "base":
            # 基座文件对应的定制补丁还没建 → 警示条里给一键创建入口
            stem = re.sub(r"(\.dict)?\.yaml$", "", path)
            candidate = f"{stem}.custom.yaml"
            if (candidate in config_options.PRESETS
                    and candidate not in store.manifest()["files"]):
                ctx["preset_custom"] = candidate
        if path.endswith(".custom.yaml"):
            ctx["custom"] = _custom_form_ctx(path, content)
        else:
            ctx["custom"] = None
        return ctx

    @bp.route("/configs")
    def configs_page():
        path = request.args.get("path", "")
        editor = _editor_ctx(path, saved=False) if path else None
        preset_files = list(config_options.PRESETS)
        rels = _config_rels()
        presets = [{"name": n, "desc": config_options.PRESETS[n]["desc"],
                    "exists": n in store.manifest()["files"]}
                   for n in preset_files]
        return render_template(
            "configs.html",
            presets=presets,
            custom_rels=[r for r in rels if r.endswith(".custom.yaml")
                         and r not in preset_files],
            other_rels=[r for r in rels if not r.endswith(".custom.yaml")],
            editor=editor,
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

    @bp.route("/configs/patch/save", methods=["POST"])
    def configs_patch_save():
        """「常用设置」表单保存：按注册表把表单值合并进 .custom.yaml patch。

        表单值约定：opt::<key>（select/number，空串=删除该键恢复基座默认；
        bool 用 "true"/"false"）；hotkey::<value> 多选框，全不选=删除；
        opt::schema_list_order 逗号分隔的已选方案顺序。
        """
        path = request.form.get("path", "")
        try:
            path = safe_relpath(path)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        meta = store.manifest()["files"].get(path)
        if meta is None:
            return "", 200, toast(f"清单中没有 {path}，请用「新建文件」", "err")
        spec = config_options.target_for(path)
        if spec is None:
            return "", 200, toast(f"{path} 没有常用设置表单，请用源码模式", "err")
        opts = config_options.option_map(spec)
        updates: dict[str, object] = {}
        removes: list[str] = []

        def drop(key: str) -> None:
            updates.pop(key, None)
            if key not in removes:
                removes.append(key)

        try:
            for key, opt in opts.items():
                if opt.type == "schema_list":
                    order = request.form.get("opt::schema_list_order", "")
                    ids = [s.strip() for s in order.split(",") if s.strip()]
                    known = {s["id"] for s in config_options.available_schemas(store)}
                    unknown = [i for i in ids if i not in known]
                    if unknown:
                        raise ValueError(f"未知方案：{'、'.join(unknown)}")
                    if ids:
                        updates[key] = [{"schema": i} for i in ids]
                    else:
                        drop(key)
                    continue
                if opt.type == "hotkeys":
                    picked = [c[0] for c in opt.choices
                              if request.form.get(f"hotkey::{c[0]}")]
                    if picked:
                        updates[key] = picked
                    else:
                        drop(key)
                    continue
                raw = (request.form.get(f"opt::{key}") or "").strip()
                if raw == "":
                    drop(key)
                elif opt.type == "bool":
                    if raw not in ("true", "false"):
                        raise ValueError(f"{opt.label} 的值无效")
                    updates[key] = raw == "true"
                elif opt.type == "int":
                    try:
                        val = int(raw)
                    except ValueError:
                        raise ValueError(f"{opt.label} 必须是整数") from None
                    if not opt.int_min <= val <= opt.int_max:
                        raise ValueError(
                            f"{opt.label} 须在 {opt.int_min}–{opt.int_max} 之间")
                    updates[key] = val
                elif opt.type in ("enum", "keyname"):
                    if raw not in dict(opt.choices):
                        raise ValueError(f"{opt.label} 的选项无效")
                    updates[key] = raw
                else:  # 预留：str 型
                    updates[key] = raw
        except ValueError as e:
            return "", 200, toast(str(e), "err")

        disk = store.get_path(path)
        current = disk.read_text(encoding="utf-8", errors="replace") if disk else ""
        try:
            new_text = custom_yaml.apply_patch(current, updates, removes)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        store.add_many(
            [AddItem(path, new_text.encode("utf-8"), source="console",
                     version=meta.get("version", ""))],
            detail=f"控制台表单保存 {path}",
        )
        return respond("partials/editor.html", _editor_ctx(path, saved=True),
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
        headers = toast(f"已创建 {path}")
        # 全页跳转到新文件，左侧列表与编辑器一次到位
        headers["HX-Redirect"] = url_for("console.configs_page", path=path)
        return "", 200, headers

    @bp.route("/configs/preset", methods=["POST"])
    def configs_preset():
        """预设定制文件：不存在则按模板创建（console 来源），整页跳进编辑器；
        已存在则直接打开，不重复创建。"""
        name = request.form.get("name", "").strip()
        preset = config_options.PRESETS.get(name)
        if preset is None:
            return "", 200, toast("未知的预设文件", "err")
        try:
            name = safe_relpath(name)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        existed = name in store.manifest()["files"]
        if not existed:
            store.add_many(
                [AddItem(name, preset["starter"].encode("utf-8"),
                         source="console")],
                detail=f"控制台新建预设 {name}",
            )
        headers = toast(f"已创建 {name}" if not existed else f"{name} 已存在")
        headers["HX-Redirect"] = url_for("console.configs_page", path=name)
        return "", 200, headers

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

    # ---- 上游基座（rime-ice 基座文件的全览入口） ------------------------------

    def _base_rows(q: str = "") -> list[dict]:
        rows = []
        for rel, meta in sorted(store.manifest()["files"].items()):
            if meta.get("source") != "base":
                continue
            if q and q.lower() not in rel.lower():
                continue
            rows.append({
                "path": rel,
                "version": meta.get("version", ""),
                "source": meta.get("source", ""),
                "size": meta.get("size", 0),
                "sha3": meta.get("sha3", "")[:20],
            })
        return rows

    @bp.route("/base")
    def base_page():
        q = request.args.get("q", "")
        return render_template(
            "base_repo.html",
            status=upstream.status(),
            origin=upstream.current_origin(),
            schedule=current_app.extensions["scheduler"].status(),
            base_rows=_base_rows(q),
            q=q,
        )

    @bp.route("/base/table")
    def base_table():
        q = request.args.get("q", "")
        return render_template("partials/base_table.html",
                               base_rows=_base_rows(q), status=upstream.status(),
                               q=q)

    @bp.route("/base/repo", methods=["POST"])
    def base_repo_set():
        """自定义更新地址：保存进 server.json 并切换已克隆仓库的 origin。"""
        url = request.form.get("repo_url", "")
        try:
            settings.set_base_repo_url(url)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        upstream.repo_url = settings.base_repo_url
        try:
            changed = upstream.set_repo_url(settings.base_repo_url)
        except GitError as e:
            return "", 200, toast(f"地址已保存，但切换远端失败：{e}", "err",
                                  baseUpdated={})
        msg = "仓库地址已保存" + ("，origin 已切换" if changed else "")
        return "", 200, toast(msg, baseUpdated={})

    @bp.route("/base/schedule", methods=["POST"])
    def base_schedule_set():
        """自动更新开关 + cron 表达式。"""
        enabled = request.form.get("enabled") == "on"
        cron = request.form.get("cron", "")
        try:
            settings.set_base_schedule(enabled, cron)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        current_app.extensions["scheduler"].reconfigure()
        return "", 200, toast(
            f"自动更新已{'开启，按 cron 排期' if enabled else '关闭'}", baseUpdated={})

    @bp.route("/base/reclone", methods=["POST"])
    def base_reclone():
        """删除本地基座目录重新克隆（换仓库/历史分叉的逃生通道）。"""
        try:
            report = upstream.reclone()
        except GitError as e:
            return "", 200, toast(f"重新克隆失败：{e}", "err", baseUpdated={})
        rb = report["rebuild"]
        return "", 200, toast(
            f"重新克隆完成：新增 {rb['added']}，更新 {rb['updated']}，"
            f"移除 {rb['removed']}", baseUpdated={})

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
        return render_template("devices.html", devices=userdb.devices(),
                               tokens=settings.tokens,
                               device_labels=_device_labels())

    @bp.route("/devices/table")
    def devices_table():
        return respond("partials/devices_table.html",
                       {"devices": userdb.devices(),
                        "device_labels": _device_labels()})

    @bp.route("/devices/delete", methods=["POST"])
    def devices_delete():
        name = request.form.get("device", "")
        show = _dev_show(name)
        try:
            ok = userdb.delete_device(name)
        except ValueError as e:
            return "", 200, toast(str(e), "err")
        if not ok:
            return "", 200, toast(f"设备 {show} 不存在", "err")
        store.activity("userdb", f"删除设备 {name}")
        # 前端 danger-action fetch 直发后触发 devicesUpdated 事件自刷新表格
        return "", 200, toast(f"已删除设备 {show}", devicesUpdated={})

    # ---- API token 管理（多 token，设备页） -----------------------------------

    def _tokens_ctx() -> dict:
        return {"tokens": settings.tokens}

    @bp.route("/devices/tokens/table")
    def tokens_table():
        return respond("partials/tokens_table.html", _tokens_ctx())

    @bp.route("/devices/tokens/create", methods=["POST"])
    def tokens_create():
        entry = settings.add_token(request.form.get("label", ""))
        store.activity("token", f"签发 API token（{entry['label'] or '未命名'}）")
        return respond("partials/tokens_table.html", _tokens_ctx(),
                       "已生成 token，请立即复制保存")

    @bp.route("/devices/tokens/delete", methods=["POST"])
    def tokens_delete():
        token = request.form.get("token", "")
        if not settings.remove_token(token):
            return "", 200, toast("token 不存在", "err")
        store.activity("token", "吊销一个 API token")
        return "", 200, toast("已吊销 token", tokensUpdated={})

    return bp
