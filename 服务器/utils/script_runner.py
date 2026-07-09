import os
import sys
import subprocess
import tempfile
import shutil
import logging
import json
import errno
from pathlib import Path
import time
import signal

from utils.config_loader import config_manager
from utils.error_handler import APIError

logger = logging.getLogger(__name__)

class ScriptRunner:
    def __init__(self):
        self.makedict_path = Path(config_manager.get("server", "paths.makedict"))
        self.runtime_cn_dicts = Path(config_manager.get("dict", "dict.cn_dicts_path"))
        self.max_execution_time = config_manager.get("script", "scripts.max_execution_time", 300)
        self.max_memory_mb = config_manager.get("script", "scripts.max_memory_mb", 512)
        self.allow_network = config_manager.get("script", "scripts.allow_network_access", True)
        self.log_execution = config_manager.get("script", "scripts.log_execution", True)
        self.trusted_users = set(config_manager.get("script", "scripts.trusted_users", []))
        
        # 确保目录存在
        self.makedict_path.mkdir(exist_ok=True)
        self.runtime_cn_dicts.mkdir(parents=True, exist_ok=True)

    def run_script(self, script_name, version, device=None, extra_params=None):
        """
        执行自定义词库生成脚本
        
        参数:
            script_name: 脚本名称（对应makedict下的目录名）
            version: 词库版本
            device: 设备标识（用于权限检查）
            extra_params: 额外参数（字典）
        
        返回:
            执行结果字典
        """
        script_dir = self.makedict_path / script_name
        main_script = script_dir / "main.py"
        
        # 验证脚本目录和主脚本
        if not script_dir.exists():
            logger.error(f"脚本目录不存在: {script_dir}")
            raise APIError(f"脚本 '{script_name}' 不存在", 404)
        
        if not main_script.exists():
            logger.error(f"脚本主文件不存在: {main_script}")
            raise APIError(f"脚本 '{script_name}' 缺少主文件 main.py", 404)
        
        # 权限检查：只有信任的设备可以执行脚本
        if device and self.trusted_users:
            if device not in self.trusted_users:
                logger.warning(f"设备 {device} 不在信任列表中，拒绝执行脚本")
                raise APIError(f"设备 {device} 没有执行脚本的权限", 403)
        
        # 创建临时工作目录
        with tempfile.TemporaryDirectory(prefix=f"rime_makedict_{script_name}_") as temp_dir:
            temp_path = Path(temp_dir)
            
            # 复制脚本目录到临时目录
            temp_script_dir = temp_path / script_name
            shutil.copytree(script_dir, temp_script_dir, dirs_exist_ok=True)
            main_script = temp_script_dir / "main.py"
            
            # 准备参数
            params = {
                "version": version,
                "extra": extra_params or {}
            }
            
            # 构建命令
            logger.info(f"脚本主文件路径: {main_script.resolve()}, 相对路径: {main_script}")
            cmd = [sys.executable, str(main_script), version]
            
            # 添加额外参数（通过环境变量或标准输入）
            env = os.environ.copy()
            if extra_params:
                env["RIME_MAKEDICT_PARAMS"] = json.dumps(extra_params)
            
            # 执行脚本
            logger.info(f"执行脚本: {script_name}, 版本: {version}, 工作目录: {temp_script_dir}")
            
            try:
                # 设置超时
                start_time = time.time()
                
                process = subprocess.Popen(
                    cmd,
                    cwd=temp_script_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    start_new_session=True,  # 创建新进程组，方便超时时清理子树
                )

                try:
                    stdout, stderr = process.communicate(timeout=self.max_execution_time)
                except subprocess.TimeoutExpired:
                    # 超时终止进程（优先杀进程组，Windows 下回退到 process.kill）
                    try:
                        if hasattr(os, 'killpg') and hasattr(signal, 'SIGTERM'):
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            process.wait(timeout=5)
                        else:
                            process.kill()
                    except Exception:
                        process.kill()
                    stdout, stderr = process.communicate()
                    logger.error(f"脚本执行超时: {script_name}, 超时时间: {self.max_execution_time}秒")
                    raise APIError(f"脚本执行超时（超过{self.max_execution_time}秒）", 408)
                
                execution_time = time.time() - start_time
                
                # 检查退出码
                if process.returncode != 0:
                    logger.error(f"脚本执行失败: {script_name}, 退出码: {process.returncode}")
                    logger.error(f"标准错误: {stderr[:500]}")
                    raise APIError(f"脚本执行失败: {stderr[:200]}", 500)
                
                # 查找生成的词库文件（递归搜索子目录）
                dict_files = list(temp_path.rglob("*.dict.yaml"))
                if not dict_files:
                    logger.error(f"脚本未生成词库文件: {script_name}")
                    raise APIError("脚本未生成词库文件（*.dict.yaml）", 500)
                
                # 将生成的词库文件移动到runtime/cn_dicts/
                moved_files = []
                total_size = 0
                for dict_file in dict_files:
                    target_file = self.runtime_cn_dicts / dict_file.name

                    file_size = dict_file.stat().st_size
                    total_size += file_size

                    try:
                        # 尝试使用shutil.move（如果同设备会更快）
                        shutil.move(str(dict_file), str(target_file))
                    except OSError as e:
                        # 跨设备 move 失败时，退化为 copy + delete
                        if e.errno == errno.EXDEV or getattr(e, 'winerror', None) == 17:
                            logger.debug(f"跨设备移动，使用复制+删除: {dict_file} -> {target_file}")
                            shutil.copy2(str(dict_file), str(target_file))
                            dict_file.unlink()
                        else:
                            raise

                    moved_files.append({"name": dict_file.name, "size": file_size})

                    logger.info(f"词库文件已移动: {dict_file.name} -> {target_file}")

                # 记录执行日志
                if self.log_execution:
                    logger.info(f"脚本执行成功: {script_name}, 版本: {version}, "
                               f"耗时: {execution_time:.2f}秒, "
                               f"生成文件: {', '.join(f['name'] for f in moved_files)}")

                return {
                    "success": True,
                    "script": script_name,
                    "version": version,
                    "execution_time": round(execution_time, 2),
                    "output_files": [f["name"] for f in moved_files],
                    "output_files_detail": moved_files,
                    "total_size": total_size,
                    "stdout": stdout[:1000],
                    "stderr": stderr[:500] if stderr else None,
                    "exit_code": process.returncode
                }
                
            except APIError:
                raise
            except Exception as e:
                logger.error(f"脚本执行异常: {script_name}, 错误: {e}")
                raise APIError(f"脚本执行异常: {str(e)}", 500)

    def list_scripts(self):
        """列出所有可用的脚本"""
        scripts = []
        for item in self.makedict_path.iterdir():
            if item.is_dir():
                main_script = item / "main.py"
                if main_script.exists():
                    scripts.append(item.name)
        
        return sorted(scripts)

script_runner = ScriptRunner()