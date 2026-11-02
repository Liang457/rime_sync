"""发布服务层：rime_dict 的 /api/publish 与控制台上传共用。"""
from __future__ import annotations

from pathlib import Path

from .store import AddItem, FileStore


def publish_files(
    store: FileStore,
    files: list[tuple[str, Path | bytes]],
    *,
    source: str = "publish",
    version: str = "",
    detail: str = "",
) -> list[dict]:
    """files: [(目标相对路径, 内容/来源文件)]，按 sha3 幂等入库并更新 manifest。"""
    items = [AddItem(rel, data, source=source, version=version) for rel, data in files]
    return store.add_many(items, detail=detail)
