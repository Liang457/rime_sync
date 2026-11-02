"""上游基座（rime-ice）管理。

只做两件事：git clone/pull 到 store/base/（只读，绝不推送），以及用基座目录
重建 store 基线（覆盖 base 来源文件、保护其他来源、清退已消失的 base 文件）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .store import FileStore


class GitError(RuntimeError):
    pass


class BaseManager:
    def __init__(self, store: FileStore, base_dir: Path, repo_url: str):
        self.store = store
        self.base_dir = base_dir
        self.repo_url = repo_url

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
            files[rel] = p
        return files

    def update_and_rebuild(self, force: bool = False) -> dict:
        """拉取基座最新 commit，然后重建 store 基线。返回两段报告。"""
        cloned_now = False
        if not self.cloned:
            self.base_dir.parent.mkdir(parents=True, exist_ok=True)
            self.run_git("clone", "--depth", "1", self.repo_url, str(self.base_dir),
                         timeout=600)
            cloned_now = True
        else:
            self.run_git("-C", str(self.base_dir), "pull", "--ff-only")
        commit_line = self.current_commit()
        commit_short = commit_line.split(" ", 1)[0] if commit_line else "unknown"
        report = self.store.rebuild_base(
            self.collect_base_files(), version=commit_short, force=force,
            detail=("克隆基座 " if cloned_now else "基座 ") + commit_short,
        )
        return {
            "git": {"cloned_now": cloned_now, "commit": commit_line},
            "rebuild": report,
        }
