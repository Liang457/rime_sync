import logging
from pathlib import Path

from utils.config_loader import config_manager
from utils.error_handler import APIError

logger = logging.getLogger(__name__)

def edit_file(file_path, line, content, action="insert"):
    """
    编辑配置文件
    
    参数:
        file_path: 相对于runtime目录的文件路径
        line: 行号（1-based）
        content: 要插入或替换的内容（delete 时可为 None）
        action: 操作类型：insert / replace / delete
    
    返回:
        操作结果字典
    """
    runtime_path = Path(config_manager.resolve_path(config_manager.get("server", "paths.runtime")))
    target_path = (runtime_path / file_path).resolve()
    
    # 安全检查：确保目标路径在runtime目录内
    if not target_path.is_relative_to(runtime_path.resolve()):
        logger.error(f"路径遍历攻击尝试: {file_path}")
        raise APIError("无效的文件路径", 400)
    
    # 确保文件存在
    if not target_path.exists():
        logger.error(f"文件不存在: {target_path}")
        raise APIError("文件不存在", 404)
    
    # 检查文件扩展名是否允许
    allowed_extensions = config_manager.get("server", "server.allowed_extensions", [])
    if allowed_extensions and not any(target_path.name.endswith(ext) for ext in allowed_extensions):
        logger.error(f"文件类型不允许: {target_path.name}")
        raise APIError("文件类型不允许", 400)
    
    # 读取文件内容
    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        logger.error(f"读取文件失败: {target_path}, 错误: {e}")
        raise APIError(f"读取文件失败: {str(e)}", 500)
    
    # 执行编辑操作（各分支校验各自的行号范围）
    if action == "insert":
        if line < 1 or line > len(lines) + 1:
            logger.error(f"行号超出范围: {line}, 文件行数: {len(lines)}")
            raise APIError(f"行号超出范围，有效范围: 1-{len(lines)+1}", 400)
        lines.insert(line - 1, content + '\n')
        operation = "insert"
    elif action == "replace":
        if line < 1 or line > len(lines):
            logger.error(f"替换行号超出范围: {line}, 文件行数: {len(lines)}")
            raise APIError(f"替换行号超出范围，有效范围: 1-{len(lines)}", 400)
        lines[line - 1] = content + '\n'
        operation = "replace"
    elif action == "delete":
        if line < 1 or line > len(lines):
            logger.error(f"删除行号超出范围: {line}, 文件行数: {len(lines)}")
            raise APIError(f"删除行号超出范围，有效范围: 1-{len(lines)}", 400)
        del lines[line - 1]
        operation = "delete"
    else:
        logger.error(f"不支持的操作类型: {action}")
        raise APIError(f"不支持的操作类型: {action}", 400)
    
    # 写入文件
    try:
        with open(target_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    except Exception as e:
        logger.error(f"写入文件失败: {target_path}, 错误: {e}")
        raise APIError(f"写入文件失败: {str(e)}", 500)
    
    logger.info(f"文件编辑成功: {file_path}, 操作: {operation}, 行号: {line}")

    return {
        "success": True,
        "file_path": file_path,
        "operation": operation,
        "line": line,
        "total_lines": len(lines),
        "content_preview": None if content is None else content[:100] + ("..." if len(content) > 100 else "")
    }