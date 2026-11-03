"""上游基座（rime-ice）管理。

只做两件事：git clone/pull 到 store/base/（只读，绝不推送），以及用基座目录
重建 store 基线（覆盖 base 来源文件、保护其他来源、清退已消失的 base 文件）。

基座入库走白名单：只收客户端真正需要的运行时文件（词库/lua/opencc 目录 +
根目录的方案与配置 yaml、自定义短语 txt），仓库自带的 .github/、others/、
*.md、LICENSE 等开发文件一律不入库。
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from .store import FileStore

# 整棵子树入库的目录（客户端 Rime 用户目录需要的资产）
BASE_TREE_DIRS = ("cn_dicts", "en_dicts", "lua", "opencc")
# 根目录只收这些扩展名（default.yaml、各 *.schema.yaml、*.dict.yaml、custom_phrase.txt）
BASE_ROOT_EXTS = (".yaml", ".txt")
# 根目录匹配扩展名但仍排除的名单（东风破 recipe，客户端无用）
BASE_EXCLUDE_NAMES = {"recipe.yaml"}


class GitError(RuntimeError):
    pass


def _is_runtime_file(rel: str) -> bool:
    """基座白名单：判断仓库内相对路径是否是要分发到客户端的运行时文件。"""
    parts = rel.split("/")
    if parts[0] in BASE_TREE_DIRS:
        return True
    if len(parts) == 1:  # 根目录文件
        p = Path(rel)
        return p.suffix in BASE_ROOT_EXTS and rel not in BASE_EXCLUDE_NAMES
    return False


class BaseManager:
    def __init__(self, store: FileStore, base_dir: Path, repo_url: str):
        self.store = store
        self.base_dir = base_dir
        self.repo_url = repo_url
        # git 操作互斥：手动按钮 / 自动调度 / 改地址并发时只允许一个 rebuild 在跑
        # （store 内部锁管 manifest 一致性，这层管 git 工作目录与远端）
        self._op_lock = threading.Lock()

    # ---- git ---------------------------------------------------------------

    def run_git(self, *args: str, timeout: int = 300) -> str:
        cmd = ["git", *args]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError as e:
            raise GitError("找不到 git，请确认服务器已安装 git 并在 PATH 中") from e
        except subprocess.TimeoutExpired as e:
            raise GitError(f"git 超时: {' '.join(args)}") from e
        if proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
        return proc.stdout

    @property
    def cloned(self) -> bool:
        return (self.base_dir / ".git").is_dir()

    def current_commit(self) -> str:
        if not self.cloned:
            return ""
        out = self.run_git("-C", str(self.base_dir), "log", "-1", "--oneline")
        return out.strip()

    def current_origin(self) -> str:
        if not self.cloned:
            return ""
        out = self.run_git("-C", str(self.base_dir), "remote", "get-url", "origin")
        return out.strip()

    def set_repo_url(self, url: str) -> bool:
        """切换基座远端地址。已克隆且 origin 不同才动 git；返回是否实际切换。"""
        url = url.strip().rstrip("/")
        if not (url.startswith("https://") or url.startswith("http://")):
            raise GitError("仓库地址必须是 http(s):// 开头")
        with self._op_lock:
            if not self.cloned:
                return False  # 未克隆：下次更新会直接从新地址 clone
            old = self.current_origin().rstrip("/")
            if old == url:
                return False
            self.run_git("-C", str(self.base_dir), "remote", "set-url", "origin", url)
            return True

    def reclone(self) -> dict:
        """删除本地基座目录重新克隆（换仓库/历史分叉后的逃生通道）。"""
        with self._op_lock:
            if self.base_dir.exists():
                shutil.rmtree(self.base_dir)
        return self.update_and_rebuild(force=False)

    # ---- 状态 ---------------------------------------------------------------

    def status(self) -> dict:
        if not self.cloned:
            return {"cloned": False, "commit": "", "url": self.repo_url,
                    "base_files": 0}
        info = self.current_commit()
        count = sum(1 for p in self.base_dir.rglob("*")
                    if p.is_file() and ".git" not in p.relative_to(self.base_dir).parts)
        return {
            "cloned": True,
            "commit": info,
            "url": self.repo_url,
            "base_files": count,
        }

    # ---- 更新 + 重建基线 ------------------------------------------------------

    def collect_base_files(self) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for p in sorted(self.base_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self.base_dir).as_posix()
            if rel.startswith(".git/") or "/.git/" in f"/{rel}":
                continue
            if not _is_runtime_file(rel):
                continue  # 白名单外：.github/、others/、*.md、LICENSE 等不入库
            files[rel] = p
        return files

    def update_and_rebuild(self, force: bool = False) -> dict:
        """拉取基座最新 commit，然后重建 store 基线。返回两段报告。"""
        with self._op_lock:
            cloned_now = False
            if not self.cloned:
                self.base_dir.parent.mkdir(parents=True, exist_ok=True)
                self.run_git("clone", "--depth", "1", self.repo_url,
                             str(self.base_dir), timeout=600)
                cloned_now = True
            else:
                self.run_git("-C", str(self.base_dir), "pull", "--ff-only")
            commit_line = self.current_commit()
            commit_short = commit_line.split(" ", 1)[0] if commit_line else "unknown"
            report = self.store.rebuild_base(
                self.collect_base_files(), version=commit_short, force=force,
                detail=("克隆基座 " if cloned_now else "基座 ") + commit_short,
            )
            # 基线重建后重放词库联动（rime_ice.dict.yaml 的 import_tables）
            from . import rime_ice

            linkage = rime_ice.sync_import_tables(self.store)
            if linkage and linkage.get("changed"):
                self.store.activity(
                    "rime_ice",
                    f"基座重建后联动 import_tables（+{len(linkage['added'])} "
                    f"-{len(linkage['removed'])}）",
                )
            return {
                "git": {"cloned_now": cloned_now, "commit": commit_line},
                "rebuild": report,
                "rime_ice": linkage,
            }
