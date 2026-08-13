import re
import logging
from pathlib import Path

from flask import request

from utils.config_loader import config_manager
from utils.error_handler import success_response, error_response

logger = logging.getLogger(__name__)

_INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f/:\\*?"<>|]')


def safe_filename(filename):
    """清理文件名：保留中文等Unicode字符，仅替换路径分隔符和非法字符。"""
    if not filename:
        return ""
    name = Path(filename).name
    name = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    if not name or name == "..":
        return ""
    return name

def handle_config_upload(request):
    """
    处理配置文件上传
    
    支持上传 *.custom.yaml 文件到 runtime 目录
    """
    # 检查是否有文件部分
    if 'file' not in request.files:
        return error_response("没有上传文件", 400)
    
    file = request.files['file']
    
    # 检查文件名
    if file.filename == '':
        return error_response("没有选择文件", 400)
    
    # 安全处理文件名（保留中文等Unicode字符）
    filename = safe_filename(file.filename)
    if not filename:
        return error_response("无效的文件名", 400)
    
    # 检查文件扩展名
    allowed_extensions = config_manager.get("server", "server.allowed_extensions", [])
    if allowed_extensions and not any(filename.endswith(ext) for ext in allowed_extensions):
        return error_response(f"文件类型不允许，允许的扩展名: {', '.join(allowed_extensions)}", 400)
    
    # 检查是否是 .custom.yaml 文件
    if not filename.endswith('.custom.yaml'):
        logger.warning(f"上传的文件不是 .custom.yaml: {filename}")
        # 仍然允许上传，但记录警告
    
    # 获取设备标识
    device = request.form.get('device', 'unknown')
    overwrite = request.form.get('overwrite', 'false').lower() == 'true'
    
    # 检查设备类型（如果是slave则拒绝上传）
    try:
        devices_config = config_manager.get("devices", "devices", {})
        if device in devices_config:
            device_type = devices_config[device].get("type")
            if device_type == "slave":
                logger.warning(f"设备 {device} 是从机，拒绝配置文件上传")
                return error_response(f"设备 {device} 是从机，配置文件上传需要主机确认", 403)
    except Exception as e:
        logger.warning(f"检查设备类型失败: {e}，继续上传")
    
    # 确定保存路径
    runtime_path = Path(config_manager.resolve_path(config_manager.get("server", "paths.runtime")))
    save_path = runtime_path / filename
    
    # 安全检查：确保保存路径在runtime目录内
    if not save_path.resolve().is_relative_to(runtime_path.resolve()):
        logger.error(f"路径遍历攻击尝试: {filename}")
        return error_response("无效的文件名", 400)
    
    # 检查文件是否已存在
    file_existed = save_path.exists()
    if file_existed and not overwrite:
        return error_response("文件已存在，使用 overwrite=true 覆盖", 409)
    
    # 确保目录存在
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # 保存文件
        file.save(str(save_path))
        
        # 获取文件信息
        file_size = save_path.stat().st_size
        
        logger.info(f"配置文件上传成功: {filename}, 设备: {device}, 大小: {file_size}字节")
        
        return success_response({
            "filename": filename,
            "size": file_size,
            "saved_path": str(save_path.relative_to(runtime_path)),
            "device": device,
            "overwritten": file_existed
        }, "配置文件上传成功")
        
    except Exception as e:
        logger.error(f"文件上传失败: {filename}, 错误: {e}")
        return error_response(f"文件上传失败: {str(e)}", 500)