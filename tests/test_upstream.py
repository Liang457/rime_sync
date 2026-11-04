"""上游基座：白名单过滤、更新地址切换（真实 git）。"""
import shutil
import subprocess

import pytest

from app.services.upstream import BaseManager, GitError, _is_runtime_file

HAS_GIT = shutil.which("git") is not None


def test_runtime_whitelist():
    included = {
        "cn_dicts/8105.dict.yaml", "cn_dicts/base.dict.yaml",
        "en_dicts/en.dict.yaml", "lua/a.lua", "opencc/t2s.txt",
        "default.yaml", "rime_ice.schema.yaml", "custom_phrase.txt",
        "symbols_v.yaml", "melt_eng.dict.yaml",
    }
    excluded = {
        ".github/workflows/release.yml", "others/docs/x.md",
        "README.md", "AGENTS.md", "LICENSE", "go.work", ".gitignore",
        "recipe.yaml", "others/patch_examples/default.custom.yaml",
    }
    for rel in included:
        assert _is_runtime_file(rel), rel
    for rel in excluded:
        assert not _is_runtime_file(rel), rel


def test_collect_base_files_filters(tmp_path):
    base = tmp_path / "base"
    (base / "cn_dicts").mkdir(parents=True)
    (base / ".github" / "workflows").mkdir(parents=True)
    (base / "others").mkdir()
    for rel, body in {
        "default.yaml": "d", "cn_dicts/8105.dict.yaml": "c",
        "README.md": "r", ".github/workflows/x.yml": "g",
        "others/x.txt": "o", "recipe.yaml": "rc", "go.work": "w",
    }.items():
        (base / rel).write_text(body, encoding="utf-8")
    mgr = BaseManager(store=None, base_dir=base, repo_url="https://x/y")
    assert set(mgr.collect_base_files()) == {"default.yaml", "cn_dicts/8105.dict.yaml"}


def test_set_repo_url_not_cloned(tmp_path):
    mgr = BaseManager(store=None, base_dir=tmp_path / "nope",
                      repo_url="https://a/a")
    assert mgr.current_origin() == ""
    assert mgr.set_repo_url("https://b/b") is False  # 未克隆：等下次更新直接 clone


@pytest.mark.skipif(not HAS_GIT, reason="需要 git")
def test_set_repo_url_switches_origin(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")
    git("remote", "add", "origin", "https://old/old")

    mgr = BaseManager(store=None, base_dir=repo, repo_url="https://old/old")
    assert mgr.current_origin() == "https://old/old"
    assert mgr.set_repo_url("https://old/old") is False  # 同址：不动
    assert mgr.set_repo_url("https://new/new") is True
    assert mgr.current_origin() == "https://new/new"
    with pytest.raises(GitError):
        mgr.set_repo_url("ftp://bad/bad")


# ---- 真 git 端到端：clone --depth 1 → rebuild → pull --ff-only → rebuild ------


def _mk_remote(remote) -> None:
    """建一个本地远端仓库：白名单内文件 + 白名单外垃圾文件。"""
    def git(*args):
        subprocess.run(["git", *args], cwd=remote, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (remote / "cn_dicts").mkdir(parents=True)
    (remote / "default.yaml").write_text("v1", encoding="utf-8")
    (remote / "cn_dicts" / "8105.dict.yaml").write_text("d1", encoding="utf-8")
    (remote / "README.md").write_text("junk", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")


@pytest.mark.skipif(not HAS_GIT, reason="需要 git")
def test_update_and_rebuild_clone_then_pull(tmp_path):
    """首次更新真 clone + 重建；远端有新提交后第二次更新真 pull --ff-only。"""
    from app.services.store import FileStore

    remote = tmp_path / "remote"
    remote.mkdir()
    _mk_remote(remote)
    store = FileStore(tmp_path / "store")
    mgr = BaseManager(store=store, base_dir=tmp_path / "base", repo_url=str(remote))

    r1 = mgr.update_and_rebuild()
    assert r1["git"]["cloned_now"] is True
    assert r1["rebuild"]["added"] == 2            # README.md 被白名单挡住
    assert "README.md" not in store.manifest()["files"]
    assert store.get_path("default.yaml").read_bytes() == b"v1"
    assert store.manifest()["files"]["default.yaml"]["version"]
    assert mgr.cloned

    # 远端新提交：改一个 + 加一个
    (remote / "default.yaml").write_text("v2", encoding="utf-8")
    (remote / "cn_dicts" / "new.dict.yaml").write_text("d2", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=remote, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=remote,
                   check=True, capture_output=True)

    r2 = mgr.update_and_rebuild()
    assert r2["git"]["cloned_now"] is False
    assert r2["rebuild"]["updated"] == 1 and r2["rebuild"]["added"] == 1
    assert store.get_path("default.yaml").read_bytes() == b"v2"
    assert "cn_dicts/new.dict.yaml" in store.manifest()["files"]


@pytest.mark.skipif(not HAS_GIT, reason="需要 git")
def test_run_git_failure_raises_with_stderr(tmp_path):
    """run_git 子进程封装：非零退出 → GitError，且消息里带上 stderr 内容。"""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    mgr = BaseManager(store=None, base_dir=not_a_repo, repo_url="https://x/y")
    with pytest.raises(GitError) as ei:
        mgr.run_git("-C", str(not_a_repo), "log", "-1", "--oneline")
    msg = str(ei.value)
    assert "失败" in msg and "log" in msg
    assert msg.split("失败:")[-1].strip()          # stderr 内容被拼进消息
