import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.core.config import Settings, get_settings
from testweave.core.errors import AppError, ErrorResponse
from testweave.core.security import generate_session_token
from testweave.db.models import User
from testweave.modules.auth.service import SESSION_ABSOLUTE_LIFETIME, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID  # 统一使用 uuid.UUID 类型，以便类型检查一致
    username: str
    email: str
    display_name: str
    is_system_admin: bool


@router.post(
    "/login",
    response_model=UserResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    """用户登录接口，成功后返回用户信息并设置 HttpOnly session_token Cookie 与 xsrf_token Cookie"""
    try:
        user, token = AuthService.login(
            db,
            username_or_email=payload.username_or_email,
            password=payload.password,
            request_id=request.state.request_id,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise AppError(
            code="UNAUTHORIZED",
            message=str(e),
            status_code=401,
        ) from None

    # 生成 CSRF Double Submit Token
    xsrf_token = generate_session_token()

    max_age_seconds = int(SESSION_ABSOLUTE_LIFETIME.total_seconds())
    secure_cookie = settings.environment == "production"

    # 设置 Session Cookie (HttpOnly)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=max_age_seconds,
        secure=secure_cookie,
    )

    # 设置 CSRF Cookie (非 HttpOnly，便于前端 JS 读取传递到 Header)
    response.set_cookie(
        key="xsrf_token",
        value=xsrf_token,
        httponly=False,
        samesite="lax",
        path="/",
        max_age=max_age_seconds,
        secure=secure_cookie,
    )

    return user


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    """用户退出登录接口，清除 Session Cookie 并撤销会话"""
    session_token = request.cookies.get("session_token")
    if session_token:
        AuthService.logout(db, session_token, request.state.request_id)
        db.commit()

    # 清除 Cookie
    secure_cookie = settings.environment == "production"
    response.delete_cookie(
        "session_token",
        path="/",
        secure=secure_cookie,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        "xsrf_token",
        path="/",
        secure=secure_cookie,
        httponly=False,
        samesite="lax",
    )

    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> Any:
    """获取当前登录用户信息"""
    return current_user
