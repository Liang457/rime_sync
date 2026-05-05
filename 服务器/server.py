#!/usr/bin/env python3
"""
rime-server 主程序
树莓派5上的Rime配置同步服务器
"""

import os
import sys
import logging
import shutil
import atexit
import uuid
import tempfile
from datetime import datetime
from pathlib import Path

# 在 import utils 之前配置基础日志，确保 Manager 单例初始化期间的
# warning/error 至少输出到 stderr，不会被静默吞掉
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# 临时 tar 文件缓存目录，避免 send_file 流式传输时的竞态删除问题
TAR_CACHE = Path(tempfile.gettempdir()) / "rime_server_tar_cache"
TAR_CACHE.mkdir(parents=True, exist_ok=True)

def _cleanup_tar_cache():
    """进程退出时清理缓存目录"""
    if TAR_CACHE.exists():
        shutil.rmtree(TAR_CACHE, ignore_errors=True)

atexit.register(_cleanup_tar_cache)

from utils.config_loader import config_manager
from utils.error_handler import (
    success_response, error_response, APIError,
    register_error_handlers
)

def setup_logging():
    from logging.handlers import RotatingFileHandler
    from utils.log_manager import LogManager

    log_level = config_manager.get("server", "server.log_level", "INFO")
    log_file = config_manager.get("server", "server.log_file", "logs/server.log")
    log_max_bytes = config_manager.get("server", "server.log_max_bytes", 10 * 1024 * 1024)
    log_backup_count = config_manager.get("server", "server.log_backup_count", 5)

    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # 归档非当天的旧日志（在创建新 handler 之前）
    archive_enabled = config_manager.get("log_archive", "log_archive.enabled", True)
    retention_days = config_manager.get("log_archive", "log_archive.retention_days", 90)
    if archive_enabled:
        lm = LogManager(log_dir, retention_days)
        lm.archive_old_logs()
        lm.cleanup_old_archives()

    # 清除模块级 bootstrap handler，修复 basicConfig 二次调用无效的 bug
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    root.setLevel(getattr(logging, log_level.upper()))
    fmt = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    fh = RotatingFileHandler(
        str(Path(log_file).resolve()),
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
        encoding='utf-8'
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    logger = logging.getLogger(__name__)
    logger.info(f"日志系统初始化完成，日志级别: {log_level}")
    return logger

def create_app():
    app = Flask(__name__)
    CORS(app)
    
    app.config['MAX_CONTENT_LENGTH'] = (
        config_manager.get("server", "server.max_upload_size_mb", 100) * 1024 * 1024
    )
    
    logger = setup_logging()
    
    register_error_handlers(app)
    
    @app.before_request
    def log_request():
        if request.path != '/api/health':
            logger.info(f"{request.method} {request.path} - {request.remote_addr}")
    
    @app.after_request
    def log_response(response):
        if request.path != '/api/health' and response.status_code >= 400:
            logger.warning(f"响应状态: {response.status_code} - {request.path}")
        return response
    
    @app.route('/')
    def index():
        return success_response({
            "name": "rime-server",
            "version": "1.0",
            "description": "Rime配置同步服务器",
            "docs": "请参考API文档"
        })
    
    @app.route('/api/status', methods=['GET'])
    def api_status():
        from utils.rime_ice_manager import get_rime_ice_version
        version = get_rime_ice_version()
        
        return success_response({
            "version": "1.0",
            "rime_ice_version": version,
            "uptime": "待实现",
            "storage_usage": "待实现"
        })
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        import shutil
        import psutil
        
        disk_usage = shutil.disk_usage("/")
        memory_usage = psutil.virtual_memory()
        
        disk_percent = round((disk_usage.used / disk_usage.total) * 100, 2) if disk_usage.total > 0 else 0
        
        return success_response({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "disk": {
                "total_gb": round(disk_usage.total / (1024**3), 2),
                "used_gb": round(disk_usage.used / (1024**3), 2),
                "free_gb": round(disk_usage.free / (1024**3), 2),
                "percent": disk_percent
            },
            "memory": {
                "total_mb": round(memory_usage.total / (1024**2), 2),
                "available_mb": round(memory_usage.available / (1024**2), 2),
                "percent": memory_usage.percent
            }
        })
    
    @app.route('/api/rime_ice/update', methods=['POST'])
    def update_rime_ice():
        from utils.rime_ice_manager import update_rime_ice_repo
        force = False
        if request.is_json:
            data = request.get_json(silent=True) or {}
            force = data.get('force', False)
        result = update_rime_ice_repo(force=force)
        return success_response(result, "rime-ice更新操作完成")
    
    @app.route('/api/rime_ice/copy_to_runtime', methods=['POST'])
    def copy_to_runtime():
        from utils.rime_ice_manager import copy_to_runtime as copy_runtime
        result = copy_runtime()
        return success_response(result, "已复制rime-ice文件到runtime目录")
    
    @app.route('/api/file/edit', methods=['POST'])
    def edit_file():
        from utils.file_editor import edit_file as edit_file_func
        
        if not request.is_json:
            return error_response("请求必须是JSON格式", 400)
        
        data = request.json
        file_path = data.get('path')
        line = data.get('line')
        content = data.get('content')
        action = data.get('action', 'insert')
        
        if not file_path or line is None or not content:
            return error_response("缺少必要参数: path, line, content", 400)
        
        try:
            line = int(line)
        except ValueError:
            return error_response("line必须是整数", 400)
        
        try:
            result = edit_file_func(file_path, line, content, action)
            return success_response(result, "文件编辑成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/makedict/run/<script_name>', methods=['POST'])
    def run_makedict_script(script_name):
        from utils.script_runner import script_runner

        # 安全检查：script_name 不能包含路径遍历字符
        if not script_name or '..' in script_name or '/' in script_name or '\\' in script_name:
            return error_response("无效的脚本名称", 400)

        if not request.is_json:
            return error_response("请求必须是JSON格式", 400)

        data = request.get_json(silent=True) or {}
        version = data.get('version')
        device = data.get('device')
        extra_params = data.get('extra_params', {})
        
        if not version:
            return error_response("缺少必要参数: version", 400)
        
        try:
            result = script_runner.run_script(script_name, version, device, extra_params)
            return success_response(result, "脚本执行成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/makedict/list', methods=['GET'])
    def list_makedict_scripts():
        from utils.script_runner import script_runner
        scripts = script_runner.list_scripts()
        return success_response({"scripts": scripts}, "脚本列表获取成功")
    
    @app.route('/api/config/upload', methods=['POST'])
    def upload_config():
        from utils.config_uploader import handle_config_upload
        return handle_config_upload(request)
    
    @app.route('/api/sync/upload/tar', methods=['POST'])
    def sync_upload_tar():
        from utils.sync_manager import sync_manager

        if 'file' not in request.files:
            return error_response("没有上传文件", 400)

        file = request.files['file']
        device = request.form.get('device')

        if not device:
            return error_response("缺少设备标识", 400)

        if file.filename == '':
            return error_response("没有选择文件", 400)

        try:
            result = sync_manager.upload_tar(device, file)
            return success_response(result, "tar文件上传成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/sync/upload/file', methods=['POST'])
    def sync_upload_file():
        from utils.sync_manager import sync_manager
        
        if 'file' not in request.files:
            return error_response("没有上传文件", 400)
        
        file = request.files['file']
        device = request.form.get('device')
        filename = request.form.get('filename')
        
        if not device or not filename:
            return error_response("缺少设备标识或文件名", 400)
        
        if file.filename == '':
            return error_response("没有选择文件", 400)
        
        try:
            result = sync_manager.upload_file(device, filename, file)
            return success_response(result, "文件上传成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/sync/info', methods=['GET'])
    def sync_info():
        from utils.sync_manager import sync_manager
        
        device = request.args.get('device')
        since = request.args.get('since')
        
        try:
            if device:
                result = sync_manager.get_file_info(device)
            else:
                # 返回所有设备信息
                devices = sync_manager.list_devices()
                device_infos = []
                for dev in devices:
                    try:
                        info = sync_manager.get_file_info(dev)
                        info['name'] = dev
                        device_infos.append(info)
                    except Exception:
                        continue
                result = {"devices": device_infos}
            
            return success_response(result, "同步信息获取成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/sync/get/<device>/tar', methods=['GET'])
    def sync_get_tar(device):
        from utils.sync_manager import sync_manager
        from flask import send_file

        since = request.args.get('since')
        tar_path = None

        try:
            tar_path = sync_manager.create_tar(device, since)
            cache_name = f"sync_{device}_{uuid.uuid4().hex[:8]}.tar"
            cache_path = TAR_CACHE / cache_name
            shutil.move(str(tar_path), str(cache_path))
            tar_path = cache_path

            response = send_file(
                str(cache_path),
                as_attachment=True,
                download_name=f"{device}_sync.tar",
                mimetype='application/x-tar'
            )
            @response.call_on_close
            def cleanup():
                try:
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception:
                    pass
            return response
        except APIError as e:
            if tar_path is not None and tar_path.exists():
                try:
                    tar_path.unlink()
                except Exception:
                    pass
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/sync/get/<device>/file/<path:filename>', methods=['GET'])
    def sync_get_file(device, filename):
        from utils.sync_manager import sync_manager
        from flask import send_file
        
        try:
            file_path = sync_manager.get_file_content(device, filename)
            return send_file(
                str(file_path),
                as_attachment=True,
                download_name=filename
            )
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/device/list', methods=['GET'])
    def device_list():
        from utils.sync_manager import sync_manager
        
        try:
            devices = sync_manager.get_device_details()
            return success_response({"devices": devices}, "设备列表获取成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/dict/info', methods=['GET'])
    def dict_info():
        from utils.dict_manager import dict_manager
        
        category = request.args.get('category')  # 'cn' 或 'en'
        since = request.args.get('since')
        
        try:
            result = dict_manager.get_dict_info(category, since)
            return success_response(result, "词库信息获取成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/dict/get/tar', methods=['GET'])
    def dict_get_tar():
        from utils.dict_manager import dict_manager
        from flask import send_file

        category = request.args.get('category')
        since = request.args.get('since')
        tar_path = None

        try:
            tar_path = dict_manager.create_tar(category, since)
            cache_name = f"dict_{category or 'all'}_{uuid.uuid4().hex[:8]}.tar"
            cache_path = TAR_CACHE / cache_name
            shutil.move(str(tar_path), str(cache_path))
            tar_path = cache_path

            response = send_file(
                str(cache_path),
                as_attachment=True,
                download_name=f"rime_dicts_{category or 'all'}.tar",
                mimetype='application/x-tar'
            )
            @response.call_on_close
            def cleanup():
                try:
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception:
                    pass
            return response
        except APIError as e:
            if tar_path is not None and tar_path.exists():
                try:
                    tar_path.unlink()
                except Exception:
                    pass
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/dict/get/file/<path:file_name>', methods=['GET'])
    def dict_get_file(file_name):
        from utils.dict_manager import dict_manager
        from flask import send_file
        
        category = request.args.get('category')
        
        try:
            file_path = dict_manager.get_file_content(file_name, category)
            return send_file(
                str(file_path),
                as_attachment=True,
                download_name=file_name
            )
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/full_sync/info', methods=['GET'])
    def full_sync_info():
        from utils.full_sync_manager import full_sync_manager
        
        exclude = request.args.get('exclude')
        since = request.args.get('since')
        
        try:
            result = full_sync_manager.get_file_info(
                exclude_patterns=full_sync_manager.get_exclude_patterns(exclude) if exclude else None,
                since=since
            )
            return success_response(result, "完整配置包信息获取成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/full_sync/download', methods=['GET'])
    def full_sync_download():
        from utils.full_sync_manager import full_sync_manager
        from flask import send_file

        exclude = request.args.get('exclude')
        since = request.args.get('since')
        tar_path = None

        try:
            tar_path = full_sync_manager.create_tar(
                exclude_patterns=full_sync_manager.get_exclude_patterns(exclude) if exclude else None,
                since=since
            )
            cache_name = f"fullsync_{uuid.uuid4().hex[:8]}.tar"
            cache_path = TAR_CACHE / cache_name
            shutil.move(str(tar_path), str(cache_path))
            tar_path = cache_path

            response = send_file(
                str(cache_path),
                as_attachment=True,
                download_name="rime_full_config.tar",
                mimetype='application/x-tar'
            )
            @response.call_on_close
            def cleanup():
                try:
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception:
                    pass
            return response
        except APIError as e:
            if tar_path is not None and tar_path.exists():
                try:
                    tar_path.unlink()
                except Exception:
                    pass
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/full_sync/upload', methods=['POST'])
    def full_sync_upload():
        from utils.full_sync_manager import full_sync_manager

        if 'file' not in request.files:
            return error_response("没有上传文件", 400)

        file = request.files['file']
        overwrite = request.form.get('overwrite', 'false').lower() == 'true'
        hash_value = request.form.get('hash')

        if file.filename == '':
            return error_response("没有选择文件", 400)

        # TODO: 验证哈希值（如果提供）

        try:
            result = full_sync_manager.upload_tar(file, overwrite)
            return success_response(result, "完整配置包上传成功")
        except APIError as e:
            return error_response(e.message, e.code, e.details)
    
    @app.route('/api/config/reload', methods=['POST'])
    def reload_config():
        changed = config_manager.reload()
        message = "配置已重新加载" if changed else "配置无变化"
        return success_response({"changed": changed}, message)
    
    logger.info("Flask应用初始化完成")
    return app, logger

if __name__ == '__main__':
    app, logger = create_app()

    host = config_manager.get("server", "server.host", "0.0.0.0")
    port = config_manager.get("server", "server.port", 10032)
    threads = config_manager.get("server", "server.threads", 4)

    logger.info(f"启动服务器 (waitress): {host}:{port}, threads={threads}")

    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=threads)
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        sys.exit(1)