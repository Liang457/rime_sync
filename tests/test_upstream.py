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
