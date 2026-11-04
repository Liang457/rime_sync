"""manage.py 迁移命令：import-runtime / import-sync（部署机上一次性执行，防呆重点）。"""
import json

import manage
from app.services.store import FileStore


def test_import_runtime_skips_junk(tmp_path):
    """旧 runtime 迁入：source=migrate；.git/ 与 client_config.json 不迁。"""
    runtime = tmp_path / "old-runtime"
    (runtime / ".git").mkdir(parents=True)
    (runtime / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (runtime / "default.yaml").write_text("schema: x", encoding="utf-8")
    (runtime / "client_config.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "srv"
    root.mkdir()

    manage.cmd_import_runtime(str(runtime), root=root)

    store = FileStore(root / "store")
    files = store.manifest()["files"]
    assert files["default.yaml"]["source"] == "migrate"
    assert store.get_path("default.yaml").read_text("utf-8") == "schema: x"
    assert ".git/HEAD" not in files
    assert "client_config.json" not in files


def test_import_runtime_missing_dir_exits(tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        manage.cmd_import_runtime(str(tmp_path / "nope"), root=tmp_path / "srv")


def test_import_sync_merges_registry(tmp_path):
    """旧 sync 迁入：_manifest.json 不迁、注册表并入 last_seen、
    快照目录已消失的设备只登记元数据；重跑幂等。"""
    old = tmp_path / "old-sync"
    (old / "pc-1").mkdir(parents=True)
    (old / "pc-1" / "luna.userdb.txt").write_text("P1", encoding="utf-8")
    (old / "phone-1" / "deep").mkdir(parents=True)
    (old / "phone-1" / "deep" / "a.txt").write_text("A", encoding="utf-8")
    (old / "_manifest.json").write_text("{}", encoding="utf-8")  # 服务器旧元数据
    root = tmp_path / "srv"
    (root / "config").mkdir(parents=True)
    (root / "config" / "devices.json").write_text(json.dumps({
        "devices": {
            "pc-1": {"last_seen": "2025-01-01T08:00:00+08:00"},
            "ghost": {"last_seen": "2024-12-31T00:00:00+08:00"},  # 目录已消失
        },
    }), encoding="utf-8")

    manage.cmd_import_sync(str(old), root=root)

    registry = json.loads(
        (root / "sync" / "_devices.json").read_text(encoding="utf-8"))
    assert registry["pc-1"]["files"] == 1
    assert registry["pc-1"]["last_push"] == "2025-01-01T08:00:00+08:00"
    assert registry["phone-1"]["files"] == 1          # 嵌套目录按文件数统计
    assert registry["ghost"]["files"] == 0            # 只登记元数据
    assert not (root / "sync" / "_manifest.json").exists()
    assert (root / "sync" / "pc-1" / "luna.userdb.txt").read_text("utf-8") == "P1"

    # 重跑：合并到已有目录，文件计数不变
    manage.cmd_import_sync(str(old), root=root)
    registry2 = json.loads(
        (root / "sync" / "_devices.json").read_text(encoding="utf-8"))
    assert registry2["pc-1"]["files"] == 1
    assert (root / "sync" / "pc-1" / "luna.userdb.txt").read_text("utf-8") == "P1"
