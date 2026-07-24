import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.security import (
    generate_session_token,
    hash_session_token,
    verify_password,
)
from testweave.db.models import User, UserSession
from testweave.modules.audit.service import AuditService
from testweave.modules.users.service import UserService

SESSION_ABSOLUTE_LIFETIME = timedelta(days=7)
SESSION_IDLE_LIFETIME = timedelta(hours=24)


class AuthService:
    @staticmethod
    def login(
        db: Session,
        *,
        username_or_email: str,
        password: str,
        request_id: str,
    ) -> tuple[User, str]:
        """用户登录校验与会话创建"""
        user = UserService.get_user_by_username_or_email(db, username_or_email)
        if not user:
            # 记录失败审计
            AuditService.log_event(
                db,
                action="login_failed",
                object_type="user",
                object_id=username_or_email,
                summary=f"登录失败：用户不存在 '{username_or_email}'",
                request_id=request_id,
            )
            raise ValueError("用户名/邮箱或密码错误")

        if user.status != "active":
            AuditService.log_event(
                db,
                action="login_failed",
                object_type="user",
                object_id=str(user.id),
                actor_id=user.id,
                summary=f"登录失败：用户账号已被停用 '{user.username}'",
                request_id=request_id,
            )
            raise ValueError("账号已被停用")

        if not verify_password(user.hashed_password, password):
            AuditService.log_event(
                db,
                action="login_failed",
                object_type="user",
                object_id=str(user.id),
                actor_id=user.id,
                summary=f"登录失败：密码错误 '{user.username}'",
                request_id=request_id,
            )
            raise ValueError("用户名/邮箱或密码错误")

        # 密码正确，创建 Session
        token = generate_session_token()
        token_hash = hash_session_token(token)

        now = datetime.now(UTC)
        session = UserSession(
            user_id=user.id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + SESSION_ABSOLUTE_LIFETIME,
            last_accessed_at=now,
        )
        db.add(session)

        # 记录登录成功审计
        AuditService.log_event(
            db,
            action="login_success",
            object_type="user",
            object_id=str(user.id),
            actor_id=user.id,
            summary=f"用户登录成功 '{user.username}'",
            request_id=request_id,
        )

        return user, token

    @staticmethod
    def get_user_by_session_token(db: Session, token: str) -> User | None:
        """根据会话 Token 获取对应的有效用户，包含滑动过期更新逻辑"""
        token_hash = hash_session_token(token)
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        session = db.scalar(stmt)

        if not session:
            return None

        def ensure_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)

        now = datetime.now(UTC)
        expires_at = ensure_utc(session.expires_at)
        last_accessed_at = ensure_utc(session.last_accessed_at)

        # 校验绝对过期
        if expires_at < now:
            db.delete(session)
            return None

        # 校验空闲过期
        if last_accessed_at + SESSION_IDLE_LIFETIME < now:
            db.delete(session)
            return None

        # 校验用户状态
        user = UserService.get_user_by_id(db, session.user_id)
        if not user or user.status != "active":
            db.delete(session)
            return None

        # 滑动过期逻辑：如果自上次访问已超过 10 分钟，则使用独立的短暂 Session 进行更新并立即 Commit
        # 这样可以避免在 GET 请求（通常无显式 commit）中由于 Session 自动 Flush 导致数据库锁挂起
        if now - last_accessed_at > timedelta(minutes=10):
            from sqlalchemy import update
            from sqlalchemy.orm import Session as SqlalchemySession

            if db.bind:
                with SqlalchemySession(db.bind) as temp_db:
                    try:
                        stmt_update = (
                            update(UserSession)
                            .where(UserSession.id == session.id)
                            .values(last_accessed_at=now)
                        )
                        temp_db.execute(stmt_update)
                        temp_db.commit()
                    except Exception:
                        temp_db.rollback()

        return user

    @staticmethod
    def logout(db: Session, token: str, request_id: str) -> None:
        """注销会话"""
        token_hash = hash_session_token(token)
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        session = db.scalar(stmt)

        if session:
            user_id = session.user_id
            db.delete(session)
            # 记录注销审计
            AuditService.log_event(
                db,
                action="logout",
                object_type="user",
                object_id=str(user_id),
                actor_id=user_id,
                summary="用户注销登录",
                request_id=request_id,
            )

    @staticmethod
    def revoke_all_user_sessions(db: Session, user_id: uuid.UUID) -> None:
        """撤销用户的所有会话 (例如停用用户时调用)"""
        stmt = select(UserSession).where(UserSession.user_id == user_id)
        sessions = db.scalars(stmt).all()
        for session in sessions:
            db.delete(session)
