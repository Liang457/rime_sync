import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


@pytest.fixture()
def env(tmp_path):
    """隔离环境：独立 data 根目录 + 无 token + 免登录。返回 (app, client, root)。"""
    root = tmp_path
    app = create_app(settings_path=root / "config" / "server.json", root_dir=root)
    app.config["TESTING"] = True
    return app, app.test_client(), root


@pytest.fixture()
def tokened_env(tmp_path):
    """开了 api_token 的隔离环境。"""
    root = tmp_path
    settings_path = root / "config" / "server.json"
    app = create_app(settings_path=settings_path, root_dir=root)
    app.config["TESTING"] = True
    # 直接改写已加载的 settings 并重新绑定蓝图不现实——create_app 时读 token，
    # 这里用 json 改文件 + 重建 app
    import json

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["server"]["api_token"] = "sekrit"
    settings_path.write_text(json.dumps(data), encoding="utf-8")
    app = create_app(settings_path=settings_path, root_dir=root)
    app.config["TESTING"] = True
    return app, app.test_client(), root
