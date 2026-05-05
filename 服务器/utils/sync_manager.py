import os
import json
import logging
import tarfile
import hashlib
import shutil
import errno
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from utils.config_loader import config_manager
from utils.error_handler import APIError

logger = logging.getLogger(__name__)

class SyncManager:
    def __init__(self):
        self.sync_base = Path(config_manager.get("server", "paths.sync"))
        self.hash_algorithm = config_manager.get("sync", "sync.hash_algorithm", "sha3-256")
        self.manifest_filename = config_manager.get("sync", "sync.manifest_file", "_manifest.json")
        self.max_files_per_device = config_manager.get("sync", "sync.max_files_per_device", 100)
        self.max_total_size_mb = config_manager.get("sync", "sync.max_total_size_mb", 1024)
        
        # 确保基础目录存在
        self.sync_base.mkdir(parents=True, exist_ok=True)
    
    def get_device_path(self, device_name: str) -> Path:
        """获取设备目录路径"""
        device_path = self.sync_base / device_name
        return device_path
    
    def validate_device_name(self, device_name: str) -> bool:
        """验证设备名是否合法"""
        if not device_name or not isinstance(device_name, str):
            return False
        if device_name in ('.', '..'):
            return False
        for char in ('/', '\\', '\0'):
            if char in device_name:
                return False
        if device_name.startswith('.') or device_name.startswith('~'):
            return False
        if len(device_name) > 64:
            return False
        return True
    
    def calculate_hash(self, filepath: Path) -> str:
        """计算文件哈希"""
        if self.hash_algorithm == "sha3-256":
            hash_obj = hashlib.sha3_256()
        else:
            # 默认为sha256
            hash_obj = hashlib.sha256()
        
        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hash_obj.update(chunk)
            return f"{self.hash_algorithm}:{hash_obj.hexdigest()}"
        except Exception as e:
            logger.error(f"计算文件哈希失败: {filepath}, 错误: {e}")
            raise APIError(f"计算文件哈希失败: {str(e)}", 500)
    
    def load_manifest(self, device_name: str) -> Dict:
        """加载设备的清单文件"""
        device_path = self.get_device_path(device_name)
        manifest_path = device_path / self.manifest_filename
        
        if not manifest_path.exists():
            return {}
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载清单文件失败: {manifest_path}, 错误: {e}")
            return {}
    
    def save_manifest(self, device_name: str, manifest: Dict):
        """保存设备的清单文件"""
        device_path = self.get_device_path(device_name)
        manifest_path = device_path / self.manifest_filename
        
        try:
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存清单文件失败: {manifest_path}, 错误: {e}")
            raise APIError(f"保存清单文件失败: {str(e)}", 500)
    
    def update_file_info(self, device_name: str, filename: str, filepath: Path):
        """更新文件信息到清单"""
        manifest = self.load_manifest(device_name)
        
        file_info = {
            "hash": self.calculate_hash(filepath),
            "size": filepath.stat().st_size,
            "modified": datetime.now().isoformat(),
            "type": "file"
        }
        
        manifest[filename] = file_info
        self.save_manifest(device_name, manifest)
        
        return file_info
    
    def upload_file(self, device_name: str, filename: str, file_content) -> Dict:
        """上传单个文件"""
        if not self.validate_device_name(device_name):
            raise APIError("设备名不合法", 400)
        
        device_path = self.get_device_path(device_name)
        device_path.mkdir(parents=True, exist_ok=True)
        
        # 检查文件数量限制
        manifest = self.load_manifest(device_name)
        if len(manifest) >= self.max_files_per_device:
            raise APIError(f"设备文件数量超过限制: {self.max_files_per_device}", 400)
        
        # 保存文件
        file_path = device_path / filename
        try:
            file_content.save(str(file_path))
        except Exception as e:
            logger.error(f"保存文件失败: {file_path}, 错误: {e}")
            raise APIError(f"保存文件失败: {str(e)}", 500)
        
        # 更新清单
        file_info = self.update_file_info(device_name, filename, file_path)
        
        logger.info(f"文件上传成功: 设备={device_name}, 文件={filename}, 大小={file_info['size']}")
        
        return {
            "device": device_name,
            "filename": filename,
            "size": file_info["size"],
            "hash": file_info["hash"],
            "timestamp": file_info["modified"]
        }
    
    def upload_tar(self, device_name: str, tar_content) -> Dict:
        """上传tar文件"""
        if not self.validate_device_name(device_name):
            raise APIError("设备名不合法", 400)

        device_path = self.get_device_path(device_name)
        device_path.mkdir(parents=True, exist_ok=True)

        # 创建临时目录
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tar_path = temp_path / "upload.tar"

            # 保存tar文件
            try:
                tar_content.save(str(tar_path))
            except Exception:
                # 如果save失败，尝试直接写入
                tar_content.seek(0)
                with open(tar_path, 'wb') as f:
                    f.write(tar_content.read())

            # 解压tar文件
            try:
                with tarfile.open(tar_path, 'r') as tar_ref:
                    tar_ref.extractall(path=temp_path, filter='data')
            except Exception as e:
                logger.error(f"解压tar文件失败: {e}")
                raise APIError(f"解压tar文件失败: {str(e)}", 400)

            # 处理解压的文件
            uploaded_files = []
            for extracted_file in temp_path.rglob('*'):
                if extracted_file.is_file() and extracted_file != tar_path:
                    # 计算相对路径
                    rel_path = extracted_file.relative_to(temp_path)
                    filename = str(rel_path).replace('\\', '/')  # 统一使用正斜杠

                    # 移动文件到设备目录（处理跨设备移动）
                    target_path = device_path / rel_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    try:
                        # 首先尝试使用shutil.move（如果同设备会更快）
                        shutil.move(str(extracted_file), str(target_path))
                    except OSError as e:
                        # 跨设备 move 失败时，退化为 copy + delete
                        # errno.EXDEV 是 Linux 跨设备错误, winerror 17 是 Windows 等价
                        if e.errno == errno.EXDEV or getattr(e, 'winerror', None) == 17:
                            logger.debug(f"跨设备移动，使用复制+删除: {extracted_file} -> {target_path}")
                            shutil.copy2(str(extracted_file), str(target_path))
                            extracted_file.unlink()
                        else:
                            raise

                    # 更新清单
                    file_info = self.update_file_info(device_name, filename, target_path)
                    uploaded_files.append({
                        "name": filename,
                        "size": file_info["size"],
                        "hash": file_info["hash"]
                    })

            logger.info(f"tar上传成功: 设备={device_name}, 文件数={len(uploaded_files)}")

            return {
                "device": device_name,
                "files_added": [f["name"] for f in uploaded_files],
                "files_info": uploaded_files,
                "total_size": sum(f["size"] for f in uploaded_files),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_file_info(self, device_name: str, filename: str = None) -> Dict:
        """获取文件信息"""
        if not self.validate_device_name(device_name):
            raise APIError("设备名不合法", 400)
        
        device_path = self.get_device_path(device_name)
        if not device_path.exists():
            raise APIError(f"设备不存在: {device_name}", 404)
        
        manifest = self.load_manifest(device_name)
        
        if filename:
            # 获取单个文件信息
            if filename not in manifest:
                # 检查文件是否存在但不在清单中
                file_path = device_path / filename
                if file_path.exists():
                    # 添加到清单
                    file_info = self.update_file_info(device_name, filename, file_path)
                    manifest[filename] = file_info
                else:
                    raise APIError(f"文件不存在: {filename}", 404)
            
            file_info = manifest[filename].copy()
            file_info["name"] = filename
            return file_info
        else:
            # 获取所有文件信息
            files = []
            total_size = 0
            
            # 首先确保清单包含所有实际文件
            for file_path in device_path.rglob('*'):
                if file_path.is_file() and file_path.name != self.manifest_filename:
                    rel_path = file_path.relative_to(device_path)
                    filename = str(rel_path).replace('\\', '/')
                    
                    if filename not in manifest:
                        # 更新清单
                        self.update_file_info(device_name, filename, file_path)
                        manifest = self.load_manifest(device_name)  # 重新加载
            
            # 返回清单中的所有文件
            for filename, info in manifest.items():
                file_info = info.copy()
                file_info["name"] = filename
                files.append(file_info)
                total_size += info.get("size", 0)
            
            return {
                "files": files,
                "total_size": total_size,
                "timestamp": datetime.now().isoformat()
            }
    
    def list_devices(self) -> List[str]:
        """列出所有设备"""
        devices = []
        for item in self.sync_base.iterdir():
            if item.is_dir():
                devices.append(item.name)
        return sorted(devices)
    
    def get_device_details(self) -> List[Dict]:
        """获取设备详细信息"""
        devices_info = []
        
        for device_name in self.list_devices():
            device_path = self.get_device_path(device_name)
            manifest = self.load_manifest(device_name)
            
            # 计算文件总数和总大小
            total_files = 0
            total_size = 0
            last_sync = None
            
            for file_info in manifest.values():
                total_files += 1
                total_size += file_info.get("size", 0)
                
                # 获取最新的修改时间
                modified = file_info.get("modified")
                if modified:
                    try:
                        modified_dt = datetime.fromisoformat(modified.replace('Z', '+00:00'))
                        if last_sync is None or modified_dt > last_sync:
                            last_sync = modified_dt
                    except (ValueError, TypeError):
                        pass
            
            devices_info.append({
                "name": device_name,
                "last_sync": last_sync.isoformat() if last_sync else None,
                "total_files": total_files,
                "total_size": total_size
            })
        
        # 按最后同步时间倒序排序
        devices_info.sort(key=lambda x: x["last_sync"] or "", reverse=True)
        return devices_info
    
    def get_file_content(self, device_name: str, filename: str) -> Path:
        """获取文件内容路径"""
        if not self.validate_device_name(device_name):
            raise APIError("设备名不合法", 400)
        
        device_path = self.get_device_path(device_name)
        file_path = device_path / filename
        
        # 安全检查：防止路径遍历
        try:
            file_path.resolve().relative_to(device_path.resolve())
        except ValueError:
            raise APIError("无效的文件路径", 400)
        
        if not file_path.exists():
            raise APIError(f"文件不存在: {filename}", 404)
        
        return file_path
    
    def create_tar(self, device_name: str, since: str = None) -> Path:
        """创建设备的tar文件（写入TAR_CACHE目录）"""
        import uuid
        import tempfile

        device_path = self.get_device_path(device_name)
        if not device_path.exists():
            raise APIError(f"设备不存在: {device_name}", 404)

        # 创建临时tar文件（写入系统临时目录，后续由路由层移到TAR_CACHE）
        temp_tar = tempfile.NamedTemporaryFile(suffix='.tar', delete=False)
        temp_tar.close()

        try:
            with tarfile.open(temp_tar.name, 'w') as tarf:
                for file_path in device_path.rglob('*'):
                    if file_path.is_file() and file_path.name != self.manifest_filename:
                        rel_path = file_path.relative_to(device_path)

                        # 检查时间筛选
                        if since:
                            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                            since_time = datetime.fromisoformat(since.replace('Z', '+00:00'))
                            if file_mtime < since_time:
                                continue

                        # 添加到tar
                        tarf.add(file_path, arcname=str(rel_path))

            return Path(temp_tar.name)
        except Exception as e:
            # 清理临时文件
            if Path(temp_tar.name).exists():
                Path(temp_tar.name).unlink()
            raise APIError(f"创建tar文件失败: {str(e)}", 500)

sync_manager = SyncManager()