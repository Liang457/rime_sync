"""控制台：页面渲染、上传/删除、配置编辑、基座更新（假 git）、登录。"""
import hashlib
import io
import json
import urllib.parse

import pytest

from app import create_app
from app.services.upstream import GitError


def toast_of(resp) -> str:
    """取响应里的中文 toast 消息（percent-encoded）。"""
    return urllib.parse.unquote(resp.headers.get("X-Toast-Data", ""))


def upload_file(client, rel, content, prefix="", **form):
    return client.post("/files/upload", data={
        "files": (io.BytesIO(content), rel.rsplit("/", 1)[-1]),
        "prefix": prefix,
        "prefix_f": "all", "source_f": "all", "q_f": "",
        **form,
    }, content_type="multipart/form-data")


# ---- 页面 -----------------------------------------------------------------


@pytest.mark.parametrize("page", ["/", "/files", "/configs", "/base", "/devices"])
def test_pages_render(env, page):
    app, client, root = env
    r = client.get(page)
    assert r.status_code == 200
    assert b"RIME" in r.data


# ---- 词库文件上传 / 删除 -----------------------------------------------------


def test_upload_and_table(env):
    app, client, root = env
    r = upload_file(client, "zzz.dict.yaml", b"ENTRY\t100", prefix="cn_dicts",
                    version="3.3", source="rime_dict")
    assert r.status_code == 200
    assert "cn_dicts/zzz.dict.yaml".encode() in r.data  # 返回的表格局部里出现
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert manifest["files"]["cn_dicts/zzz.dict.yaml"]["source"] == "rime_dict"


def test_upload_without_files_shows_error_toast(env):
    app, client, root = env
    r = client.post("/files/upload", data={"prefix_f": "all", "source_f": "all",
                                           "q_f": ""},
                    content_type="multipart/form-data")
    assert "没有选择文件" in toast_of(r)


def test_delete_via_console(env):
    app, client, root = env
    upload_file(client, "a.yaml", b"A")
    r = client.post("/files/delete", data={"path": "a.yaml"})
    assert "已删除" in toast_of(r)
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert "a.yaml" not in manifest["files"]


def test_download(env):
    app, client, root = env
    upload_file(client, "a.yaml", b"DATA")
    assert client.get("/files/download/a.yaml").data == b"DATA"


# ---- 配置编辑 -------------------------------------------------------------


def test_config_edit_flow(env):
    app, client, root = env
    upload_file(client, "default.custom.yaml", b"patch:\n  key: 1\n")
    r = client.get("/configs/editor?path=default.custom.yaml")
    assert b"patch:" in r.data
    r = client.post("/configs/save", data={
        "path": "default.custom.yaml", "content": "patch:\n  key: 2\n"})
    assert "已保存" in toast_of(r)
    disk = root / "store" / "files" / "default.custom.yaml"
    assert b"key: 2" in disk.read_bytes()
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert manifest["files"]["default.custom.yaml"]["source"] == "console"


def test_config_create_and_duplicate(env):
    app, client, root = env
    r = client.post("/configs/create", data={"path": "new.custom.yaml",
                                             "content": "patch:"})
    assert "已创建" in toast_of(r)
    r = client.post("/configs/create", data={"path": "new.custom.yaml", "content": ""})
    assert "已存在" in toast_of(r)


def test_config_rejects_bad_path(env):
    app, client, root = env
    r = client.post("/configs/create", data={"path": "../evil.yaml", "content": ""})
    assert "非法" in toast_of(r)


# ---- 上游基座（假 git）------------------------------------------------------


def _patch_git(monkeypatch, upstream, output="deadbee fix: initial"):
    monkeypatch.setattr(type(upstream), "cloned", property(lambda self: True))
    monkeypatch.setattr(upstream, "run_git", lambda *a, **k: output)


def test_base_update_with_fake_git(env, tmp_path, monkeypatch):
    app, client, root = env
    upstream = app.extensions["upstream"]
    base_dir = upstream.base_dir
    base_dir.mkdir(parents=True)
    (base_dir / "default.yaml").write_text("base new", encoding="utf-8")
    _patch_git(monkeypatch, upstream)

    r = client.post("/base/update", data={})
    assert r.status_code == 200
    assert "baseUpdated" in r.headers["HX-Trigger"]
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert manifest["files"]["default.yaml"]["source"] == "base"
    assert (root / "store" / "files" / "default.yaml").read_text("utf-8") == "base new"


def test_base_protects_console_files(env, monkeypatch):
    app, client, root = env
    upstream = app.extensions["upstream"]
    base_dir = upstream.base_dir
    base_dir.mkdir(parents=True)
    (base_dir / "default.yaml").write_text("base ver", encoding="utf-8")
    _patch_git(monkeypatch, upstream)

    upload_file(client, "default.yaml", b"my local patch")
    r = client.post("/base/update", data={})
    assert "保护 1" in toast_of(r)
    assert (root / "store" / "files" / "default.yaml").read_bytes() == b"my local patch"

    r = client.post("/base/update", data={"force": "on"})
    assert (root / "store" / "files" / "default.yaml").read_text("utf-8") == "base ver"


def test_base_git_error_surfaces(env, monkeypatch):
    app, client, root = env
    upstream = app.extensions["upstream"]

    def boom(*a, **k):
        raise GitError("网络不通")

    monkeypatch.setattr(type(upstream), "cloned", property(lambda self: True))
    monkeypatch.setattr(upstream, "run_git", boom)
    r = client.post("/base/update", data={})
    assert "失败" in toast_of(r)


# ---- 登录 -----------------------------------------------------------------


def _enable_console_password(root) -> None:
    settings_path = root / "config" / "server.json"
    data = json.loads(settings_path.read_text("utf-8"))
    data["console"]["password_hash"] = hashlib.sha3_256(b"hunter2").hexdigest()
    settings_path.write_text(json.dumps(data), encoding="utf-8")


def test_login_flow(tmp_path):
    root = tmp_path
    settings_path = root / "config" / "server.json"
    create_app(settings_path=settings_path, root_dir=root)  # 生成默认配置
    _enable_console_password(root)
    client = create_app(settings_path=settings_path, root_dir=root).test_client()

    r = client.get("/files")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = client.post("/login", data={"password": "wrong", "next": "/files"})
    assert "密码不对".encode() in r.data
    r = client.post("/login", data={"password": "hunter2", "next": "/files"})
    assert r.status_code == 302
    assert client.get("/files").status_code == 200
