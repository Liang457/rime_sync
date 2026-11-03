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
    """走新 JSON 上传流程；prefix 传 'cn_dicts' 等目录名。"""
    data = {
        "files": (io.BytesIO(content), rel.rsplit("/", 1)[-1]),
        "prefix": prefix,
        **form,
    }
    return client.post("/files/upload", data=data, content_type="multipart/form-data")


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
    r = upload_file(client, "zzz.dict.yaml", b"ENTRY\t100", prefix="cn_dicts")
    j = r.get_json()
    assert j["ok"] is True
    assert j["saved"][0]["path"] == "cn_dicts/zzz.dict.yaml"
    assert j["conflicts"] == []
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert manifest["files"]["cn_dicts/zzz.dict.yaml"]["source"] == "upload"


def test_upload_without_files_shows_error(env):
    app, client, root = env
    r = client.post("/files/upload", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "没有选择文件" in toast_of(r)


def test_upload_same_name_asks_then_replace(env):
    app, client, root = env
    upload_file(client, "a.yaml", b"v1")
    # 第二次上传同名 → 不落盘，报告冲突
    r = upload_file(client, "a.yaml", b"v2")
    j = r.get_json()
    assert j["conflicts"] == ["a.yaml"] and j["saved"] == []
    assert (root / "store" / "files" / "a.yaml").read_bytes() == b"v1"
    # 确认批量替换 → 落盘
    r = upload_file(client, "a.yaml", b"v2", replace="1")
    j = r.get_json()
    assert j["conflicts"] == [] and j["saved"][0]["status"] == "updated"
    assert (root / "store" / "files" / "a.yaml").read_bytes() == b"v2"


def test_upload_cn_dict_updates_rime_ice(env):
    app, client, root = env
    store = app.extensions["store"]
    from app.services.store import AddItem

    store.add_many([AddItem("rime_ice.dict.yaml", b"import_tables:\n  - 8105\n",
                            source="base")])
    upload_file(client, "zzz.dict.yaml", b"E\t1", prefix="cn_dicts")
    content = store.get_path("rime_ice.dict.yaml").read_text("utf-8")
    assert "- zzz" in content and "- 8105" in content
    # 删除词库 → 联动移除
    r = client.post("/files/delete", data={"path": "cn_dicts/zzz.dict.yaml"})
    assert "已同步 rime_ice.dict.yaml" in toast_of(r)
    content = store.get_path("rime_ice.dict.yaml").read_text("utf-8")
    assert "- zzz" not in content and "- 8105" in content


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


# ---- API token 管理 -------------------------------------------------------


def test_token_create_and_revoke(env):
    app, client, root = env
    r = client.post("/devices/tokens/create", data={"label": "手机"})
    assert "已生成" in toast_of(r)
    settings = app.extensions["settings"]
    assert len(settings.tokens) == 1
    tok = settings.tokens[0]
    assert tok["label"] == "手机" and tok["token"].startswith("rs_")
    # 设备页能看到 token
    assert tok["token"].encode() in client.get("/devices").data
    # 吊销
    r = client.post("/devices/tokens/delete", data={"token": tok["token"]})
    assert "已吊销" in toast_of(r)
    assert settings.tokens == []


def test_token_file_persisted(env):
    app, client, root = env
    client.post("/devices/tokens/create", data={"label": "pad"})
    cfg = json.loads((root / "config" / "server.json").read_text("utf-8"))
    assert cfg["server"]["tokens"][0]["label"] == "pad"


# ---- 登录 -----------------------------------------------------------------


def _enable_console_password(root) -> None:
    settings_path = root / "config" / "server.json"
    data = json.loads(settings_path.read_text("utf-8"))
    data["console"]["password_hash"] = hashlib.sha3_256(b"hunter2").hexdigest()
    settings_path.write_text(json.dumps(data), encoding="utf-8")


def test_login_flow(tmp_path):
    root = tmp_path
    settings_path = root / "config" / "server.json"
    create_app(settings_path=settings_path, root_dir=root,
               run_scheduler=False)  # 生成默认配置
    _enable_console_password(root)
    client = create_app(settings_path=settings_path, root_dir=root,
                        run_scheduler=False).test_client()

    r = client.get("/files")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = client.post("/login", data={"password": "wrong", "next": "/files"})
    assert "密码不对".encode() in r.data
    r = client.post("/login", data={"password": "hunter2", "next": "/files"})
    assert r.status_code == 302
    assert client.get("/files").status_code == 200


# ---- 页面拆分：词库文件页=自定义，基座页=基座全览（P1）-----------------------


def test_files_page_hides_base_but_base_page_shows(env):
    app, client, root = env
    store = app.extensions["store"]
    from app.services.store import AddItem

    store.add_many([AddItem("cn_dicts/base.dict.yaml", b"base", source="base"),
                    AddItem("README.md", b"junk", source="base")])
    upload_file(client, "mine.dict.yaml", b"mine", prefix="cn_dicts")

    r = client.get("/files")
    assert b"cn_dicts/mine.dict.yaml" in r.data
    assert b"cn_dicts/base.dict.yaml" not in r.data
    assert b"README.md" not in r.data
    assert b'value="base"' not in r.data            # 来源下拉不再提供 base

    r = client.get("/base")
    assert b"cn_dicts/base.dict.yaml" in r.data
    assert b"README.md" in r.data


def test_base_update_filters_whitelist_and_cleans_legacy(env, monkeypatch):
    """基座重建：白名单外不入库；上一轮混进来的垃圾 base 文件被清退。"""
    app, client, root = env
    store = app.extensions["store"]
    from app.services.store import AddItem

    # 模拟上一版无白名单时误入库的垃圾
    store.add_many([AddItem("AGENTS.md", b"old junk", source="base")])
    upstream = app.extensions["upstream"]
    base_dir = upstream.base_dir
    base_dir.mkdir(parents=True)
    (base_dir / "default.yaml").write_text("base new", encoding="utf-8")
    (base_dir / "cn_dicts").mkdir()
    (base_dir / "cn_dicts" / "8105.dict.yaml").write_text("dict", encoding="utf-8")
    (base_dir / "README.md").write_text("junk", encoding="utf-8")
    gh = base_dir / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "release.yml").write_text("wf", encoding="utf-8")
    _patch_git(monkeypatch, upstream)

    r = client.post("/base/update", data={})
    assert r.status_code == 200
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert "default.yaml" in manifest["files"]
    assert "cn_dicts/8105.dict.yaml" in manifest["files"]
    assert "README.md" not in manifest["files"]
    assert ".github/workflows/release.yml" not in manifest["files"]
    assert "AGENTS.md" not in manifest["files"]     # 旧垃圾被清退


# ---- 基座更新地址与自动更新（P2）---------------------------------------------


def test_base_repo_saved(env):
    app, client, root = env
    r = client.post("/base/repo",
                    data={"repo_url": "https://mirror.example.com/rime-ice"})
    assert "已保存" in toast_of(r)
    cfg = json.loads((root / "config" / "server.json").read_text("utf-8"))
    assert cfg["base"]["repo_url"] == "https://mirror.example.com/rime-ice"
    assert app.extensions["upstream"].repo_url.endswith("rime-ice")


def test_base_repo_rejects_non_http(env):
    app, client, root = env
    for bad in ("ftp://x/y", "", "github.com/foo/bar"):
        r = client.post("/base/repo", data={"repo_url": bad})
        assert "http" in toast_of(r)
    cfg = json.loads((root / "config" / "server.json").read_text("utf-8"))
    assert cfg["base"]["repo_url"] == "https://github.com/iDvel/rime-ice"  # 未被改


def test_base_schedule_validates_cron(env):
    app, client, root = env
    settings = app.extensions["settings"]
    r = client.post("/base/schedule", data={"enabled": "on", "cron": "bad cron!"})
    assert "无效" in toast_of(r)
    assert settings.base_auto_update is False
    r = client.post("/base/schedule", data={"enabled": "on", "cron": "0 4 * * *"})
    assert "已开启" in toast_of(r)
    assert settings.base_auto_update is True and settings.base_cron == "0 4 * * *"
    r = client.post("/base/schedule", data={})
    assert "已关闭" in toast_of(r)
    assert settings.base_auto_update is False


def test_base_reclone_route(env, monkeypatch):
    app, client, root = env
    store = app.extensions["store"]
    from app.services.store import AddItem

    store.add_many([AddItem("default.yaml", b"v", source="base"),
                    AddItem("default.custom.yaml", b"patch: {}\n", source="console")])
    upstream = app.extensions["upstream"]
    upstream.base_dir.mkdir(parents=True)
    (upstream.base_dir / "default.yaml").write_text("v", encoding="utf-8")
    _patch_git(monkeypatch, upstream)

    r = client.post("/base/reclone", data={})
    assert "重新克隆完成" in toast_of(r)
    assert "baseUpdated" in r.headers["HX-Trigger"]
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    # 假 git 克隆产物为空 → base 清退；console 来源的补丁文件不受影响
    assert "default.yaml" not in manifest["files"]
    assert "default.custom.yaml" in manifest["files"]


# ---- 配置表单（P3）----------------------------------------------------------


def _mk_default_pair(app):
    """基座 default.yaml + 一份已有手写键的 default.custom.yaml。"""
    from app.services.store import AddItem

    app.extensions["store"].add_many([
        AddItem("default.yaml",
                b"menu:\n  page_size: 5\nascii_composer:\n  good_old_caps_lock: true\n",
                source="base"),
        AddItem("default.custom.yaml",
                b"patch:\n  menu/page_size: 6\n  custom/thing: keepme\n",
                source="console"),
    ])


def test_patch_form_save_flow(env):
    app, client, root = env
    from app.services.custom_yaml import parse_patch

    _mk_default_pair(app)
    r = client.post("/configs/patch/save", data={
        "path": "default.custom.yaml",
        "opt::menu/page_size": "9",
        "opt::ascii_composer/good_old_caps_lock": "false",
        "opt::ascii_composer/switch_key/Shift_L": "commit_text",
        "opt::ascii_composer/switch_key/Shift_R": "",       # 删除（不在补丁里，无碍）
        "hotkey::F4": "on",
        "hotkey::Control+grave": "on",
        "opt::key_binder/select_first_character": "bracketleft",
    })
    assert "已保存" in toast_of(r)
    text = (root / "store" / "files" / "default.custom.yaml").read_text("utf-8")
    p = parse_patch(text)
    assert p["menu/page_size"] == 9
    assert p["ascii_composer/good_old_caps_lock"] is False
    assert p["ascii_composer/switch_key/Shift_L"] == "commit_text"
    assert p["switcher/hotkeys"] == ["F4", "Control+grave"]
    assert p["key_binder/select_first_character"] == "bracketleft"
    assert p["custom/thing"] == "keepme"                    # 手写键保留
    manifest = json.loads((root / "store" / "manifest.json").read_text("utf-8"))
    assert manifest["files"]["default.custom.yaml"]["source"] == "console"


def test_patch_form_schema_list_order(env):
    app, client, root = env
    from app.services.custom_yaml import parse_patch
    from app.services.store import AddItem

    app.extensions["store"].add_many([
        AddItem("rime_ice.schema.yaml", b"schema:\n  name: x\n", source="base"),
        AddItem("t9.schema.yaml", b"schema:\n  name: y\n", source="base"),
    ])
    upload_file(client, "default.custom.yaml", b"patch: {}\n")
    r = client.post("/configs/patch/save", data={
        "path": "default.custom.yaml",
        "opt::schema_list_order": "t9, rime_ice",
    })
    assert "已保存" in toast_of(r)
    p = parse_patch(
        (root / "store" / "files" / "default.custom.yaml").read_text("utf-8"))
    assert p["schema_list"] == [{"schema": "t9"}, {"schema": "rime_ice"}]
    # 未知方案被拒
    r = client.post("/configs/patch/save", data={
        "path": "default.custom.yaml", "opt::schema_list_order": "ghost"})
    assert "未知方案" in toast_of(r)


def test_patch_form_validation_errors(env):
    app, client, root = env
    _mk_default_pair(app)

    r = client.post("/configs/patch/save", data={
        "path": "default.custom.yaml", "opt::menu/page_size": "99"})
    assert "须在" in toast_of(r)
    r = client.post("/configs/patch/save", data={
        "path": "default.custom.yaml", "opt::menu/page_size": "abc"})
    assert "整数" in toast_of(r)
    r = client.post("/configs/patch/save", data={
        "path": "default.custom.yaml",
        "opt::ascii_composer/switch_key/Shift_L": "hacked"})
    assert "选项无效" in toast_of(r)
    r = client.post("/configs/patch/save", data={
        "path": "nope.custom.yaml", "opt::menu/page_size": "6"})
    assert "清单中没有" in toast_of(r)
    # 未注册表单的补丁文件 → 指引源码模式
    upload_file(client, "rime_ice.custom.yaml", b"patch: {}\n")
    r = client.post("/configs/patch/save", data={
        "path": "rime_ice.custom.yaml", "opt::menu/page_size": "6"})
    assert "源码模式" in toast_of(r)


def test_configs_page_groups_and_editor_views(env):
    app, client, root = env
    _mk_default_pair(app)

    r = client.get("/configs?path=default.custom.yaml")
    assert "定制补丁".encode() in r.data
    assert b'data-tab="form"' in r.data            # 有「常用设置」Tab
    assert b"schema-order-input" in r.data
    assert "跟随基座默认".encode() in r.data
    assert "上游默认：5".encode() in r.data        # 基座默认值展示

    r = client.get("/configs?path=default.yaml")
    assert "基座文件：直接修改".encode() in r.data  # base 来源警示条
    assert b'data-tab="form"' not in r.data         # 非补丁文件只有源码模式

    # 补丁文件解析冲突 → 报错提示进源码修正
    upload_file(client, "default.custom.yaml",
                b"patch:\n  menu: {page_size: 6}\n  menu/page_size: 7\n",
                replace="1")
    r = client.get("/configs?path=default.custom.yaml")
    assert "解析失败".encode() in r.data
