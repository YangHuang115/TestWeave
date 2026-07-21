from fastapi import Depends, Request
from sqlalchemy.orm import Session

from testweave.api.dependencies.database import get_db
from testweave.core.errors import AppError
from testweave.db.models import User
from testweave.modules.auth.service import AuthService


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """提取会话 Cookie 校验当前登录用户，并进行 CSRF 防御校验"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise AppError(
            code="UNAUTHORIZED",
            message="未登录或会话已失效，请重新登录",
            status_code=401,
        )

    # 写请求 (POST, PUT, PATCH, DELETE) 执行 CSRF 校验 (Double Submit Cookie)
    if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        xsrf_cookie = request.cookies.get("xsrf_token")
        xsrf_header = request.headers.get("X-CSRF-Token")
        if not xsrf_cookie or not xsrf_header or xsrf_cookie != xsrf_header:
            raise AppError(
                code="CSRF_ERROR",
                message="CSRF 校验失败",
                status_code=403,
            )

    user = AuthService.get_user_by_session_token(db, session_token)
    if not user:
        raise AppError(
            code="UNAUTHORIZED",
            message="会话已过期，请重新登录",
            status_code=401,
        )

    # 绑定当前用户 ID 到请求状态，供 requestId 日志记录使用
    request.state.user_id = user.id
    return user


async def require_system_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """强要求必须是系统管理员身份"""
    if not current_user.is_system_admin:
        raise AppError(
            code="FORBIDDEN",
            message="拒绝访问：该操作要求系统管理员权限",
            status_code=403,
        )
    return current_user
