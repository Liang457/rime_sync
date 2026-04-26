import os
import logging
from pathlib import Path
from werkzeug.utils import secure_filename

from flask import request

from utils.config_loader import config_manager
from utils.error_handler import success_response, error_response, APIError

logger = logging.getLogger(__name__)

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
    
    # 安全处理文件名
    filename = secure_filename(file.filename)
    
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
    runtime_path = Path(config_manager.get("server", "paths.runtime"))
    save_path = runtime_path / filename
    
    # 安全检查：确保保存路径在runtime目录内
    if not save_path.resolve().is_relative_to(runtime_path.resolve()):
        logger.error(f"路径遍历攻击尝试: {filename}")
        return error_response("无效的文件名", 400)
    
    # 检查文件是否已存在
    if save_path.exists() and not overwrite:
        return error_response("文件已存在，使用 overwrite=true 覆盖", 409)
    
    # 确保目录存在
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # 保存文件
        file.save(str(save_path))
        
        # 获取文件信息
        file_size = save_path.stat().st_size
        
        logger.info(f"配置文件上传成功: {filename}, 设备: {device}, 大小: {file_size}字节")
        
        # 更新设备信息（简化）
        update_device_info(device, filename)
        
        return success_response({
            "filename": filename,
            "size": file_size,
            "saved_path": str(save_path.relative_to(runtime_path)),
            "device": device,
            "overwritten": overwrite and save_path.exists()
        }, "配置文件上传成功")
        
    except Exception as e:
        logger.error(f"文件上传失败: {filename}, 错误: {e}")
        return error_response(f"文件上传失败: {str(e)}", 500)

def update_device_info(device, filename):
    """更新设备信息（简化版本）"""
    try:
        # 这里可以更新 devices.json 中的设备信息
        # 简化实现：只记录日志
        logger.debug(f"设备 {device} 上传了配置文件: {filename}")
    except Exception as e:
        logger.warning(f"更新设备信息失败: {e}")

def validate_config_file(filepath):
    """验证配置文件（简化版本）"""
    # 这里可以添加YAML语法验证等
    # 暂时只检查文件是否存在且可读
    path = Path(filepath)
    return path.exists() and path.is_file()