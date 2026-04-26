from flask import jsonify
import traceback
import logging

logger = logging.getLogger(__name__)

class APIError(Exception):
    def __init__(self, message, code=400, details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details

def success_response(data=None, message="操作成功", code=200):
    response = {
        "success": True,
        "data": data,
        "message": message
    }
    return jsonify(response), code

def error_response(message, code=400, details=None):
    response = {
        "success": False,
        "error": message,
        "code": code
    }
    if details:
        response["details"] = details
    return jsonify(response), code

def handle_api_error(error):
    if isinstance(error, APIError):
        logger.warning(f"API错误: {error.message} (代码: {error.code})")
        return error_response(error.message, error.code, error.details)
    
    logger.error(f"未处理的异常: {str(error)}\n{traceback.format_exc()}")
    return error_response("服务器内部错误", 500)

def register_error_handlers(app):
    app.register_error_handler(APIError, handle_api_error)
    app.register_error_handler(404, lambda e: error_response("资源不存在", 404))
    app.register_error_handler(405, lambda e: error_response("方法不允许", 405))
    app.register_error_handler(500, lambda e: error_response("服务器内部错误", 500))