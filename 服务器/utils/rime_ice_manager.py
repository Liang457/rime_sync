import os
import logging
import json
from pathlib import Path

from utils.config_loader import config_manager
from utils.error_handler import APIError

logger = logging.getLogger(__name__)

def get_rime_ice_version():
    version_file = Path(config_manager.get("server", "paths.rime_ice_original")) / "README.md"
    if version_file.exists():
        try:
            with open(version_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 简单提取版本信息
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
        import git
        repo = git.Repo(repo_path)
        
        local_commit = repo.head.commit.hexsha
        
        if force:
            logger.info("强制更新rime-ice仓库")
            repo.remotes.origin.pull()
            new_commit = repo.head.commit.hexsha
            return {
                "previous_commit": local_commit,
                "current_commit": new_commit,
                "changed_files": [],  # 简化，不计算具体变化文件
                "upgraded": True,
                "message": f"强制更新完成: {local_commit[:8]} -> {new_commit[:8]}"
            }
        
        # 检查是否有新提交
        repo.remotes.origin.fetch()
        remote_commit = repo.remotes.origin.refs.main.commit.hexsha
        
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
        repo.remotes.origin.pull()
        new_commit = repo.head.commit.hexsha
        
        # 获取变化文件列表（简化版本）
        changed_files = []
        try:
            diff = repo.git.diff(f"{local_commit}..{new_commit}", name_only=True)
            if diff:
                changed_files = [f.strip() for f in diff.split('\n') if f.strip()]
        except Exception:
            pass  # 忽略获取变化文件的错误
        
        return {
            "previous_commit": local_commit,
            "current_commit": new_commit,
            "changed_files": changed_files,
            "upgraded": True,
            "message": f"已从 {local_commit[:8]} 更新到 {new_commit[:8]}"
        }
        
    except ImportError:
        logger.error("未安装gitpython库")
        raise APIError("gitpython库未安装", 500)
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
    
    try:
        import git
        logger.info(f"克隆rime-ice仓库: {repo_url} (分支: {branch})")
        repo = git.Repo.clone_from(repo_url, repo_path, branch=branch)
        logger.info(f"rime-ice仓库克隆完成: {repo_path}")
        return {
            "upgraded": True,
            "message": "克隆完成"
        }
    except ImportError:
        logger.error("未安装gitpython库")
        raise APIError("gitpython库未安装", 500)
    except Exception as e:
        logger.error(f"克隆rime-ice仓库失败: {e}")
        raise APIError(f"克隆rime-ice仓库失败: {str(e)}", 500)

def copy_to_runtime():
    src_path = Path(config_manager.get("server", "paths.rime_ice_original"))
    dst_path = Path(config_manager.get("server", "paths.runtime"))
    
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
    
    def ignore_patterns(path, names):
        ignored = []
        for name in names:
            full_path = Path(path) / name
            rel_path = full_path.relative_to(src_path) if full_path.is_relative_to(src_path) else Path(name)
            
            # 检查是否匹配排除模式
            for pattern in exclude_patterns:
                if pattern in str(rel_path):
                    ignored.append(name)
                    break
        
        return ignored
    
    try:
        # 如果目标目录已存在，先删除
        if dst_path.exists():
            shutil.rmtree(dst_path)
            logger.info(f"已删除旧的runtime目录: {dst_path}")
        
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
                        # 处理 target 路径：去掉开头的 '/'
                        if target.startswith('/'):
                            target = target[1:]
                        target_path = dst_path / target
                        if source_path.exists() and source_path.is_file():
                            # 确保目标目录存在
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            # 复制文件
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
        logger.error(f"复制到runtime目录失败: {e}")
        raise APIError(f"复制到runtime目录失败: {str(e)}", 500)