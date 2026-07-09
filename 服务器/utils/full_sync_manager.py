import os
import json
import logging
import tarfile
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set

from utils.config_loader import config_manager
from utils.error_handler import APIError
from utils.hash_utils import compute_file_hash, safe_parse_iso

logger = logging.getLogger(__name__)

class FullSyncManager:
    def __init__(self):
        self.runtime_path = Path(config_manager.get("server", "paths.runtime"))
        
        # 默认排除的文件和目录
        self.default_excludes = [
            "installation.yaml",
            ".github/",
            "build/",
            "rime_ice.userdb"
        ]
    
    def calculate_hash(self, filepath: Path) -> str:
        """计算文件 SHA3-256 哈希"""
        return compute_file_hash(filepath)
    
    def get_exclude_patterns(self, extra_excludes: str = None) -> Set[str]:
        """获取排除模式集合"""
        excludes = set(self.default_excludes)
        
        if extra_excludes:
            for pattern in extra_excludes.split(','):
                pattern = pattern.strip()
                if pattern:
                    excludes.add(pattern)
        
        return excludes
    
    def is_excluded(self, file_path: Path, exclude_patterns: Set[str]) -> bool:
        """检查文件是否应该被排除"""
        # 转换为相对于runtime目录的路径字符串
        rel_path = str(file_path.relative_to(self.runtime_path))
        
        for pattern in exclude_patterns:
            # 如果模式以/结尾，表示目录排除
            if pattern.endswith('/'):
                if rel_path.startswith(pattern):
                    return True
            else:
                # 精确匹配文件名或路径
                if rel_path == pattern:
                    return True
        
        return False
    
    def get_file_info(self, exclude_patterns: Set[str] = None, since: str = None) -> Dict:
        """获取完整配置包文件信息"""
        if exclude_patterns is None:
            exclude_patterns = self.get_exclude_patterns()
        
        files = []
        total_size = 0
        
        # 递归遍历runtime目录
        for file_path in self.runtime_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            # 检查是否被排除
            if self.is_excluded(file_path, exclude_patterns):
                continue
            
            # 时间筛选
            if since:
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                since_time = safe_parse_iso(since)
                if file_mtime < since_time:
                    continue
            
            rel_path = file_path.relative_to(self.runtime_path)
            file_info = {
                "path": str(rel_path).replace('\\', '/'),
                "size": file_path.stat().st_size,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                "hash": self.calculate_hash(file_path),
                "type": "file"
            }
            
            files.append(file_info)
            total_size += file_info["size"]
        
        return {
            "files": files,
            "total_size": total_size,
            "timestamp": datetime.now().isoformat(),
            "excluded": list(exclude_patterns)
        }
    
    def create_tar(self, exclude_patterns: Set[str] = None, since: str = None) -> Path:
        """创建完整配置包的tar文件"""
        if exclude_patterns is None:
            exclude_patterns = self.get_exclude_patterns()

        # 创建临时tar文件
        temp_tar = tempfile.NamedTemporaryFile(suffix='.tar', delete=False)
        temp_tar.close()

        try:
            with tarfile.open(temp_tar.name, 'w') as tarf:
                for file_path in self.runtime_path.rglob('*'):
                    if not file_path.is_file():
                        continue

                    # 检查是否被排除
                    if self.is_excluded(file_path, exclude_patterns):
                        continue

                    # 时间筛选
                    if since:
                        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                        since_time = datetime.fromisoformat(since.replace('Z', '+00:00'))
                        if file_mtime < since_time:
                            continue

                    rel_path = file_path.relative_to(self.runtime_path)
                    tarf.add(str(file_path), arcname=str(rel_path))

            logger.info(f"完整配置包tar创建成功: {temp_tar.name}")
            return Path(temp_tar.name)

        except Exception as e:
            logger.error(f"创建tar文件失败: {e}")
            # 清理临时文件
            if os.path.exists(temp_tar.name):
                os.unlink(temp_tar.name)
            raise APIError(f"创建tar文件失败: {str(e)}", 500)

    def upload_tar(self, tar_content, overwrite: bool = False, hash_value: str = None) -> Dict:
        """上传完整配置包tar文件"""
        if not overwrite:
            raise APIError("完整配置包上传需要明确设置 overwrite=true 确认操作", 400)

        # 创建临时目录用于解压
        with tempfile.TemporaryDirectory(prefix="rime_full_sync_") as temp_dir:
            temp_path = Path(temp_dir)
            tar_path = temp_path / "uploaded.tar"

            try:
                # 保存tar文件
                tar_content.save(str(tar_path))
            except Exception:
                # 如果save方法不可用，直接写入
                tar_content.seek(0)
                with open(tar_path, 'wb') as f:
                    f.write(tar_content.read())

            # 验证哈希（如果提供了）
            if hash_value:
                actual_hash = compute_file_hash(tar_path)
                if actual_hash != hash_value:
                    raise APIError(
                        f"哈希校验失败: 期望 {hash_value[:16]}..., 实际 {actual_hash[:16]}...",
                        400
                    )

            # 验证tar文件
            try:
                with tarfile.open(tar_path, 'r') as tf:
                    pass  # 只验证格式，不提取内容
            except Exception:
                raise APIError("上传的文件不是有效的tar文件", 400)

            # 备份现有runtime目录（必须成功才能继续）
            backup_path = None
            if overwrite:
                backup_dir = Path(config_manager.get("server", "paths.backups"))
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backup_dir / f"runtime_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                try:
                    shutil.copytree(self.runtime_path, backup_path)
                    logger.info(f"已创建runtime目录备份: {backup_path}")
                except Exception as e:
                    logger.error(f"创建备份失败，中止操作: {e}")
                    raise APIError(f"创建备份失败，无法安全执行覆盖操作: {str(e)}", 500)

            try:
                # 清空现有runtime目录（排除隐藏文件/目录）
                for item in list(self.runtime_path.iterdir()):
                    if item.name.startswith('.'):
                        continue
                    try:
                        if item.is_file() or item.is_symlink():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    except Exception as e:
                        logger.warning(f"清理 {item} 失败: {e}")

                # 解压tar文件到runtime目录
                with tarfile.open(tar_path, 'r') as tarf:
                    tarf.extractall(path=self.runtime_path, filter='data')

                # 统计文件
                extracted_files = []
                total_size = 0
                for file_path in self.runtime_path.rglob('*'):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(self.runtime_path)
                        extracted_files.append(str(rel_path).replace('\\', '/'))
                        total_size += file_path.stat().st_size

                logger.info(f"完整配置包上传成功，解压 {len(extracted_files)} 个文件，总大小 {total_size} 字节")

                return {
                    "files_added": len(extracted_files),
                    "total_size": total_size,
                    "timestamp": datetime.now().isoformat(),
                    "backup_created": backup_path is not None,
                    "backup_path": str(backup_path) if backup_path else None,
                    "warning": "服务器配置已重置，请谨慎操作"
                }

            except Exception as e:
                # 恢复备份
                if backup_path and backup_path.exists():
                    logger.info(f"尝试恢复备份: {backup_path}")
                    # 清空当前runtime目录
                    for item in self.runtime_path.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    # 恢复备份
                    shutil.copytree(backup_path, self.runtime_path, dirs_exist_ok=True)

                logger.error(f"完整配置包上传失败: {e}")
                raise APIError(f"完整配置包上传失败: {str(e)}", 500)

# 创建全局实例
full_sync_manager = FullSyncManager()