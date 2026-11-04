"""rime_server 管理命令：

  python manage.py set-password            # 设置控制台登录密码
  python manage.py clear-password          # 清除密码（回到免登录）
  python manage.py import-runtime <dir>    # 迁移旧 rime_sync/runtime/ 进文件库
  python manage.py import-sync <dir>       # 迁移旧 rime_sync/sync/<设备>/ 进设备中转
"""
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.services.store import AddItem, FileStore  # noqa: E402


def cmd_set_password() -> None:
    s = Settings(ROOT / "config" / "server.json")
    p1 = getpass.getpass("新密码: ")
    if len(p1) < 6:
        sys.exit("密码至少 6 位")
    p2 = getpass.getpass("再输一遍: ")
    if p1 != p2:
        sys.exit("两次输入不一致")
    s.set_password(p1)
    print("已设置控制台密码，重启服务生效。")


def cmd_clear_password() -> None:
    s = Settings(ROOT / "config" / "server.json")
    s.clear_password()
    print("已清除密码（免登录模式），重启服务生效。")


def cmd_import_runtime(old_dir: str, root: Path = ROOT) -> None:
    """旧 runtime/ 整体迁入文件库，source=migrate（基座重建时受保护）。"""
    src = Path(old_dir).resolve()
    if not src.is_dir():
        sys.exit(f"目录不存在: {src}")
    app = create_app(root_dir=root, run_scheduler=False)
    store = FileStore(root / "store")
    items = []
    for p in src.rglob("*"):
        if p.is_file():
            rel = p.relative_to(src).as_posix()
            if rel.startswith(".git/") or "client_config.json" in rel:
                continue
            items.append(AddItem(rel, p, source="migrate"))
    print(f"迁移 {len(items)} 个文件 ...")
    results = store.add_many(items, detail=f"迁移旧 runtime {len(items)} 个文件")
    changed = sum(r["status"] != "unchanged" for r in results)
    print(f"完成：变更 {changed}，manifest revision = {store.revision}")


def cmd_import_sync(old_dir: str, root: Path = ROOT) -> None:
    """旧 sync/<device>/（含 _manifest.json 元数据）迁入新设备中转区，
    并把 v1 config/devices.json 里的设备元数据（last_seen）并入注册表。"""
    import json
    import shutil

    src = Path(old_dir).resolve()
    if not src.is_dir():
        sys.exit(f"目录不存在: {src}")
    new_sync = root / "sync"
    new_sync.mkdir(parents=True, exist_ok=True)
    reg_path = new_sync / "_devices.json"
    registry: dict = {}
    if reg_path.exists():
        registry = json.loads(reg_path.read_text(encoding="utf-8"))

    # v1 设备元数据：{"devices": {名字: {last_seen, ...}}}
    old_meta: dict = {}
    dev_file = root / "config" / "devices.json"
    if dev_file.exists():
        try:
            data = json.loads(dev_file.read_text(encoding="utf-8"))
            old_meta = data.get("devices", {})
        except (json.JSONDecodeError, OSError):
            old_meta = {}

    moved = 0
    for d in sorted(src.iterdir()):
        if not d.is_dir():
            continue  # 旧 _manifest.json 是服务器自己的元数据，不迁
        dest = new_sync / d.name
        if dest.exists():
            print(f"合并到已有目录: {d.name}")
        else:
            shutil.copytree(d, dest,
                            ignore=shutil.ignore_patterns("_manifest.json"))
        files = size = 0
        for p in dest.rglob("*"):
            if p.is_file():
                files += 1
                size += p.stat().st_size
        info = registry.get(d.name, {})
        info.setdefault("last_push", old_meta.get(d.name, {}).get("last_seen", ""))
        info.update({"files": files, "size": size})
        registry[d.name] = info
        moved += 1
        print(f"迁入: {d.name}（{files} 个文件）")

    # 只在旧 devices.json 里有、但快照目录已不存在的设备，也登记进注册表
    for name, meta in old_meta.items():
        if name not in registry:
            registry[name] = {"last_push": meta.get("last_seen", ""),
                              "files": 0, "size": 0}

    reg_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成：迁入 {moved} 台设备，注册表共 {len(registry)} 台。")


def main() -> None:
    cmds = {
        "set-password": lambda: cmd_set_password(),
        "clear-password": lambda: cmd_clear_password(),
        "import-runtime": lambda a: cmd_import_runtime(a),
        "import-sync": lambda a: cmd_import_sync(a),
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    if sys.argv[1] in ("import-runtime", "import-sync") and not arg:
        sys.exit("需要目录参数")
    cmds[sys.argv[1]](arg)


if __name__ == "__main__":
    main()
