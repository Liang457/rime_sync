"""rime_server 应用工厂。"""
from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, jsonify

from .api import SERVER_VERSION, api_bp
from .console import console_bp
from .settings import Settings
from .services.scheduler import BaseUpdateScheduler
from .services.store import FileStore
from .services.upstream import BaseManager
from .services.userdb import UserDbStore

__version__ = SERVER_VERSION


def create_app(
    settings_path: Path | None = None,
    root_dir: Path | None = None,
    run_scheduler: bool = True,
) -> Flask:
    root = Path(root_dir) if root_dir else Path(__file__).resolve().parent.parent
    settings = Settings(settings_path if settings_path else root / "config" / "server.json")

    store = FileStore(root / "store")
    userdb = UserDbStore(root / "sync")
    upstream = BaseManager(store, root / "store" / "base", settings.base_repo_url)
    scheduler = BaseUpdateScheduler(settings, upstream, store)

    app = Flask(__name__)
    app.secret_key = settings.secret_key
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_bytes
    app.config["STARTED"] = time.time()
    app.json.ensure_ascii = False

    app.register_blueprint(
        api_bp(store, userdb, upstream, settings.token_ok,
               settings.record_token_use, root)
    )
    app.register_blueprint(
        console_bp(store, userdb, upstream, settings, root)
    )
    # 服务对象挂到 extensions，便于测试与后续扩展
    app.extensions["store"] = store
    app.extensions["userdb"] = userdb
    app.extensions["upstream"] = upstream
    app.extensions["settings"] = settings
    app.extensions["scheduler"] = scheduler
    if run_scheduler:  # 测试传 False，避免后台线程搅局
        scheduler.start()

    @app.errorhandler(404)
    def _not_found(e):
        if request_wants_json():
            return jsonify({"ok": False, "error": "not found"}), 404
        return e

    return app


def request_wants_json() -> bool:
    from flask import request

    return request.path.startswith("/api/")
