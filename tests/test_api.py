"""API 端点：认证、manifest、下载、publish 幂等、userdb 推拉、health/status。"""
import io
import tarfile


def make_tar_gz(files: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def read_tar_gz(data: bytes) -> dict:
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            out[m.name] = tf.extractfile(m).read()
    return out


def publish(client, rel, content=b"body", **form):
    return client.post("/api/publish", data={
        "file": (io.BytesIO(content), rel.rsplit("/", 1)[-1]),
        **form, "path": rel,
    }, content_type="multipart/form-data")


# ---- 认证 ---------------------------------------------------------------


def test_health_open_without_token(env):
    app, client, root = env
    assert client.get("/api/health").status_code == 200


def test_token_required_when_set(tokened_env):
    app, client, root = tokened_env
    assert client.get("/api/manifest").status_code == 401
    assert client.get("/api/manifest",
                      headers={"X-Api-Token": "wrong"}).status_code == 401
    assert client.get("/api/manifest",
                      headers={"X-Api-Token": "sekrit"}).status_code == 200
    assert client.get("/api/health").status_code == 200  # health 永远开放


# ---- manifest 与下载 ------------------------------------------------------


def test_manifest_and_get_file(env):
    app, client, root = env
    publish(client, "cn_dicts/a.dict.yaml", b"AAAA", version="3.3", source="rime_dict")
    m = client.get("/api/manifest").get_json()
    assert m["revision"] == 1
    assert m["files"]["cn_dicts/a.dict.yaml"]["sha3"].startswith("sha3-256:")

    r = client.get("/api/files/get/cn_dicts/a.dict.yaml")
    assert r.status_code == 200
    assert r.data == b"AAAA"
    assert client.get("/api/files/get/cn_dicts/none.yaml").status_code == 404
    assert client.get("/api/files/get/../secret").status_code in (400, 404)


def test_publish_idempotent(env):
    app, client, root = env
    r1 = publish(client, "cn_dicts/z.dict.yaml", b"same", version="v1")
    assert r1.get_json()["results"][0]["status"] == "created"
    r2 = publish(client, "cn_dicts/z.dict.yaml", b"same", version="v1")
    j = r2.get_json()
    assert j["results"][0]["status"] == "unchanged"
    assert j["revision"] == 1  # 幂等：无变更不加版本


def test_publish_multiple_files(env):
    app, client, root = env
    data = {
        "files": [
            (io.BytesIO(b"A"), "a.dict.yaml"),
            (io.BytesIO(b"B"), "b.dict.yaml"),
        ],
        "source": "rime_dict",
        "version": "2026-11-02",
    }
    r = client.post("/api/publish", data=data, content_type="multipart/form-data")
    j = r.get_json()
    assert j["ok"] is True
    assert {x["path"] for x in j["results"]} == {"a.dict.yaml", "b.dict.yaml"}


def test_publish_rejects_path_with_multiple(env):
    app, client, root = env
    data = {"files": [(io.BytesIO(b"A"), "a.yaml"), (io.BytesIO(b"B"), "b.yaml")],
            "path": "one.yaml"}
    r = client.post("/api/publish", data=data, content_type="multipart/form-data")
    assert r.status_code == 400


def test_files_get_batch_and_all(env):
    app, client, root = env
    publish(client, "a.yaml", b"A")
    publish(client, "dir/b.yaml", b"B")

    r = client.get("/api/files/get?paths=a.yaml,dir/b.yaml")
    assert r.status_code == 200
    assert read_tar_gz(r.data) == {"a.yaml": b"A", "dir/b.yaml": b"B"}

    r = client.get("/api/files/get?paths=a.yaml,ghost.yaml")
    assert r.status_code == 404
    assert r.get_json()["missing"] == ["ghost.yaml"]

    r = client.get("/api/files/get?all=1")
    assert set(read_tar_gz(r.data)) == {"a.yaml", "dir/b.yaml"}
    assert client.get("/api/files/get").status_code == 400


# ---- 用户词库 -------------------------------------------------------------


def test_userdb_roundtrip(env):
    app, client, root = env
    r = client.post("/api/userdb/push?device=phone-1",
                    data={"tar": (make_tar_gz({"luna.userdb.txt": "P1"}), "snap.tar.gz")},
                    content_type="multipart/form-data")
    assert r.get_json()["files"] == 1

    r = client.post("/api/userdb/push",
                    data={"device": "pc-1",
                          "tar": (make_tar_gz({"luna.userdb.txt": "PC1"}), "s.tar.gz")},
                    content_type="multipart/form-data")
    assert r.get_json()["ok"] is True

    r = client.get("/api/userdb/pull?device=phone-1")
    assert r.headers["X-Sync-File-Count"] == "1"
    files = read_tar_gz(r.data)
    assert files == {"pc-1/luna.userdb.txt": b"PC1"}

    r = client.get("/api/userdb/pull")
    assert r.headers["X-Sync-File-Count"] == "2"

    r = client.post("/api/userdb/push", data={"tar": (make_tar_gz({"x": "x"}), "t")},
                    content_type="multipart/form-data")
    assert r.status_code == 400  # 缺 device


# ---- status ---------------------------------------------------------------


def test_status_counts(env):
    app, client, root = env
    publish(client, "cn_dicts/a.dict.yaml", b"A")
    client.post("/api/userdb/push?device=d1",
                data={"tar": (make_tar_gz({"f.txt": "f"}), "t")},
                content_type="multipart/form-data")
    s = client.get("/api/status").get_json()
    assert s["file_count"] == 1
    assert s["devices"] == 1
    assert s["revision"] == 1
    assert s["base"]["cloned"] is False
