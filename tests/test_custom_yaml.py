"""*.custom.yaml patch 解析/合并/序列化 + 选项注册表的基座数据读取。"""
import pytest

from app.services.config_options import available_schemas, base_yaml_data, walk_path
from app.services.custom_yaml import apply_patch, dump_patch, parse_patch
from app.services.store import AddItem, FileStore


def test_parse_nested_flattens_to_slash():
    text = ("patch:\n"
            "  menu:\n"
            "    page_size: 6\n"
            "  ascii_composer/switch_key/Shift_L: commit_code\n")
    assert parse_patch(text) == {
        "menu/page_size": 6,
        "ascii_composer/switch_key/Shift_L": "commit_code",
    }


def test_parse_empty_and_none():
    assert parse_patch("") == {}
    assert parse_patch("# 只有注释\n") == {}
    assert parse_patch("patch:\n") == {}


def test_parse_rejects_conflict_and_non_mapping():
    with pytest.raises(ValueError):
        parse_patch("patch:\n  menu: {page_size: 6}\n  menu/page_size: 7\n")
    with pytest.raises(ValueError):
        parse_patch("patch: [1, 2]\n")


def test_dump_parse_roundtrip():
    patch = {
        "menu/page_size": 6,
        "schema_list": [{"schema": "rime_ice"}, {"schema": "t9"}],
        "switcher/fold_options": True,
    }
    text = dump_patch(patch)
    assert parse_patch(text) == patch
    assert "schema: rime_ice" in text
    assert text.startswith("# RIME 定制补丁")  # 说明头


def test_apply_preserves_unknown_keys():
    current = "patch:\n  menu/page_size: 6\n  custom/thing: keepme\n"
    new = apply_patch(current, {"menu/page_size": 8}, [])
    assert parse_patch(new) == {"menu/page_size": 8, "custom/thing": "keepme"}


def test_apply_removes_and_placeholder():
    current = dump_patch({"menu/page_size": 6, "custom/thing": "abc"})
    new = apply_patch(current, {}, ["custom/thing"])
    assert parse_patch(new) == {"menu/page_size": 6}
    new = apply_patch(new, {"menu/page_size": None}, [])  # None 也表示删除
    assert "patch: {}" in new


def test_apply_to_empty_current():
    assert parse_patch(apply_patch("", {"menu/page_size": 5}, [])) == {
        "menu/page_size": 5,
    }


def test_available_schemas(tmp_path):
    st = FileStore(tmp_path)
    st.add_many([
        AddItem("rime_ice.schema.yaml",
                b"schema:\n  schema_id: rime_ice\n  name: \xe9\x9b\xbe\xe5\x87\x87\xe6\x8b\xbc\xe9\x9f\xb3\n",
                source="base"),
        AddItem("mine.schema.yaml", b"schema:\n  name: \xe8\x87\xaa\xe5\xae\x9a\xe4\xb9\x89\n",
                source="upload"),
    ])
    got = {s["id"]: s for s in available_schemas(st)}
    assert got["rime_ice"]["name"] == "雾凇拼音"
    assert got["rime_ice"]["source"] == "base"
    assert got["mine"]["name"] == "自定义"
    assert got["mine"]["source"] == "upload"


def test_base_yaml_data_and_walk(tmp_path):
    st = FileStore(tmp_path)
    st.add_many([AddItem("default.yaml", b"menu:\n  page_size: 5\n", source="base"),
                 AddItem("other.yaml", b"x: 1\n", source="console")])
    data = base_yaml_data(st, "default.yaml")
    assert walk_path(data, "menu/page_size") == 5
    assert walk_path(data, "menu/missing") is None
    assert walk_path({}, "menu") is None
    assert base_yaml_data(st, "other.yaml") == {}       # 非 base 来源不算基座
    assert base_yaml_data(st, "nope.yaml") == {}
