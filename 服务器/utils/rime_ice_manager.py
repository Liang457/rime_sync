import os
import logging
import json
import subprocess
from pathlib import Path

from utils.config_loader import config_manager
from utils.error_handler import APIError

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 120  # git 网络操作超时秒数


def _run_git(args, cwd=None, timeout=GIT_TIMEOUT):
    """执行 git 命令（带超时），返回 (returncode, stdout, stderr)"""
    cmd = ["git"] + args
    logger.debug(f"执行 git 命令: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error(f"Git 操作超时 ({timeout}s): {' '.join(cmd)}")
        raise APIError(f"Git 操作超时（超过 {timeout} 秒）", 500)
    except FileNotFoundError:
        logger.error("系统未安装 git 命令")
        raise APIError("系统未安装 git", 500)


def get_rime_ice_version():
    version_file = Path(config_manager.get("server", "paths.rime_ice_original")) / "README.md"
    if version_file.exists():
        try:
            with open(version_file, 'r', encoding='utf-8') as f:
                content = f.read()
                import re
                version_match = re.search(r'rime-ice\s+v?(\d+\.\d+\.\d+)', content, re.IGNORECASE)
                if version_match:
                    return version_match.group(1)
        except Exception as e:
            logger.warning(f"读取rime-ice版本失败: {e}")

    return "unknown"


def is_valid_git_repo(path):
    """检查路径是否为有效的git仓库"""
    try:
        import git
        git.Repo(path)
        return True
    except Exception:
        return False


def _get_head_commit(repo_path):
    """获取仓库 HEAD commit hash（本地操作，使用 GitPython）"""
    try:
        import git
        repo = git.Repo(repo_path)
        return repo.head.commit.hexsha
    except Exception as e:
        logger.error(f"获取 HEAD commit 失败: {e}")
        raise APIError(f"获取仓库信息失败: {str(e)}", 500)


def update_rime_ice_repo(force=False):
    repo_path = Path(config_manager.get("server", "paths.rime_ice_original"))

    # 如果目录不存在，或者存在但不是有效的git仓库，则克隆
    if not repo_path.exists() or not is_valid_git_repo(repo_path):
        if repo_path.exists():
            logger.warning(f"rime-ice目录存在但不是有效的git仓库，将删除并重新克隆")
            import shutil
            shutil.rmtree(repo_path)

        logger.info(f"rime-ice仓库不存在或无效，开始克隆...")
        result = clone_rime_ice_repo()
        return {
            "previous_commit": None,
            "current_commit": None,
            "changed_files": [],
            "upgraded": result["upgraded"],
            "message": result["message"]
        }

    try:
        local_commit = _get_head_commit(repo_path)

        if force:
            logger.info("强制更新rime-ice仓库")
            returncode, stdout, stderr = _run_git(
                ["pull", "--ff-only"], cwd=str(repo_path)
            )
            if returncode != 0:
                logger.error(f"git pull 失败: {stderr}")
                raise APIError(f"更新失败: {stderr[:200]}", 500)
            new_commit = _get_head_commit(repo_path)
            return {
                "previous_commit": local_commit,
                "current_commit": new_commit,
                "changed_files": [],
                "upgraded": True,
                "message": f"强制更新完成: {local_commit[:8]} -> {new_commit[:8]}"
            }

        # 检查是否有新提交（fetch 远程）
        logger.info("检查 rime-ice 远程更新...")
        returncode, stdout, stderr = _run_git(["fetch", "origin"], cwd=str(repo_path))
        if returncode != 0:
            logger.error(f"git fetch 失败: {stderr}")
            raise APIError(f"获取远程信息失败: {stderr[:200]}", 500)

        # 获取远程 main 分支 commit
        returncode, remote_commit_str, stderr = _run_git(
            ["rev-parse", "origin/main"], cwd=str(repo_path)
        )
        if returncode != 0:
            raise APIError(f"解析远程引用失败: {stderr[:200]}", 500)
        remote_commit = remote_commit_str

        if local_commit == remote_commit:
            logger.info("rime-ice仓库已经是最新版本")
            return {
                "previous_commit": local_commit,
                "current_commit": local_commit,
                "changed_files": [],
                "upgraded": False,
                "message": "已经是最新版本"
            }

        logger.info(f"检测到新版本，开始更新: {local_commit[:8]} -> {remote_commit[:8]}")

        # 执行 pull
        returncode, stdout, stderr = _run_git(
            ["pull", "--ff-only"], cwd=str(repo_path)
        )
        if returncode != 0:
            logger.error(f"git pull 失败: {stderr}")
            raise APIError(f"更新失败: {stderr[:200]}", 500)
        new_commit = _get_head_commit(repo_path)

        # 获取变化文件列表
        changed_files = []
        returncode, diff_output, _ = _run_git(
            ["diff", "--name-only", f"{local_commit}..{new_commit}"],
            cwd=str(repo_path)
        )
        if diff_output:
            changed_files = [f.strip() for f in diff_output.split('\n') if f.strip()]

        return {
            "previous_commit": local_commit,
            "current_commit": new_commit,
            "changed_files": changed_files,
            "upgraded": True,
            "message": f"已从 {local_commit[:8]} 更新到 {new_commit[:8]}"
        }

    except APIError:
        raise
    except Exception as e:
        logger.error(f"更新rime-ice仓库失败: {e}")
        raise APIError(f"更新rime-ice仓库失败: {str(e)}", 500)


def clone_rime_ice_repo():
    repo_url = config_manager.get("server", "git.rime_ice_repo")
    branch = config_manager.get("server", "git.rime_ice_branch")
    repo_path = Path(config_manager.get("server", "paths.rime_ice_original"))

    # 如果目录已存在且是有效的git仓库，则返回已存在
    if repo_path.exists() and is_valid_git_repo(repo_path):
        logger.warning(f"有效的git仓库已存在: {repo_path}")
        return {
            "upgraded": False,
            "message": "有效的git仓库已存在"
        }

    # 如果目录存在但不是git仓库，删除它
    if repo_path.exists():
        logger.warning(f"目录存在但不是有效的git仓库，将删除: {repo_path}")
        import shutil
        shutil.rmtree(repo_path)

    logger.info(f"克隆rime-ice仓库: {repo_url} (分支: {branch})")
    returncode, stdout, stderr = _run_git(
        ["clone", "--branch", branch, "--depth", "1", repo_url, str(repo_path)],
        timeout=300  # clone 需要更长的超时时间
    )
    if returncode != 0:
        logger.error(f"克隆失败: {stderr}")
        raise APIError(f"克隆rime-ice仓库失败: {stderr[:200]}", 500)

    logger.info(f"rime-ice仓库克隆完成: {repo_path}")
    return {
        "upgraded": True,
        "message": "克隆完成"
    }


def copy_to_runtime():
    src_path = Path(config_manager.get("server", "paths.rime_ice_original"))
    dst_path = Path(config_manager.get("server", "paths.runtime"))
    backup_tmp = None

    if not src_path.exists():
        logger.error(f"源目录不存在: {src_path}")
        raise APIError("rime-ice原始仓库不存在", 404)

    # 排除的目录和文件
    exclude_patterns = [
        '.git',
        '.github',
        'build',
        'rime_ice.userdb',
        'installation.yaml'
    ]

    import shutil
    from datetime import datetime as dt

    def ignore_patterns(path, names):
        ignored = []
        for name in names:
            full_path = Path(path) / name
            rel_path = full_path.relative_to(src_path) if full_path.is_relative_to(src_path) else Path(name)

            for pattern in exclude_patterns:
                if pattern in str(rel_path):
                    ignored.append(name)
                    break

        return ignored

    try:
        # 如果目标目录已存在，先重命名为备份（而非直接删除）
        if dst_path.exists():
            backup_name = f"{dst_path.name}_backup_{dt.now().strftime('%Y%m%d_%H%M%S')}"
            backup_tmp = dst_path.parent / backup_name
            shutil.move(str(dst_path), str(backup_tmp))
            logger.info(f"旧的runtime目录已备份: {backup_tmp}")

        # 复制目录树
        shutil.copytree(src_path, dst_path, ignore=ignore_patterns, dirs_exist_ok=False)

        # 自定义文件替换
        custom_replacements = []
        custom_skipped = []
        custom_files_dir = Path(__file__).parent.parent / "custom_files"
        custom_map_file = custom_files_dir / "custom_map.json"

        if custom_map_file.exists():
            try:
                with open(custom_map_file, 'r', encoding='utf-8') as f:
                    mapping = json.load(f)
                if isinstance(mapping, list) and mapping:
                    for item in mapping:
                        if not isinstance(item, dict):
                            continue
                        source = item.get('source')
                        target = item.get('target')
                        if not source or not target:
                            continue
                        source_path = custom_files_dir / source
                        if target.startswith('/'):
                            target = target[1:]
                        target_path = dst_path / target
                        if source_path.exists() and source_path.is_file():
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source_path, target_path)
                            custom_replacements.append({
                                "source": source,
                                "target": target,
                                "status": "applied"
                            })
                        else:
                            custom_skipped.append({
                                "source": source,
                                "target": target,
                                "reason": "source not found" if not source_path.exists() else "not a file"
                            })
                else:
                    logger.info("custom_map.json 为空或不是列表，跳过自定义替换")
            except Exception as e:
                logger.warning(f"解析 custom_map.json 失败: {e}")
        else:
            logger.info("custom_map.json 不存在，跳过自定义替换")

        # 复制成功后清理备份
        if backup_tmp is not None and backup_tmp.exists():
            shutil.rmtree(backup_tmp, ignore_errors=True)
            logger.info(f"备份已清理: {backup_tmp}")

        logger.info(f"已复制rime-ice文件到runtime目录: {dst_path}")
        return {
            "success": True,
            "message": "runtime目录已更新",
            "copied_files": "全部文件",
            "custom_replacements": {
                "applied": len(custom_replacements),
                "skipped": len(custom_skipped),
                "details": custom_replacements + custom_skipped
            }
        }
    except Exception as e:
        # 失败时恢复备份
        if backup_tmp is not None and backup_tmp.exists():
            logger.error(f"复制失败，恢复旧runtime目录")
            if dst_path.exists():
                shutil.rmtree(dst_path, ignore_errors=True)
            shutil.move(str(backup_tmp), str(dst_path))
        logger.error(f"复制到runtime目录失败: {e}")
        raise APIError(f"复制到runtime目录失败: {str(e)}", 500)
