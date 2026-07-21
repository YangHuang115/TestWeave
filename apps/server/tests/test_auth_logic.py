from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from testweave.api.dependencies.database import get_db
from testweave.core.config import Settings, get_settings
from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.core.security import (
    hash_password,
    hash_session_token,
    verify_password,
)
from testweave.db.base import Base
from testweave.db.models import UserSession
from testweave.main import create_app
from testweave.modules.auth.service import (
    AuthService,
)
from testweave.modules.users.service import UserService


def test_password_hashing_and_verification() -> None:
    raw_pwd = "my-secure-password"
    hashed = hash_password(raw_pwd)

    assert hashed != raw_pwd
    assert verify_password(hashed, raw_pwd) is True
    assert verify_password(hashed, "wrong-password") is False


def test_user_creation_and_login_flow(db: Session) -> None:
    # 1. 创建用户
    user = UserService.create_user(
        db,
        username="testuser",
        email="testuser@testweave.com",
        display_name="Test User",
        password="correct-password",
    )
    db.commit()

    assert user.id is not None
    assert user.status == "active"

    # 2. 正常登录
    logged_in_user, token = AuthService.login(
        db,
        username_or_email="testuser",
        password="correct-password",
        request_id="req-1",
    )
    db.commit()

    assert logged_in_user.id == user.id
    assert token is not None

    # 3. 校验 Session
    active_user = AuthService.get_user_by_session_token(db, token)
    assert active_user is not None
    assert active_user.id == user.id

    # 4. 退出登录
    AuthService.logout(db, token, "req-2")
    db.commit()

    # 5. 校验 Session 已废止
    assert AuthService.get_user_by_session_token(db, token) is None


def test_login_failures(db: Session) -> None:
    UserService.create_user(
        db,
        username="failuser",
        email="fail@testweave.com",
        display_name="Fail User",
        password="correct-password",
    )
    db.commit()

    # 用户不存在
    with pytest.raises(ValueError, match="用户名/邮箱或密码错误"):
        AuthService.login(db, username_or_email="nonexistent", password="pwd", request_id="req-f1")

    # 密码错误
    with pytest.raises(ValueError, match="用户名/邮箱或密码错误"):
        AuthService.login(
            db, username_or_email="failuser", password="wrong-password", request_id="req-f2"
        )


def test_inactive_user_cannot_login_or_restore(db: Session) -> None:
    user = UserService.create_user(
        db,
        username="inactiveuser",
        email="inactive@testweave.com",
        display_name="Inactive User",
        password="correct-password",
    )
    UserService.update_user_status(db, user.id, "inactive")
    db.commit()

    # 无法登录
    with pytest.raises(ValueError, match="账号已被停用"):
        AuthService.login(
            db, username_or_email="inactiveuser", password="correct-password", request_id="req-i1"
        )


def test_session_expiration(db: Session) -> None:
    UserService.create_user(
        db,
        username="expuser",
        email="exp@testweave.com",
        display_name="Exp User",
        password="correct-password",
    )
    db.commit()

    _, token = AuthService.login(
        db, username_or_email="expuser", password="correct-password", request_id="req-e1"
    )
    db.commit()

    # 模拟绝对过期：将 expires_at 调到过去
    token_hash = hash_session_token(token)
    session = db.query(UserSession).filter_by(token_hash=token_hash).first()
    assert session is not None
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert AuthService.get_user_by_session_token(db, token) is None


def test_session_idle_timeout(db: Session) -> None:
    UserService.create_user(
        db,
        username="idleuser",
        email="idle@testweave.com",
        display_name="Idle User",
        password="correct-password",
    )
    db.commit()

    _, token = AuthService.login(
        db, username_or_email="idleuser", password="correct-password", request_id="req-d1"
    )
    db.commit()

    # 模拟空闲过期：将 last_accessed_at 调到 25 小时前
    token_hash = hash_session_token(token)
    session = db.query(UserSession).filter_by(token_hash=token_hash).first()
    assert session is not None
    session.last_accessed_at = datetime.now(UTC) - timedelta(hours=25)
    db.commit()

    assert AuthService.get_user_by_session_token(db, token) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("environment", "expected_secure"),
    [("development", False), ("test", False), ("production", True)],
)
async def test_auth_cookies_follow_environment_secure_policy(
    environment: str,
    expected_secure: bool,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            username = f"cookie-{environment}"
            UserService.create_user(
                db,
                username=username,
                email=f"{username}@testweave.com",
                display_name="Cookie User",
                password="correct-password",
            )
            db.commit()

            settings_kwargs = (
                {"secret_key": "Y6zvH8qP2nB5sT9wK4mR7xC1dF3jL0aQ"}
                if environment == "production"
                else {}
            )
            settings = Settings(environment=environment, _env_file=None, **settings_kwargs)
            app = create_app(settings=settings, readiness_probe=NotConfiguredReadinessProbe())
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_settings] = lambda: settings
            transport = ASGITransport(app=app)

            async with AsyncClient(
                transport=transport,
                base_url="https://test" if expected_secure else "http://test",
            ) as client:
                login_response = await client.post(
                    "/api/v1/auth/login",
                    json={"username_or_email": username, "password": "correct-password"},
                )
                assert login_response.status_code == 200

                logout_response = await client.post("/api/v1/auth/logout")
                assert logout_response.status_code == 200

        for response in (login_response, logout_response):
            cookie_headers = response.headers.get_list("set-cookie")
            assert len(cookie_headers) == 2
            assert all(("; Secure" in header) is expected_secure for header in cookie_headers)
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
