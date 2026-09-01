import secrets
import logging

from flask import request

from utils.config_loader import config_manager
from utils.error_handler import error_response

logger = logging.getLogger(__name__)


def authenticate_request():
    """校验请求认证。api_token 为空时保持无认证；配置后所有 /api/* 请求必须携带正确的 X-Api-Token。

    注意：该 token 以明文 HTTP 传输，仅在部署方通过 Nginx 等做 TLS 终结（或置于完全可信的
    局域网）时才算真正的认证，此处主要作为防误触与 CSRF 防护的可选门禁。
    返回 None 表示放行；返回 (response, code) 表示拒绝。
    """
    if not request.path.startswith('/api/'):
        return None
    expected = config_manager.get("server", "server.api_token", "")
    if not expected:
        return None
    provided = request.headers.get("X-Api-Token", "")
    if not secrets.compare_digest(provided, expected):
        return error_response("未授权: X-Api-Token 请求头缺失或不正确", 401)
    return None
