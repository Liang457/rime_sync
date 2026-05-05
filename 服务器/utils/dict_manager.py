import os
import json
import logging
import tarfile
import hashlib
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from utils.config_loader import config_manager
from utils.error_handler import APIError

logger = logging.getLogger(__name__)

class DictManager:
    def __init__(self):
        self.cn_dicts_path = Path(config_manager.get("dict", "dict.cn_dicts_path"))
        self.en_dicts_path = Path(config_manager.get("dict", "dict.en_dicts_path"))
        self.allowed_extensions = config_manager.get("dict", "dict.allowed_extensions", [".dict.yaml", ".txt"])
        
        # 确保目录存在
        self.cn_dicts_path.mkdir(parents=True, exist_ok=True)
        self.en_dicts_path.mkdir(parents=True, exist_ok=True)
    
    def get_dict_info(self, category: str = None, since: str = None) -> Dict:
        """
        获取词库文件信息
        
        参数:
            category: 类别，'cn' 或 'en'，为None时返回所有
            since: 时间戳，只返回此时间之后有变动的文件
        
        返回:
            词库信息字典
        """
        result = {}
        total_size = 0
        
        categories = []
        if category is None:
            categories = [('cn', self.cn_dicts_path), ('en', self.en_dicts_path)]
        elif category == 'cn':
            categories = [('cn', self.cn_dicts_path)]
        elif category == 'en':
            categories = [('en', self.en_dicts_path)]
        else:
            raise APIError(f"无效的类别: {category}", 400)
        
        since_time = None
        if since:
            try:
                since_time = datetime.fromisoformat(since.replace('Z', '+00:00'))
            except ValueError:
                raise APIError("无效的时间格式，请使用ISO格式", 400)
        
        for cat_name, cat_path in categories:
            if not cat_path.exists():
                result[cat_name] = []
                continue
            
            files = []
            for file_path in cat_path.rglob('*'):
                if file_path.is_file():
                    # 检查文件扩展名
                    if self.allowed_extensions and not any(file_path.name.endswith(ext) for ext in self.allowed_extensions):
                        continue
                    
                    # 检查时间筛选
                    if since_time:
                        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                        if file_mtime < since_time:
                            continue
                    
                    # 计算相对路径
                    rel_path = file_path.relative_to(cat_path)
                    
                    # 计算文件哈希
                    file_hash = self._calculate_hash(file_path)
                    
                    file_info = {
                        "path": str(rel_path),
                        "size": file_path.stat().st_size,
                        "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                        "hash": file_hash,
                        "type": "file"
                    }
                    
                    files.append(file_info)
                    total_size += file_info["size"]
            
            # 按路径排序
            files.sort(key=lambda x: x["path"])
            result[cat_name] = files
        
        return {
            "categories": result,
            "total_size": total_size,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_file_content(self, file_name: str, category: str = None) -> Path:
        """
        获取词库文件路径
        
        参数:
            file_name: 文件名（可能包含相对路径）
            category: 类别，'cn' 或 'en'，为None时自动判断
        
        返回:
            文件路径
        """
        # 确定文件所在目录
        if category == 'cn':
            base_path = self.cn_dicts_path
            file_path = self.cn_dicts_path / file_name
        elif category == 'en':
            base_path = self.en_dicts_path
            file_path = self.en_dicts_path / file_name
        else:
            # 自动判断：先在cn_dicts中查找，然后在en_dicts中查找
            cn_path = self.cn_dicts_path / file_name
            en_path = self.en_dicts_path / file_name
            
            if cn_path.exists():
                base_path = self.cn_dicts_path
                file_path = cn_path
            elif en_path.exists():
                base_path = self.en_dicts_path
                file_path = en_path
            else:
                raise APIError(f"文件不存在: {file_name}", 404)
        
        # 安全检查：防止路径遍历
        try:
            file_path.resolve().relative_to(base_path.resolve())
        except ValueError:
            raise APIError("无效的文件路径", 400)
        
        if not file_path.exists():
            raise APIError(f"文件不存在: {file_name}", 404)
        
        return file_path
    
    def create_tar(self, category: str = None, since: str = None) -> Path:
        """
        创建词库tar文件

        参数:
            category: 类别，'cn' 或 'en'，为None时包含所有
            since: 时间戳，只包含此时间之后有变动的文件

        返回:
            临时tar文件路径
        """
        # 确定要包含的目录
        categories = []
        if category is None:
            categories = [('cn_dicts', self.cn_dicts_path), ('en_dicts', self.en_dicts_path)]
        elif category == 'cn':
            categories = [('cn_dicts', self.cn_dicts_path)]
        elif category == 'en':
            categories = [('en_dicts', self.en_dicts_path)]
        else:
            raise APIError(f"无效的类别: {category}", 400)

        since_time = None
        if since:
            try:
                since_time = datetime.fromisoformat(since.replace('Z', '+00:00'))
            except ValueError:
                raise APIError("无效的时间格式，请使用ISO格式", 400)

        # 创建临时tar文件
        temp_tar = tempfile.NamedTemporaryFile(suffix='.tar', delete=False)
        temp_tar.close()

        try:
            with tarfile.open(temp_tar.name, 'w') as tarf:
                for dir_name, dir_path in categories:
                    if not dir_path.exists():
                        continue

                    for file_path in dir_path.rglob('*'):
                        if file_path.is_file():
                            # 检查文件扩展名
                            if self.allowed_extensions and not any(file_path.name.endswith(ext) for ext in self.allowed_extensions):
                                continue

                            # 检查时间筛选
                            if since_time:
                                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                                if file_mtime < since_time:
                                    continue

                            # 计算相对路径（保留目录结构）
                            rel_path = file_path.relative_to(dir_path)
                            arcname = f"{dir_name}/{rel_path}"

                            tarf.add(file_path, arcname=arcname)

            return Path(temp_tar.name)
        except Exception as e:
            # 清理临时文件
            if Path(temp_tar.name).exists():
                Path(temp_tar.name).unlink()
            raise APIError(f"创建tar文件失败: {str(e)}", 500)
    
    def _calculate_hash(self, filepath: Path) -> str:
        """计算文件哈希（SHA3-256）"""
        hash_obj = hashlib.sha3_256()
        
        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hash_obj.update(chunk)
            return f"sha3-256:{hash_obj.hexdigest()}"
        except Exception as e:
            logger.error(f"计算文件哈希失败: {filepath}, 错误: {e}")
            raise APIError(f"计算文件哈希失败: {str(e)}", 500)

dict_manager = DictManager()