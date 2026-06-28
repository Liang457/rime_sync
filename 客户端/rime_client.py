#!/usr/bin/env python3
"""
Rime 客户端同步脚本 - Windows 版本
与 rime-server 交互，同步词库、用户输入词库等配置。
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
import tarfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

import requests
import yaml

# 默认配置文件路径
DEFAULT_CONFIG_PATH = Path(__file__).parent / "client_config.json"

class RimeClient:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config = self.load_config()
        self.setup_logging()
        self.session = requests.Session()
        self.timeout = self.config["server"]["timeout"]
        
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件，支持新旧格式"""
        if not self.config_path.exists():
            logging.error(f"配置文件不存在: {self.config_path}")
            logging.info("正在创建默认配置文件...")
            self.create_default_config()
            sys.exit(1)
            
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            # 迁移旧格式到新格式
            config = self.migrate_config(config)
            
            # 设置默认值（新格式）
            config.setdefault("server", {}).setdefault("url", "http://localhost:10032")
            config.setdefault("server", {}).setdefault("timeout", 30)
            config.setdefault("server", {}).setdefault("retry_count", 3)
            config.setdefault("server", {}).setdefault("verify_ssl", False)
            
            config.setdefault("rime", {}).setdefault("config_dir", ".")
            config.setdefault("rime", {}).setdefault("platform", "windows")
            config.setdefault("rime", {}).setdefault("android_trime_config", "")
            
            config.setdefault("sync", {}).setdefault("device_name", "")
            config.setdefault("sync", {}).setdefault("auto_sync_on_start", False)
            config.setdefault("sync", {}).setdefault("exclude_patterns", [])
            config.setdefault("sync", {}).setdefault("conflict_resolution", "latest")
            
            config.setdefault("logging", {}).setdefault("level", "INFO")
            config.setdefault("logging", {}).setdefault("file", "logs/rime_client.log")
            config.setdefault("logging", {}).setdefault("max_size_mb", 10)
            config.setdefault("logging", {}).setdefault("archive_enabled", True)
            config.setdefault("logging", {}).setdefault("archive_retention_days", 90)
            
            # 如果device_name为空，尝试从installation.yaml读取
            if not config["sync"]["device_name"]:
                config["sync"]["device_name"] = self.get_device_name_from_installation(config)
            
            return config
        except json.JSONDecodeError as e:
            logging.error(f"配置文件格式错误: {e}")
            sys.exit(1)
        except Exception as e:
            logging.error(f"加载配置文件失败: {e}")
            sys.exit(1)
    
    def migrate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """迁移旧格式配置到新格式"""
        # 如果已经有新格式，直接返回
        if "rime" in config and "sync" in config:
            return config
        
        new_config = {"server": {}, "rime": {}, "sync": {}, "logging": {}}
        
        # 迁移server部分
        if "server" in config:
            new_config["server"] = config["server"]
        else:
            new_config["server"] = {"url": "http://localhost:10032", "timeout": 30}
        
        # 迁移rime部分（从paths和device）
        new_config["rime"] = {
            "config_dir": config.get("paths", {}).get("local_rime_dir", "."),
            "platform": "windows",
            "android_trime_config": ""
        }
        
        # 迁移sync部分
        new_config["sync"] = {
            "device_name": config.get("device", {}).get("name", ""),
            "auto_sync_on_start": False,
            "exclude_patterns": config.get("sync", {}).get("exclude_patterns", []),
            "conflict_resolution": config.get("sync", {}).get("conflict_resolution", "latest")
        }
        
        # 迁移logging部分
        if "logging" in config:
            new_config["logging"] = config["logging"]
        else:
            new_config["logging"] = {
                "level": "INFO",
                "file": "logs/rime_client.log",
                "max_size_mb": 10,
                "archive_enabled": True,
                "archive_retention_days": 90
            }
        
        return new_config
    
    def create_default_config(self):
        """创建默认配置文件"""
        default_config = {
            "server": {
                "url": "http://localhost:10032",
                "timeout": 30,
                "retry_count": 3,
                "verify_ssl": False
            },
            "rime": {
                "config_dir": ".",
                "platform": "windows",
                "android_trime_config": ""
            },
            "sync": {
                "device_name": "",
                "auto_sync_on_start": False,
                "exclude_patterns": [
                    "*.userdb.txt.backup",
                    "*.log",
                    "temp/*",
                    "installation.yaml",
                    ".github/*",
                    "build/*",
                    "rime_ice.userdb"
                ],
                "conflict_resolution": "latest"
            },
            "logging": {
                "level": "INFO",
                "file": "logs/rime_client.log",
                "max_size_mb": 10,
                "archive_enabled": True,
                "archive_retention_days": 90
            }
        }
        
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        
        logging.info(f"已创建默认配置文件: {self.config_path}")
        logging.info("请编辑配置文件并设置正确的服务器URL和Rime配置目录")
    
    def get_device_name_from_installation(self, config: Dict[str, Any]) -> str:
        """从installation.yaml读取设备名"""
        config_dir = Path(config["rime"]["config_dir"])
        installation_path = config_dir / "installation.yaml"
        
        if not installation_path.exists():
            logging.warning(f"installation.yaml文件不存在: {installation_path}")
            return "unknown"
        
        try:
            with open(installation_path, "r", encoding="utf-8") as f:
                installation_data = yaml.safe_load(f)
            
            device_name = installation_data.get("installation_id")
            if not device_name:
                logging.warning("installation.yaml中没有找到installation_id字段")
                return "unknown"
            
            logging.debug(f"从installation.yaml获取到设备名: {device_name}")
            return device_name
            
        except yaml.YAMLError as e:
            logging.warning(f"解析installation.yaml失败: {e}")
            return "unknown"
        except Exception as e:
            logging.warning(f"读取installation.yaml失败: {e}")
            return "unknown"
    
    def setup_logging(self):
        """配置日志"""
        from logging.handlers import RotatingFileHandler

        log_config = self.config.get("logging", {})
        level = getattr(logging, log_config.get("level", "INFO").upper())
        log_file_str = log_config.get("file", "logs/rime_client.log")
        max_bytes = log_config.get("max_size_mb", 10) * 1024 * 1024
        backup_count = 5

        # 相对于配置文件所在目录解析日志路径
        log_file = (self.config_path.parent / log_file_str).resolve()
        log_dir = log_file.parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # 归档非当天的旧日志
        if log_config.get("archive_enabled", True):
            self._archive_old_logs(log_dir, log_config.get("archive_retention_days", 90))

        # 清除已有 handler，重建
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)

        root.setLevel(level)
        fmt = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

        fh = RotatingFileHandler(
            str(log_file), maxBytes=max_bytes,
            backupCount=backup_count, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)

    def _archive_old_logs(self, log_dir, retention_days):
        """扫描 log_dir 下 mtime 非当天的文件，打包归档。压缩回退链：7z → tar.gz → tar"""
        today = date.today()
        old_files = [
            f for f in log_dir.iterdir()
            if f.is_file()
            and not f.name.startswith(".")
            and datetime.fromtimestamp(f.stat().st_mtime).date() != today
        ]
        if not old_files:
            return

        archive_dir = log_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        archive_path = self._try_compress(old_files, archive_dir, ts)

        if archive_path and archive_path.stat().st_size > 0:
            logging.getLogger(__name__).info(
                f"日志归档完成: {archive_path.name} ({archive_path.stat().st_size / 1024:.1f} KB)"
            )
            for f in old_files:
                try:
                    f.unlink()
                except OSError:
                    pass

        self._cleanup_old_archives(archive_dir, retention_days)

    def _try_compress(self, file_list, archive_dir, timestamp):
        """三步回退：7z 命令行 → tar.gz → 无压缩 tar"""
        import shutil
        import subprocess

        temp_dir = Path(tempfile.gettempdir())
        tar_path = temp_dir / f"rime_client_logs_{timestamp}.tar"

        try:
            with tarfile.open(tar_path, "w") as tar:
                for f in file_list:
                    tar.add(str(f), arcname=f.name)
        except Exception:
            if tar_path.exists():
                tar_path.unlink(missing_ok=True)
            return None

        # 1) 尝试 7z 命令行
        archive_path = archive_dir / f"logs_{timestamp}.tar.7z"
        try:
            result = subprocess.run(
                ["7z", "a", str(archive_path), str(tar_path)],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                tar_path.unlink(missing_ok=True)
                return archive_path
        except Exception:
            pass
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)

        # 2) 回退到 tar.gz
        archive_path = archive_dir / f"logs_{timestamp}.tar.gz"
        try:
            import gzip
            with open(tar_path, "rb") as src, gzip.open(archive_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            tar_path.unlink(missing_ok=True)
            return archive_path
        except Exception:
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)

        # 3) 最终回退：无压缩 tar
        final_path = archive_dir / f"logs_{timestamp}.tar"
        shutil.move(str(tar_path), str(final_path))
        return final_path

    @staticmethod
    def _cleanup_old_archives(archive_dir, retention_days):
        """删除 mtime 超过保留期的归档文件"""
        if not archive_dir.exists():
            return
        cutoff = datetime.now() - timedelta(days=retention_days)
        for f in archive_dir.iterdir():
            if not f.is_file():
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                try:
                    f.unlink()
                    logging.getLogger(__name__).info(f"已删除过期归档: {f.name}")
                except OSError:
                    pass

    def get_device_name(self) -> str:
        """获取当前设备名（优先使用配置文件中的，否则从installation.yaml读取）"""
        device_name = self.config["sync"]["device_name"]
        if not device_name or device_name == "unknown":
            device_name = self.get_device_name_from_installation(self.config)
            # 更新配置
            self.config["sync"]["device_name"] = device_name
        
        return device_name
    
    def make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送HTTP请求并处理响应，支持自动重试"""
        url = f"{self.config['server']['url']}{endpoint}"
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", self.config["server"].get("verify_ssl", False))

        retry_count = self.config["server"].get("retry_count", 3)
        last_error = None

        for attempt in range(1, retry_count + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()

                if response.headers.get("content-type", "").startswith("application/json"):
                    return response.json()
                else:
                    return {"raw": response.content}

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_error = e
                if attempt < retry_count:
                    wait = 2 ** attempt
                    logging.warning(f"请求失败 (尝试 {attempt}/{retry_count})，{wait}秒后重试: {e}")
                    time.sleep(wait)
                    continue
                logging.error(f"请求失败，已达最大重试次数: {url}")
                sys.exit(1)

            except requests.exceptions.HTTPError as e:
                logging.warning(f"HTTP错误: {e}")
                error_msg = str(e)
                status_code = response.status_code
                try:
                    if response.headers.get("content-type", "").startswith("application/json"):
                        error_data = response.json()
                        error_msg = error_data.get('error', str(e))
                except Exception:
                    pass
                return {"success": False, "error": error_msg, "code": status_code}

            except Exception as e:
                logging.error(f"请求失败: {e}")
                sys.exit(1)
    
    def get_server_status(self) -> Dict[str, Any]:
        """获取服务器状态"""
        logging.info("获取服务器状态...")
        result = self.make_request("GET", "/api/status")
        
        if result.get("success"):
            data = result.get("data", {})
            logging.info(f"服务器版本: {data.get('version', '未知')}")
            logging.info(f"rime-ice版本: {data.get('rime_ice_version', '未知')}")
            logging.info(f"运行时间: {data.get('uptime', '未知')}")
            logging.info(f"存储使用: {data.get('storage_usage', '未知')}")
            return data
        else:
            logging.error("获取服务器状态失败")
            sys.exit(1)
    
    def sync_dicts(self, category: Optional[str] = None, since: Optional[str] = None):
        """同步词库文件"""
        logging.info("同步词库文件...")

        # 下载词库tar
        params = {}
        if category:
            params["category"] = category
        if since:
            params["since"] = since

        result = self.make_request("GET", "/api/dict/get/tar", params=params)

        if "raw" in result:
            tar_content = result["raw"]
            # 保存tar文件
            config_dir = Path(self.config["rime"]["config_dir"])
            tar_path = config_dir / "dicts_update.tar"
            with open(tar_path, "wb") as f:
                f.write(tar_content)
            logging.info(f"词库tar已下载: {tar_path}")

            # 解压tar到本地目录
            extracted_files = self.extract_dicts_tar(tar_path, config_dir)
            logging.info(f"解压完成，共 {len(extracted_files)} 个文件")

            # 删除临时tar文件
            tar_path.unlink(missing_ok=True)
            logging.info("临时tar文件已删除")

            return extracted_files
        else:
            logging.error("下载词库失败")
            sys.exit(1)
    
    @staticmethod
    def _safe_tar_member_path(member: tarfile.TarInfo, extract_dir: Path) -> Path:
        """安全解析tar成员的目标路径，防止路径遍历攻击"""
        target_path = (extract_dir / member.name).resolve()
        extract_dir_resolved = extract_dir.resolve()
        if not str(target_path).startswith(str(extract_dir_resolved) + os.sep) and target_path != extract_dir_resolved:
            raise ValueError(f"拒绝解压: 路径遍历攻击 {member.name}")
        return target_path

    def extract_dicts_tar(self, tar_path: Path, extract_dir: Path) -> list:
        """解压词库tar文件到本地目录"""
        extracted_files = []

        try:
            with tarfile.open(tar_path, "r") as tar_ref:
                for member in tar_ref.getmembers():
                    if member.isfile():
                        target_path = self._safe_tar_member_path(member, extract_dir)
                        target_path.parent.mkdir(parents=True, exist_ok=True)

                        with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                            target.write(source.read())

                        extracted_files.append(str(target_path))
                        logging.debug(f"解压文件: {member.name} -> {target_path}")

                logging.info(f"从tar解压了 {len(extracted_files)} 个文件")
                return extracted_files

        except tarfile.ReadError:
            logging.error(f"tar文件损坏: {tar_path}")
            sys.exit(1)
        except ValueError as e:
            logging.error(f"安全错误: {e}")
            sys.exit(1)
        except Exception as e:
            logging.error(f"解压tar文件失败: {e}")
            sys.exit(1)

    def extract_full_sync_tar(self, tar_path: Path, extract_dir: Path) -> list:
        """解压完整同步tar文件到本地目录"""
        extracted_files = []

        try:
            with tarfile.open(tar_path, "r") as tar_ref:
                for member in tar_ref.getmembers():
                    if member.isfile():
                        target_path = self._safe_tar_member_path(member, extract_dir)
                        target_path.parent.mkdir(parents=True, exist_ok=True)

                        with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                            target.write(source.read())

                        extracted_files.append(str(target_path))
                        logging.debug(f"解压文件: {member.name} -> {target_path}")

                logging.info(f"从tar解压了 {len(extracted_files)} 个文件")
                return extracted_files

        except tarfile.ReadError:
            logging.error(f"tar文件损坏: {tar_path}")
            sys.exit(1)
        except ValueError as e:
            logging.error(f"安全错误: {e}")
            sys.exit(1)
        except Exception as e:
            logging.error(f"解压tar文件失败: {e}")
            sys.exit(1)

    @staticmethod
    def _stop_weasel() -> Optional[str]:
        """Windows: 停止小狼毫算法服务，返回进程路径供重启使用"""
        import subprocess
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-Process WeaselServer -ErrorAction SilentlyContinue).Path"],
                capture_output=True, text=True, timeout=10
            )
            weasel_path = result.stdout.strip()
            subprocess.run(["taskkill", "/f", "/im", "WeaselServer.exe"],
                           capture_output=True, timeout=10)
            logging.info("已停止 WeaselServer.exe（避免完整同步时文件锁定）")
            return weasel_path if weasel_path else None
        except Exception as e:
            logging.warning(f"停止 WeaselServer.exe 失败: {e}")
            return None

    @staticmethod
    def _start_weasel(weasel_path: Optional[str] = None):
        """Windows: 重启小狼毫算法服务"""
        import subprocess
        import glob as glob_mod
        try:
            exe = weasel_path
            if not exe or not Path(exe).exists():
                for base in [os.environ.get("ProgramFiles", "C:\\Program Files"),
                             os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")]:
                    pattern = os.path.join(base, "Rime", "weasel-*", "WeaselServer.exe")
                    matches = sorted(glob_mod.glob(pattern), reverse=True)
                    if matches:
                        exe = matches[0]
                        break
            if exe and Path(exe).exists():
                subprocess.Popen([exe], creationflags=0x08000000)  # CREATE_NO_WINDOW
                logging.info("已重启 WeaselServer.exe")
            else:
                logging.warning("未找到 WeaselServer.exe，请手动切换输入法以重启服务")
        except Exception as e:
            logging.warning(f"重启 WeaselServer.exe 失败: {e}，请手动切换输入法")

    def create_sync_tar(self, device_name: str) -> Path:
        """创建sync/{device_name}文件夹的tar包"""
        config_dir = Path(self.config["rime"]["config_dir"])
        sync_dir = config_dir / "sync" / device_name

        if not sync_dir.exists():
            logging.error(f"sync文件夹不存在: {sync_dir}")
            logging.info(f"请确保 {sync_dir} 目录存在并包含用户词库文件")
            sys.exit(1)

        # 创建临时tar文件
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        tar_path = temp_dir / f"sync_{device_name}_{int(time.time())}.tar"

        try:
            with tarfile.open(tar_path, "w") as tarf:
                # 遍历sync/{device_name}目录下的所有文件
                for file_path in sync_dir.rglob("*"):
                    if file_path.is_file():
                        # 计算相对路径（相对于sync_dir）
                        relative_path = file_path.relative_to(sync_dir)
                        # 添加到tar中，保持目录结构
                        tarf.add(file_path, arcname=relative_path)
                        logging.debug(f"添加到tar: {relative_path}")

            logging.info(f"创建tar包: {tar_path} (包含 {sync_dir} 目录内容)")
            return tar_path

        except Exception as e:
            logging.error(f"创建tar包失败: {e}")
            if tar_path.exists():
                tar_path.unlink(missing_ok=True)
            sys.exit(1)
    
    def extract_sync_tar(self, tar_path: Path, extract_dir: Path) -> list:
        """解压同步tar文件到sync目录"""
        extracted_files = []

        try:
            with tarfile.open(tar_path, "r") as tar_ref:
                for member in tar_ref.getmembers():
                    if member.isfile():
                        target_path = self._safe_tar_member_path(member, extract_dir)
                        target_path.parent.mkdir(parents=True, exist_ok=True)

                        with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                            target.write(source.read())

                        extracted_files.append(str(target_path))
                        logging.debug(f"解压文件: {member.name} -> {target_path}")

                logging.info(f"从tar解压了 {len(extracted_files)} 个文件到 {extract_dir}")
                return extracted_files

        except tarfile.ReadError:
            logging.error(f"tar文件损坏: {tar_path}")
            sys.exit(1)
        except ValueError as e:
            logging.error(f"安全错误: {e}")
            sys.exit(1)
        except Exception as e:
            logging.error(f"解压tar文件失败: {e}")
            sys.exit(1)
    
    def sync_userdb(self, action: str = "upload", file_name: Optional[str] = None):
        """同步用户输入词库
        上传：读取installation.yaml获取设备名，打包sync/{设备名}/文件夹上传
        下载：获取其他设备的tar包并解压到sync/{其他设备名}/目录
        """
        # 获取设备名（优先从installation.yaml读取）
        device_name = self.get_device_name()
        config_dir = Path(self.config["rime"]["config_dir"])
        sync_dir = config_dir / "sync"
        device_sync_dir = sync_dir / device_name
        
        if action == "download":
            if file_name:
                # 下载单个文件（保留此功能，但主要使用tar下载）
                logging.info(f"下载用户词库文件: {file_name}")
                endpoint = f"/api/sync/get/{device_name}/file/{file_name}"
                result = self.make_request("GET", endpoint)
                
                if "raw" in result:
                    # 保存文件到sync/{设备名}目录
                    local_path = device_sync_dir / file_name
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(result["raw"])
                    logging.info(f"文件已保存: {local_path}")
                else:
                    logging.error("下载文件失败")
                    sys.exit(1)
            else:
                # 下载其他设备的用户词库
                logging.info(f"下载其他设备的用户词库（当前设备: {device_name}）...")
                
                # 获取所有设备列表
                all_devices = self.get_device_names()
                if not all_devices:
                    logging.warning("未找到任何设备，尝试从服务器获取同步信息...")
                    # 尝试通过sync/info获取设备列表
                    sync_info = self.get_sync_info()
                    all_devices = [dev.get('name') for dev in sync_info.get('devices', []) if dev.get('name')]
                
                if not all_devices:
                    logging.error("无法获取设备列表")
                    sys.exit(1)
                
                # 过滤掉当前设备
                other_devices = [d for d in all_devices if d != device_name]
                
                if not other_devices:
                    logging.info("没有其他设备需要同步")
                    return
                
                logging.info(f"发现 {len(other_devices)} 个其他设备: {', '.join(other_devices)}")
                
                # 为每个其他设备下载tar包
                for other_device in other_devices:
                    try:
                        logging.info(f"下载设备 {other_device} 的用户词库...")
                        endpoint = f"/api/sync/get/{other_device}/tar"
                        result = self.make_request("GET", endpoint)

                        if "raw" in result:
                            # 创建临时tar文件
                            temp_dir = Path(tempfile.gettempdir())
                            tar_path = temp_dir / f"sync_download_{other_device}_{int(time.time())}.tar"

                            with open(tar_path, "wb") as f:
                                f.write(result["raw"])
                            logging.info(f"设备 {other_device} 的用户词库tar已下载: {tar_path}")

                            # 解压tar文件到sync/{设备名}目录
                            other_sync_dir = sync_dir / other_device
                            extracted_files = self.extract_sync_tar(tar_path, other_sync_dir)
                            logging.info(f"设备 {other_device} 的用户词库解压完成，共 {len(extracted_files)} 个文件到 {other_sync_dir}")

                            # 删除临时tar文件
                            tar_path.unlink(missing_ok=True)
                            logging.debug(f"临时tar文件已删除: {tar_path}")
                        else:
                            logging.warning(f"下载设备 {other_device} 的用户词库tar失败，跳过此设备")
                    except Exception as e:
                        logging.warning(f"处理设备 {other_device} 时出错: {e}，跳过此设备")
                        continue

                logging.info("所有其他设备的用户词库下载完成")

        elif action == "upload":
            # 自动打包sync/{device_name}文件夹上传
            logging.info(f"上传用户词库（设备: {device_name}）...")

            # 创建tar包
            tar_path = self.create_sync_tar(device_name)

            try:
                # 上传tar文件
                with open(tar_path, 'rb') as f:
                    files = {'file': (f"sync_{device_name}.tar", f, 'application/x-tar')}
                    data = {'device': device_name}

                    result = self.make_request("POST", "/api/sync/upload/tar", files=files, data=data)

                    if result.get("success"):
                        data = result.get("data", {})
                        logging.info(f"上传成功: {data}")
                    else:
                        logging.error("上传失败")
                        sys.exit(1)
            finally:
                # 删除临时tar文件
                if tar_path.exists():
                    tar_path.unlink(missing_ok=True)
                    logging.debug(f"临时tar文件已删除: {tar_path}")
                        
        else:
            logging.error(f"未知操作: {action}")
            sys.exit(1)
    
    def update_rime_ice(self, force: bool = False):
        """请求服务器更新rime-ice仓库"""
        logging.info("请求更新rime-ice仓库...")
        
        data = {"force": force}
        result = self.make_request("POST", "/api/rime_ice/update", json=data)
        
        if result.get("success"):
            data = result.get("data", {})
            if data.get("upgraded"):
                logging.info(f"rime-ice已更新: {data.get('message', '成功')}")
                logging.info(f"变更文件: {data.get('changed_files', [])}")
                self.make_request("POST", '/api/rime_ice/copy_to_runtime')
            else:
                logging.info(f"rime-ice已是最新: {data.get('message', '无更新')}")
            return data
        else:
            logging.error("更新rime-ice失败")
            sys.exit(1)
    
    def run_dict_script(self, script_name: str, version: str, extra_params: Optional[Dict] = None):
        """请求服务器运行自定义词库生成脚本"""
        logging.info(f"运行词库生成脚本: {script_name}")
        
        data = {"version": version}
        if extra_params:
            data["extra_params"] = extra_params
            
        result = self.make_request("POST", f"/api/makedict/run/{script_name}", json=data)
        
        if result.get("success"):
            data = result.get("data", {})
            output_files = data.get('output_files', [])
            total_size = data.get('total_size', 0)
            if output_files:
                logging.info(f"脚本执行成功: {', '.join(output_files)}")
            else:
                logging.info("脚本执行成功: 未知文件")
            logging.info(f"生成大小: {total_size} 字节")
            return data
        else:
            logging.error("运行脚本失败")
            sys.exit(1)
    
    def get_dict_info(self, category: Optional[str] = None, since: Optional[str] = None):
        """获取词库文件信息"""
        logging.info("获取词库信息...")
        
        params = {}
        if category:
            params["category"] = category
        if since:
            params["since"] = since
            
        result = self.make_request("GET", "/api/dict/info", params=params)
        
        if result.get("success"):
            data = result.get("data", {})
            categories = data.get("categories", {})
            
            for cat, files in categories.items():
                logging.info(f"词库类别: {cat}")
                logging.info(f"  文件数: {len(files)}")
                
                total_size = 0
                for file_info in files:
                    total_size += file_info.get("size", 0)
                
                logging.info(f"  总大小: {total_size} 字节")
                
                # 显示前5个文件（如果有的话）
                for i, file_info in enumerate(files[:5]):
                    logging.info(f"    文件{i+1}: {file_info.get('path')} ({file_info.get('size', 0)} 字节)")
                
                if len(files) > 5:
                    logging.info(f"    ... 还有 {len(files) - 5} 个文件")
            
            logging.info(f"所有词库总大小: {data.get('total_size', 0)} 字节")
            logging.info(f"时间戳: {data.get('timestamp', '未知')}")
            return data
        else:
            logging.error("获取词库信息失败")
            sys.exit(1)
    
    def get_device_list(self):
        """获取设备列表"""
        logging.info("获取设备列表...")
        
        result = self.make_request("GET", "/api/device/list")
        
        if result.get("success"):
            data = result.get("data", {})
            devices = data.get("devices", [])
            
            logging.info(f"发现 {len(devices)} 个设备:")
            for device in devices:
                # 处理两种可能的设备格式：字符串或字典
                if isinstance(device, str):
                    # 设备名为字符串
                    logging.info(f"  设备: {device}")
                    logging.info(f"    详细信息: 使用 sync-info 命令查看详情")
                elif isinstance(device, dict):
                    # 设备信息为字典
                    logging.info(f"  设备: {device.get('name', '未知')}")
                    logging.info(f"    最后同步: {device.get('last_sync', '未知')}")
                    logging.info(f"    文件数: {device.get('total_files', 0)}")
                    logging.info(f"    总大小: {device.get('total_size', 0)} 字节")
                else:
                    logging.info(f"  设备: {device} (未知格式)")
            return data
        else:
            logging.error("获取设备列表失败")
            sys.exit(1)
    
    def get_device_names(self) -> List[str]:
        """获取所有设备名称列表"""
        result = self.make_request("GET", "/api/device/list")
        
        if not result.get("success"):
            return []
        
        data = result.get("data", {})
        devices = data.get("devices", [])
        device_names = []
        
        for device in devices:
            if isinstance(device, str):
                device_names.append(device)
            elif isinstance(device, dict):
                name = device.get('name')
                if name:
                    device_names.append(name)
        
        return device_names
    
    def edit_file(self, path: str, line: int, content: str, action: str = "insert"):
        """编辑配置文件"""
        logging.info(f"编辑文件: {path}")
        
        data = {
            "path": path,
            "line": line,
            "content": content,
            "action": action
        }
        
        result = self.make_request("POST", "/api/file/edit", json=data)
        
        if result.get("success"):
            data = result.get("data", {})
            logging.info(f"文件编辑成功: {data}")
            return data
        else:
            logging.error("编辑文件失败")
            sys.exit(1)
    
    def upload_config(self, file_path: str, device: Optional[str] = None, overwrite: bool = False):
        """上传配置文件 (*.custom.yaml)"""
        upload_path = Path(file_path)
        if not upload_path.exists():
            logging.error(f"上传文件不存在: {upload_path}")
            sys.exit(1)
        
        logging.info(f"上传配置文件: {upload_path}")
        
        # 如果没有指定设备，使用当前设备名
        if not device:
            device = self.get_device_name()
        
        files = {'file': (upload_path.name, open(upload_path, 'rb'), 'application/octet-stream')}
        data = {
            'device': device,
            'overwrite': str(overwrite).lower()
        }
        
        try:
            result = self.make_request("POST", "/api/config/upload", files=files, data=data)
            
            if result.get("success"):
                data = result.get("data", {})
                logging.info(f"配置文件上传成功: {data}")
                return data
            else:
                logging.error("上传配置文件失败")
                sys.exit(1)
        finally:
            # 确保文件被关闭
            for file_info in files.values():
                if hasattr(file_info[1], 'close'):
                    file_info[1].close()
    
    def check_health(self):
        """健康检查"""
        logging.info("执行健康检查...")
        
        result = self.make_request("GET", "/api/health")
        
        if result.get("success"):
            data = result.get("data", {})
            logging.info(f"健康检查通过: {data}")
            return data
        else:
            # 如果服务器未实现/health端点，尝试/status作为备选
            logging.warning("/api/health端点可能未实现，尝试使用/status...")
            return self.get_server_status()
    
    def check_server_connection(self) -> bool:
        """检查服务器连接"""
        try:
            result = self.make_request("GET", "/api/status")
            return result.get("success", False)
        except:
            return False
    
    def sync_upload_tar(self, device: Optional[str] = None):
        """上传用户输入词库tar文件"""
        if not device:
            device = self.get_device_name()

        logging.info(f"上传用户词库tar包（设备: {device}）...")

        # 创建tar包
        tar_path = self.create_sync_tar(device)

        try:
            with open(tar_path, 'rb') as f:
                files = {'file': (f"sync_{device}.tar", f, 'application/x-tar')}
                data = {'device': device}

                result = self.make_request("POST", "/api/sync/upload/tar", files=files, data=data)

                if result.get("success"):
                    data = result.get("data", {})
                    logging.info(f"tar上传成功: {data}")
                    return data
                else:
                    # tar上传失败，回退到逐个文件上传
                    logging.warning(f"tar上传失败: {result.get('error', '未知错误')}")
                    logging.info("回退到逐个文件上传模式...")
                    self.fallback_upload_files(device, tar_path)
                    return {"success": True, "message": "通过逐个文件上传完成"}
        finally:
            # 删除临时tar文件
            if tar_path.exists():
                tar_path.unlink(missing_ok=True)
                logging.debug(f"临时tar文件已删除: {tar_path}")

    def fallback_upload_files(self, device: str, tar_path: Path):
        """回退到逐个文件上传模式"""
        # 解压tar文件到临时目录
        import tempfile
        temp_dir = Path(tempfile.mkdtemp())

        try:
            # 解压tar文件
            with tarfile.open(tar_path, "r") as tar_ref:
                tar_ref.extractall(path=temp_dir, filter='data')

            # 获取所有文件
            file_paths = list(temp_dir.rglob("*"))
            file_paths = [f for f in file_paths if f.is_file()]

            if not file_paths:
                logging.warning("tar文件中没有文件可上传")
                return

            logging.info(f"开始逐个上传 {len(file_paths)} 个文件...")

            success_count = 0
            fail_count = 0

            for file_path in file_paths:
                try:
                    # 计算相对路径（相对于临时目录）
                    relative_path = file_path.relative_to(temp_dir)
                    # 使用sync_upload_file方法上传
                    self.sync_upload_file(str(file_path), str(relative_path), device)
                    success_count += 1
                except Exception as e:
                    logging.warning(f"上传文件 {relative_path} 失败: {e}")
                    fail_count += 1
                    continue

            logging.info(f"逐个文件上传完成: {success_count} 成功, {fail_count} 失败")

        except Exception as e:
            logging.error(f"回退上传过程中出错: {e}")
            raise
        finally:
            # 清理临时目录
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def sync_upload_file(self, file_path: str, filename: Optional[str] = None, device: Optional[str] = None):
        """上传用户输入词库单个文件"""
        if not device:
            device = self.get_device_name()
        
        upload_path = Path(file_path)
        if not upload_path.exists():
            logging.error(f"上传文件不存在: {upload_path}")
            sys.exit(1)
        
        if not filename:
            filename = upload_path.name
        
        logging.info(f"上传用户词库文件: {filename}（设备: {device}）...")
        
        with open(upload_path, 'rb') as f:
            files = {'file': (filename, f, 'application/octet-stream')}
            data = {
                'device': device,
                'filename': filename
            }
            
            result = self.make_request("POST", "/api/sync/upload/file", files=files, data=data)
            
            if result.get("success"):
                data = result.get("data", {})
                logging.info(f"上传成功: {data}")
                return data
            else:
                logging.error("上传失败")
                sys.exit(1)
    
    def get_sync_info(self, device: Optional[str] = None, since: Optional[str] = None):
        """获取用户输入词库信息"""
        logging.info("获取同步信息...")
        
        params = {}
        if device:
            params["device"] = device
        if since:
            params["since"] = since
            
        result = self.make_request("GET", "/api/sync/info", params=params)
        
        if result.get("success"):
            data = result.get("data", {})
            devices = data.get("devices", [])
            
            for dev in devices:
                logging.info(f"设备: {dev.get('name')}")
                logging.info(f"  文件数: {len(dev.get('files', []))}")
                logging.info(f"  总大小: {dev.get('total_size', 0)} 字节")
                logging.info(f"  最后同步: {dev.get('timestamp', '未知')}")
            return data
        else:
            logging.error("获取同步信息失败")
            sys.exit(1)
    
    def sync_download_tar(self, device: Optional[str] = None, since: Optional[str] = None):
        """下载用户输入词库tar包"""
        if not device:
            device = self.get_device_name()

        logging.info(f"下载用户词库tar包（设备: {device}）...")

        params = {}
        if since:
            params["since"] = since

        endpoint = f"/api/sync/get/{device}/tar"
        result = self.make_request("GET", endpoint, params=params)

        if "raw" in result:
            # 创建临时tar文件
            temp_dir = Path(tempfile.gettempdir())
            tar_path = temp_dir / f"sync_download_{device}_{int(time.time())}.tar"

            with open(tar_path, "wb") as f:
                f.write(result["raw"])
            logging.info(f"用户词库tar已下载: {tar_path}")

            # 解压tar文件到sync/{设备名}目录
            config_dir = Path(self.config["rime"]["config_dir"])
            sync_dir = config_dir / "sync" / device
            extracted_files = self.extract_sync_tar(tar_path, sync_dir)
            logging.info(f"用户词库解压完成，共 {len(extracted_files)} 个文件到 {sync_dir}")

            # 删除临时tar文件
            tar_path.unlink(missing_ok=True)
            logging.info("临时tar文件已删除")

            return extracted_files
        else:
            logging.error("下载用户词库tar失败")
            sys.exit(1)
    
    def sync_download_file(self, filename: str, device: Optional[str] = None):
        """下载用户输入词库单个文件"""
        if not device:
            device = self.get_device_name()
        
        logging.info(f"下载用户词库文件: {filename}（设备: {device}）...")
        
        endpoint = f"/api/sync/get/{device}/file/{filename}"
        result = self.make_request("GET", endpoint)
        
        if "raw" in result:
            # 保存文件到sync/{设备名}目录
            config_dir = Path(self.config["rime"]["config_dir"])
            sync_dir = config_dir / "sync" / device
            sync_dir.mkdir(parents=True, exist_ok=True)
            
            local_path = sync_dir / filename
            with open(local_path, "wb") as f:
                f.write(result["raw"])
            logging.info(f"文件已保存: {local_path}")
            return local_path
        else:
            logging.error("下载文件失败")
            sys.exit(1)
    
    def dict_download_tar(self, category: Optional[str] = None, since: Optional[str] = None):
        """下载词库tar包"""
        logging.info("下载词库tar包...")

        params = {}
        if category:
            params["category"] = category
        if since:
            params["since"] = since

        result = self.make_request("GET", "/api/dict/get/tar", params=params)

        if "raw" in result:
            # 保存tar文件
            config_dir = Path(self.config["rime"]["config_dir"])
            tar_path = config_dir / "dicts_update.tar"
            with open(tar_path, "wb") as f:
                f.write(result["raw"])
            logging.info(f"词库tar已下载: {tar_path}")

            # 解压tar到本地目录
            extracted_files = self.extract_dicts_tar(tar_path, config_dir)
            logging.info(f"解压完成，共 {len(extracted_files)} 个文件")

            # 删除临时tar文件
            tar_path.unlink(missing_ok=True)
            logging.info("临时tar文件已删除")

            return extracted_files
        else:
            logging.error("下载词库失败")
            sys.exit(1)
    
    def dict_download_file(self, filename: str, category: Optional[str] = None):
        """下载单个词库文件"""
        logging.info(f"下载词库文件: {filename}")
        
        params = {}
        if category:
            params["category"] = category
            
        endpoint = f"/api/dict/get/file/{filename}"
        result = self.make_request("GET", endpoint, params=params)
        
        if "raw" in result:
            # 保存文件到相应目录
            config_dir = Path(self.config["rime"]["config_dir"])
            if category == "cn":
                target_dir = config_dir / "cn_dicts"
            elif category == "en":
                target_dir = config_dir / "en_dicts"
            else:
                # 默认保存到config_dir
                target_dir = config_dir
            
            target_dir.mkdir(parents=True, exist_ok=True)
            local_path = target_dir / filename
            
            with open(local_path, "wb") as f:
                f.write(result["raw"])
            logging.info(f"文件已保存: {local_path}")
            return local_path
        else:
            logging.error("下载词库文件失败")
            sys.exit(1)
    
    def get_full_sync_info(self, exclude: Optional[str] = None, since: Optional[str] = None):
        """获取完整配置包文件信息"""
        logging.info("获取完整配置包信息...")
        
        params = {}
        if exclude:
            params["exclude"] = exclude
        if since:
            params["since"] = since
            
        result = self.make_request("GET", "/api/full_sync/info", params=params)
        
        if result.get("success"):
            data = result.get("data", {})
            files = data.get("files", [])
            
            logging.info(f"文件总数: {len(files)}")
            logging.info(f"总大小: {data.get('total_size', 0)} 字节")
            logging.info(f"排除的文件: {data.get('excluded', [])}")
            
            # 显示前10个文件
            for i, file_info in enumerate(files[:10]):
                logging.info(f"  文件{i+1}: {file_info.get('path')} ({file_info.get('size', 0)} 字节)")
            
            if len(files) > 10:
                logging.info(f"  ... 还有 {len(files) - 10} 个文件")
            
            return data
        else:
            logging.error("获取完整配置包信息失败")
            sys.exit(1)
    
    def full_sync_download(self, exclude: Optional[str] = None, since: Optional[str] = None):
        """下载完整配置包"""
        logging.info("下载完整配置包...")

        params = {}
        if exclude:
            params["exclude"] = exclude
        if since:
            params["since"] = since

        result = self.make_request("GET", "/api/full_sync/download", params=params)

        if "raw" in result:
            # 保存tar文件
            config_dir = Path(self.config["rime"]["config_dir"])
            tar_path = config_dir / "full_sync.tar"
            with open(tar_path, "wb") as f:
                f.write(result["raw"])
            logging.info(f"完整配置包已下载: {tar_path}")

            # Windows: 停止小狼毫服务，避免文件锁定导致解压失败
            is_windows = self.config.get("rime", {}).get("platform") == "windows"
            weasel_path = self._stop_weasel() if is_windows else None

            try:
                extracted_files = self.extract_full_sync_tar(tar_path, config_dir)
                logging.info(f"解压完成，共 {len(extracted_files)} 个文件")
            finally:
                if weasel_path is not None:
                    self._start_weasel(weasel_path)

            # 删除临时tar文件
            tar_path.unlink(missing_ok=True)
            logging.info("临时tar文件已删除")

            return extracted_files
        else:
            logging.error("下载完整配置包失败")
            sys.exit(1)
    
    def full_sync_upload(self, file_path: str, overwrite: bool = False):
        """上传完整配置包"""
        upload_path = Path(file_path)
        if not upload_path.exists():
            logging.error(f"上传文件不存在: {upload_path}")
            sys.exit(1)

        logging.info(f"上传完整配置包: {upload_path}")
        logging.warning("此操作会覆盖服务器现有配置，请谨慎操作！")

        with open(upload_path, 'rb') as f:
            files = {'file': (upload_path.name, f, 'application/x-tar')}
            data = {'overwrite': str(overwrite).lower()}

            result = self.make_request("POST", "/api/full_sync/upload", files=files, data=data)

            if result.get("success"):
                data = result.get("data", {})
                logging.info(f"完整配置包上传成功: {data}")
                return data
            else:
                logging.error("上传完整配置包失败")
                sys.exit(1)
    
    def show_interactive_menu(self):
        """显示交互式菜单"""
        while True:
            print("\n" + "="*50)
            print("Rime 客户端 - 交互式菜单")
            print("="*50)

            device_name = self.get_device_name()
            config_dir = self.config["rime"]["config_dir"]
            server_url = self.config["server"]["url"]

            print(f"当前设备: {device_name}")
            print(f"服务器: {server_url}")
            print(f"Rime 配置目录: {config_dir}")

            print("\n检查服务器连接...")
            if self.check_server_connection():
                print("✓ 服务器连接正常")
            else:
                print("✗ 服务器连接失败")

            print("\n请选择操作:")
            print(" 1. 请求服务器更新 rime-ice 仓库")
            print(" 2. 执行自定义词库脚本")
            print(" 3. 同步用户输入词库")
            print(" 4. 同步普通词库 (cn_dicts/en_dicts)")
            print(" 5. 编辑配置文件")
            print(" 6. 完整同步 (下载/上传)")
            print(" 7. 查看同步状态")
            print(" 8. 获取设备列表")
            print(" 9. 健康检查")
            print(" 10. 修改配置")
            print(" 11. 退出")

            try:
                choice = input("\n选择 [1-11]: ").strip()

                if choice == "1":
                    force = input("强制更新? (y/N): ").strip().lower() == 'y'
                    self.update_rime_ice(force)
                elif choice == "2":
                    script_name = input("脚本名称: ").strip()
                    version = input("词库版本: ").strip()
                    self.run_dict_script(script_name, version)
                elif choice == "3":
                    print("同步用户输入词库:")
                    print("  1. 上传 (默认)")
                    print("  2. 下载")
                    sub_choice = input("选择 [1-2] (默认 1): ").strip() or "1"
                    if sub_choice == "1":
                        self.sync_userdb("upload")
                    elif sub_choice == "2":
                        filename = input("文件名 (可选，留空下载tar包): ").strip() or None
                        self.sync_userdb("download", filename)
                elif choice == "4":
                    print("同步普通词库:")
                    print("  1. 中文词库 (cn)")
                    print("  2. 英文词库 (en)")
                    print("  3. 全部词库")
                    sub_choice = input("选择 [1-3] (默认 3): ").strip() or "3"
                    category = None
                    if sub_choice == "1":
                        category = "cn"
                    elif sub_choice == "2":
                        category = "en"
                    self.sync_dicts(category)
                elif choice == "5":
                    path = input("文件路径: ").strip()
                    line = int(input("行号: ").strip())
                    content = input("内容: ").strip()
                    self.edit_file(path, line, content)
                elif choice == "6":
                    print("完整同步:")
                    print("  1. 下载 (从服务器获取)")
                    print("  2. 上传 (初始化服务器)")
                    sub_choice = input("选择 [1-2]: ").strip()
                    if sub_choice == "1":
                        exclude = input("额外排除的文件（逗号分隔，可选）: ").strip() or None
                        since = input("时间戳（可选）: ").strip() or None
                        self.full_sync_download(exclude, since)
                    elif sub_choice == "2":
                        file_path = input("tar文件路径: ").strip()
                        overwrite = input("覆盖服务器配置? (y/N): ").strip().lower() == 'y'
                        self.full_sync_upload(file_path, overwrite)
                elif choice == "7":
                    self.get_sync_info()
                elif choice == "8":
                    self.get_device_list()
                elif choice == "9":
                    self.check_health()
                elif choice == "10":
                    print("修改配置:")
                    print("  1. 查看当前配置")
                    print("  2. 修改服务器URL")
                    print("  3. 修改Rime配置目录")
                    sub_choice = input("选择 [1-3]: ").strip()
                    if sub_choice == "1":
                        import json
                        print(json.dumps(self.config, indent=2, ensure_ascii=False))
                    elif sub_choice == "2":
                        new_url = input(f"新服务器URL (当前: {self.config['server']['url']}): ").strip()
                        if new_url:
                            self.config['server']['url'] = new_url
                            self.save_config()
                    elif sub_choice == "3":
                        new_dir = input(f"新Rime配置目录 (当前: {self.config['rime']['config_dir']}): ").strip()
                        if new_dir:
                            self.config['rime']['config_dir'] = new_dir
                            self.save_config()
                elif choice == "11":
                    print("再见！")
                    break
                else:
                    print("无效选择")

                input("\n按 Enter 键继续...")

            except KeyboardInterrupt:
                print("\n\n操作已取消")
                break
            except Exception as e:
                print(f"\n错误: {e}")
                input("按 Enter 键返回菜单...")
    
    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logging.info(f"配置已保存: {self.config_path}")
        except Exception as e:
            logging.error(f"保存配置失败: {e}")

def main():
    """主函数：解析命令行参数或启动交互式界面"""
    parser = argparse.ArgumentParser(description="Rime 客户端同步工具")
    parser.add_argument("--config", help="配置文件路径", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    # 如果没有提供命令，则进入交互式模式
    subparsers = parser.add_subparsers(dest="command", help="命令", metavar="COMMAND")
    
    # 状态命令
    status_parser = subparsers.add_parser("status", help="获取服务器状态")
    
    # 更新rime-ice命令
    update_parser = subparsers.add_parser("update-rime-ice", help="更新rime-ice仓库")
    update_parser.add_argument("--force", action="store_true", help="强制更新")
    
    # 运行脚本命令
    script_parser = subparsers.add_parser("run-script", help="运行自定义词库脚本")
    script_parser.add_argument("script_name", help="脚本名称")
    script_parser.add_argument("version", help="词库版本")
    script_parser.add_argument("--extra", help="额外参数（JSON格式）")
    
    # 编辑文件命令
    edit_parser = subparsers.add_parser("edit-file", help="编辑配置文件")
    edit_parser.add_argument("path", help="文件路径")
    edit_parser.add_argument("line", type=int, help="行号")
    edit_parser.add_argument("content", help="要插入的内容")
    edit_parser.add_argument("--action", choices=["insert", "replace", "delete"], default="insert", help="编辑操作类型")
    
    # 上传配置命令
    config_upload_parser = subparsers.add_parser("upload-config", help="上传配置文件 (*.custom.yaml)")
    config_upload_parser.add_argument("file", help="配置文件路径")
    config_upload_parser.add_argument("--device", help="设备标识")
    config_upload_parser.add_argument("--overwrite", action="store_true", help="是否覆盖已存在的文件")
    
    # 同步用户词库命令
    userdb_parser = subparsers.add_parser("sync-userdb", help="同步用户输入词库")
    userdb_parser.add_argument("--action", choices=["download", "upload"], default="upload", help="操作类型")
    userdb_parser.add_argument("--file", help="文件名（仅下载单个文件时使用）")
    userdb_parser.add_argument("--device", help="设备标识")
    
    # 同步用户词库tar上传命令
    sync_upload_tar_parser = subparsers.add_parser("sync-upload-tar", help="上传用户输入词库tar包")
    sync_upload_tar_parser.add_argument("--device", help="设备标识")
    
    # 同步用户词库文件上传命令
    sync_upload_file_parser = subparsers.add_parser("sync-upload-file", help="上传用户输入词库单个文件")
    sync_upload_file_parser.add_argument("file", help="文件路径")
    sync_upload_file_parser.add_argument("--filename", help="文件名（可选）")
    sync_upload_file_parser.add_argument("--device", help="设备标识")
    
    # 同步用户词库信息命令
    sync_info_parser = subparsers.add_parser("sync-info", help="获取用户输入词库信息")
    sync_info_parser.add_argument("--device", help="设备标识")
    sync_info_parser.add_argument("--since", help="时间戳（仅返回此时间之后有变动的文件）")
    
    # 同步用户词库下载tar命令
    sync_download_tar_parser = subparsers.add_parser("sync-download-tar", help="下载用户输入词库tar包")
    sync_download_tar_parser.add_argument("--device", help="设备标识")
    sync_download_tar_parser.add_argument("--since", help="时间戳（仅包含此时间之后有变动的文件）")
    
    # 同步用户词库下载文件命令
    sync_download_file_parser = subparsers.add_parser("sync-download-file", help="下载用户输入词库单个文件")
    sync_download_file_parser.add_argument("filename", help="文件名")
    sync_download_file_parser.add_argument("--device", help="设备标识")
    
    # 同步词库命令
    dict_parser = subparsers.add_parser("sync-dict", help="同步词库")
    dict_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")
    dict_parser.add_argument("--since", help="时间戳（仅同步此时间之后的文件）")
    
    # 词库信息命令
    dict_info_parser = subparsers.add_parser("dict-info", help="获取词库信息")
    dict_info_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")
    dict_info_parser.add_argument("--since", help="时间戳（仅返回此时间之后有变动的文件）")
    
    # 词库下载tar命令
    dict_download_tar_parser = subparsers.add_parser("dict-download-tar", help="下载词库tar包")
    dict_download_tar_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")
    dict_download_tar_parser.add_argument("--since", help="时间戳（仅包含此时间之后有变动的文件）")
    
    # 词库下载文件命令
    dict_download_file_parser = subparsers.add_parser("dict-download-file", help="下载单个词库文件")
    dict_download_file_parser.add_argument("filename", help="文件名")
    dict_download_file_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")
    
    # 完整同步信息命令
    full_sync_info_parser = subparsers.add_parser("full-sync-info", help="获取完整配置包信息")
    full_sync_info_parser.add_argument("--exclude", help="额外排除的文件（逗号分隔）")
    full_sync_info_parser.add_argument("--since", help="时间戳（仅返回此时间之后有变动的文件）")
    
    # 完整同步下载命令
    full_sync_download_parser = subparsers.add_parser("full-sync-download", help="下载完整配置包")
    full_sync_download_parser.add_argument("--exclude", help="额外排除的文件（逗号分隔）")
    full_sync_download_parser.add_argument("--since", help="时间戳（仅包含此时间之后有变动的文件）")
    
    # 完整同步上传命令
    full_sync_upload_parser = subparsers.add_parser("full-sync-upload", help="上传完整配置包")
    full_sync_upload_parser.add_argument("file", help="tar文件路径")
    full_sync_upload_parser.add_argument("--overwrite", action="store_true", help="是否覆盖现有配置")
    
    # 设备列表命令
    device_parser = subparsers.add_parser("device-list", help="获取设备列表")
    
    # 健康检查命令
    health_parser = subparsers.add_parser("health", help="健康检查")
    
    # 交互式模式命令
    interactive_parser = subparsers.add_parser("interactive", help="启动交互式界面")
    
    args = parser.parse_args()
    
    # 如果没有提供命令，则显示帮助或进入交互式模式
    if not args.command:
        # 检查是否在交互式终端中
        if sys.stdin.isatty() and sys.stdout.isatty():
            # 在交互式终端中，启动交互式界面
            client = RimeClient(Path(args.config))
            client.show_interactive_menu()
        else:
            # 非交互式环境，显示帮助
            parser.print_help()
            sys.exit(1)
    else:
        # 执行命令
        client = RimeClient(Path(args.config))
        
        # 根据命令调用相应方法
        if args.command == "status":
            client.get_server_status()
        elif args.command == "update-rime-ice":
            client.update_rime_ice(args.force)
        elif args.command == "run-script":
            extra_params = json.loads(args.extra) if args.extra else None
            client.run_dict_script(args.script_name, args.version, extra_params)
        elif args.command == "edit-file":
            client.edit_file(args.path, args.line, args.content, args.action)
        elif args.command == "upload-config":
            client.upload_config(args.file, args.device, args.overwrite)
        elif args.command == "sync-userdb":
            client.sync_userdb(args.action, args.file)
        elif args.command == "sync-upload-tar":
            client.sync_upload_tar(args.device)
        elif args.command == "sync-upload-file":
            client.sync_upload_file(args.file, args.filename, args.device)
        elif args.command == "sync-info":
            client.get_sync_info(args.device, args.since)
        elif args.command == "sync-download-tar":
            client.sync_download_tar(args.device, args.since)
        elif args.command == "sync-download-file":
            client.sync_download_file(args.filename, args.device)
        elif args.command == "sync-dict":
            client.sync_dicts(args.category, args.since)
        elif args.command == "dict-info":
            client.get_dict_info(args.category, args.since)
        elif args.command == "dict-download-tar":
            client.dict_download_tar(args.category, args.since)
        elif args.command == "dict-download-file":
            client.dict_download_file(args.filename, args.category)
        elif args.command == "full-sync-info":
            client.get_full_sync_info(args.exclude, args.since)
        elif args.command == "full-sync-download":
            client.full_sync_download(args.exclude, args.since)
        elif args.command == "full-sync-upload":
            client.full_sync_upload(args.file, args.overwrite)
        elif args.command == "device-list":
            client.get_device_list()
        elif args.command == "health":
            client.check_health()
        elif args.command == "interactive":
            client.show_interactive_menu()
        else:
            parser.print_help()
            sys.exit(1)

if __name__ == "__main__":
    main()