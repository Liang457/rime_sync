"""版本展示：文件内解析优先，manifest 备注作括号补充（services/versions）。"""
import io

from app.services.versions import display, inner_version

DICT = """# Rime dictionary
# encoding: utf-8
# 语料版本: 20261105
---
name: zzz
version: "3.3 (2026-11-05)"
sort: original
...
邦布\t4113
"""

SCHEMA = """# Rime schema
# encoding: utf-8
schema:
  schema_id: rime_ice
  name: 雾凇拼音
  version: "2026-03-08"
  author:
    - Dvel
"""


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---- 解析 ---------------------------------------------------------------


def test_dict_version_after_separator(tmp_path):
    assert inner_version(_write(tmp_path, "zzz.dict.yaml", DICT)) == "3.3 (2026-11-05)"


def test_comment_version_is_not_a_version(tmp_path):
    """注释头里的「版本:」不是文件版本（只有行首是键才算）。"""
    text = '# Rime theme\n# 版本: 9.9\n# 语料版本: 20261105\n'
    assert inner_version(_write(tmp_path, "wechat.trime.yaml", text)) == ""


def test_config_version_counts(tmp_path):
    """default/weasel/squirrel 没有 version，config_version 就是它的版本。"""
    text = "# Rime default settings\nconfig_version: '2026-02-06'\n"
    assert inner_version(_write(tmp_path, "default.yaml", text)) == "2026-02-06"


def test_content_version_beats_config_version(tmp_path):
    text = '---\nname: a\nversion: "1.2"\nconfig_version: "3.0"\n'
    assert inner_version(_write(tmp_path, "a.yaml", text)) == "1.2"


def test_schema_block_version(tmp_path):
    assert inner_version(_write(tmp_path, "rime_ice.schema.yaml", SCHEMA)) == "2026-03-08"


def test_unquoted_version(tmp_path):
    assert inner_version(_write(tmp_path, "a.yaml", "---\nname: a\nversion: 3.3\n")) == "3.3"


def test_missing_and_unsupported(tmp_path):
    assert inner_version(tmp_path / "nope.yaml") == ""
    assert inner_version(None) == ""
    assert inner_version(_write(tmp_path, "a.txt", "version: 1\n")) == ""


# ---- 组合规则 -----------------------------------------------------------


def test_display_parsed_only():
    assert display("1.2", "") == {"version": "1.2", "version_note": ""}


def test_display_parsed_plus_note():
    assert display("1.2", "tag-9") == {"version": "1.2", "version_note": "tag-9"}


def test_display_note_only():
    assert display("", "v2.6-restore-20261109_160633") == {
        "version": "v2.6-restore-20261109_160633", "version_note": ""}


def test_display_identical_note_collapses():
    assert display("1.2", "1.2") == {"version": "1.2", "version_note": ""}


def test_display_neither():
    assert display("", "") == {"version": "", "version_note": ""}


# ---- 页面 ---------------------------------------------------------------


def _table(client):
    return client.get("/files/table").get_data(as_text=True)


def test_files_table_shows_parsed_version(env):
    app, client, root = env
    r = client.post("/files/upload", data={
        "files": (io.BytesIO(DICT.encode("utf-8")), "zzz.dict.yaml"),
        "prefix": "cn_dicts",
    }, content_type="multipart/form-data")
    assert r.get_json()["ok"] is True
    assert "3.3 (2026-11-05)" in _table(client)


def test_files_table_puts_note_in_parentheses(env):
    app, client, root = env
    r = client.post("/api/publish", data={
        "file": (io.BytesIO(DICT.encode("utf-8")), "zzz.dict.yaml"),
        "path": "cn_dicts/zzz.dict.yaml",
        "version": "tag-9",
    }, content_type="multipart/form-data")
    assert r.get_json()["ok"] is True
    assert "3.3 (2026-11-05)<span class=\"muted\">（tag-9）</span>" in _table(client)


def test_files_table_dashes_when_no_version(env):
    app, client, root = env
    r = client.post("/files/upload", data={
        "files": (io.BytesIO(b"ENTRY\t100"), "plain.yaml"),
    }, content_type="multipart/form-data")
    assert r.get_json()["ok"] is True
    assert ">--</td>" in _table(client)
