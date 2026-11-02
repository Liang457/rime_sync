"""FileStore：清单、幂等、回收站、基座重建、zip 导入、路径安全。"""
import io
import zipfile

import pytest

from app.safe_path import safe_device_name, safe_relpath
from app.services.store import AddItem, FileStore


@pytest.fixture()
def store(tmp_path):
    return FileStore(tmp_path / "store")


# ---- 路径安全 -------------------------------------------------------------


def test_safe_relpath_accepts_normal():
    assert safe_relpath("cn_dicts/zzz.dict.yaml") == "cn_dicts/zzz.dict.yaml"
    assert safe_relpath("a\\b\\c.yaml") == "a/b/c.yaml"
    assert safe_relpath("/top/x.yaml") == "top/x.yaml"


@pytest.mark.parametrize("bad", [
    "", "..", "../x", "a/../b", "C:/x", "C:\\x", "a/..", "x:",
    "con.yaml", "NUL/x", "a/b<x>.yaml", "a/seg.", "a/seg" + " " + "/x",
])
def test_safe_relpath_rejects_bad(bad):
    with pytest.raises(ValueError):
        safe_relpath(bad)


def test_safe_relpath_allows_inner_dots():
    assert safe_relpath("rime.v2/x..yaml") == "rime.v2/x..yaml"


def test_safe_device_name():
    assert safe_device_name("abc-123") == "abc-123"
    with pytest.raises(ValueError):
        safe_device_name("a/b")
    with pytest.raises(ValueError):
        safe_device_name("..")


# ---- 增删与幂等 -----------------------------------------------------------


def test_add_and_manifest(store):
    rs = store.add_many([AddItem("cn_dicts/a.dict.yaml", b"hello", source="publish",
                                 version="1.0")])
    assert rs[0]["status"] == "created"
    m = store.manifest()
    assert m["revision"] == 1
    meta = m["files"]["cn_dicts/a.dict.yaml"]
    assert meta["sha3"].startswith("sha3-256:")
    assert meta["size"] == 5
    assert meta["source"] == "publish"
    assert store.get_path("cn_dicts/a.dict.yaml").read_bytes() == b"hello"


def test_idempotent_readd(store):
    item = AddItem("cn_dicts/a.dict.yaml", b"hello", source="publish", version="1.0")
    store.add_many([item])
    rev = store.revision
    rs = store.add_many([AddItem("cn_dicts/a.dict.yaml", b"hello", source="publish",
                                 version="1.0")])
    assert rs[0]["status"] == "unchanged"
    assert store.revision == rev


def test_update_bumps_revision(store):
    store.add_many([AddItem("f.yaml", b"v1")])
    rev = store.revision
    rs = store.add_many([AddItem("f.yaml", b"v2")])
    assert rs[0]["status"] == "updated"
    assert store.revision == rev + 1


def test_delete_moves_to_trash(store):
    store.add_many([AddItem("f.yaml", b"data")])
    assert store.delete("f.yaml")
    assert "f.yaml" not in store.manifest()["files"]
    assert not list(store.files_dir.rglob("f.yaml"))
    assert any(store.trash_dir.rglob("f.yaml"))
    assert not store.delete("f.yaml")


# ---- 基座重建 -------------------------------------------------------------


def _mk_base(tmp_path, files: dict) -> dict:
    base = {}
    for rel, content in files.items():
        p = tmp_path / "basetmp" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        base[rel] = p
    return base


def test_rebuild_base_adds_and_protects(store, tmp_path):
    store.add_many([
        AddItem("default.yaml", b"base-v1", source="base"),
        AddItem("cn_dicts/mine.dict.yaml", b"mine", source="publish"),
    ])
    incoming = _mk_base(tmp_path, {
        "default.yaml": "base-v2",
        "new.yaml": "brand-new",
        "cn_dicts/mine.dict.yaml": "base-wants-this",
    })
    report = store.rebuild_base(incoming, version="abc1234")
    assert report["added"] == 1          # new.yaml
    assert report["updated"] == 1        # default.yaml
    assert report["skipped"][0]["path"] == "cn_dicts/mine.dict.yaml"
    assert store.get_path("cn_dicts/mine.dict.yaml").read_bytes() == b"mine"
    assert store.manifest()["files"]["default.yaml"]["version"] == "abc1234"


def test_rebuild_base_removes_gone_files(store, tmp_path):
    store.add_many([AddItem("old.yaml", b"old", source="base")])
    incoming = _mk_base(tmp_path, {"fresh.yaml": "f"})
    report = store.rebuild_base(incoming, version="x")
    assert report["removed"] == 1
    assert "old.yaml" not in store.manifest()["files"]


def test_rebuild_base_force_takes_over(store, tmp_path):
    store.add_many([AddItem("f.yaml", b"console-ver", source="console")])
    incoming = _mk_base(tmp_path, {"f.yaml": "base-ver"})
    store.rebuild_base(incoming, version="c1", force=True)
    assert store.get_path("f.yaml").read_bytes() == b"base-ver"
    assert store.manifest()["files"]["f.yaml"]["source"] == "base"


# ---- zip 导入 -------------------------------------------------------------


def _zip_bytes(files: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
    buf.seek(0)
    return buf


def test_import_zip_strip_top(store):
    zf = _zip_bytes({"rime-ice-master/default.yaml": "d", "rime-ice-master/cn_dicts/8105.dict.yaml": "c"})
    report = store.import_zip(zf, strip_top=True, source="base")
    assert report["added"] == 2
    assert "default.yaml" in store.manifest()["files"]
    assert "cn_dicts/8105.dict.yaml" in store.manifest()["files"]


def test_import_zip_protects_and_force(store):
    store.add_many([AddItem("f.yaml", b"mine", source="console")])
    store.import_zip(_zip_bytes({"f.yaml": "zip-ver"}), source="base")
    assert store.get_path("f.yaml").read_bytes() == b"mine"
    store.import_zip(_zip_bytes({"f.yaml": "zip-ver"}), source="base", force=True)
    assert store.get_path("f.yaml").read_bytes() == b"zip-ver"


# ---- 打包与统计 -----------------------------------------------------------


def test_tar_bytes_roundtrip(store):
    store.add_many([AddItem("a.yaml", b"A" * 10), AddItem("b/b.yaml", b"B" * 10)])
    import tarfile

    data, missing = store.tar_bytes(["a.yaml", "b/b.yaml"])
    assert missing == []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        names = sorted(tf.getnames())
    assert names == ["a.yaml", "b/b.yaml"]
    _, missing = store.tar_bytes(["nope.yaml"])
    assert missing == ["nope.yaml"]


def test_stats_by_prefix(store):
    store.add_many([AddItem("cn_dicts/a.dict.yaml", b"x" * 5),
                    AddItem("cn_dicts/b.dict.yaml", b"x"),
                    AddItem("default.yaml", b"x")])
    stats = store.stats()
    assert stats["file_count"] == 3
    assert stats["by_prefix"]["cn_dicts"]["count"] == 2
    assert "（根目录）" in stats["by_prefix"]
    assert "publish" in stats["sources"]


def test_activity_capped(store):
    for i in range(120):
        store.activity("files", f"op-{i}")
    assert len(store.recent_activity(200)) <= 100
    assert store.recent_activity(1)[0]["detail"] == "op-119"
