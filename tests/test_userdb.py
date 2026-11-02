"""UserDbStore：设备分桶、push/pull 排除自身、注册表。"""
import io
import tarfile

import pytest

from app.services.userdb import UserDbStore


@pytest.fixture()
def udb(tmp_path):
    return UserDbStore(tmp_path / "sync")


def make_tar(files: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def read_tar(data: bytes) -> dict:
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            out[m.name] = tf.extractfile(m).read().decode("utf-8")
    return out


def test_push_and_list(udb):
    info = udb.push("device-a", make_tar({"luna_pinyin.userdb.txt": "A1"}))
    assert info["device"] == "device-a"
    assert info["files"] == 1
    assert (udb.root / "device-a" / "luna_pinyin.userdb.txt").read_text("utf-8") == "A1"
    devices = udb.devices()
    assert devices[0]["device"] == "device-a"
    assert devices[0]["last_push"]


def test_push_second_time_merges_files(udb):
    udb.push("d", make_tar({"a.txt": "1"}))
    udb.push("d", make_tar({"a.txt": "2", "b.txt": "3"}))
    assert (udb.root / "d" / "a.txt").read_text("utf-8") == "2"
    assert (udb.root / "d" / "b.txt").read_text("utf-8") == "3"
    assert udb.devices()[0]["files"] == 2


def test_pull_excludes_own_device(udb):
    udb.push("alpha", make_tar({"luna.userdb.txt": "A"}))
    udb.push("beta", make_tar({"luna.userdb.txt": "B"}))
    data, count = udb.pull_tar_bytes(exclude="alpha")
    files = read_tar(data)
    assert count == 1
    assert files == {"beta/luna.userdb.txt": "B"}
    data, count = udb.pull_tar_bytes()
    assert count == 2


def test_push_rejects_bad_names_and_paths(udb):
    with pytest.raises(ValueError):
        udb.push("../evil", make_tar({"x.txt": "x"}))
    with pytest.raises(ValueError):
        udb.push("ok", make_tar({"../escape.txt": "x"}))
    with pytest.raises(ValueError):
        udb.push("ok", make_tar({"/abs.txt": "x"}))


def test_delete_device(udb):
    udb.push("gone", make_tar({"x.txt": "x"}))
    assert udb.delete_device("gone")
    assert udb.devices() == []
    assert not (udb.root / "gone").exists()
    assert not udb.delete_device("gone")
