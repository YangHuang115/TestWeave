import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from testweave.core.security import hash_password
from testweave.db.models import User


class UserService:
    @staticmethod
    def create_user(
        db: Session,
        *,
        username: str,
        email: str,
        display_name: str,
        password: str,
        is_system_admin: bool = False,
    ) -> User:
        """创建一个新用户"""
        # 校验唯一性
        stmt = select(User).where(or_(User.username == username, User.email == email))
        existing_user = db.scalar(stmt)
        if existing_user:
            raise ValueError("用户名或邮箱已存在")

        hashed = hash_password(password)
        user = User(
            username=username,
            email=email,
            display_name=display_name,
            hashed_password=hashed,
            status="active",
            is_system_admin=is_system_admin,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()  # 确保获取到分配的 UUID
        return user

    @staticmethod
    def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
        """根据 ID 查询用户"""
        return db.get(User, user_id)

    @staticmethod
    def get_user_by_username_or_email(db: Session, username_or_email: str) -> User | None:
        """根据用户名或邮箱查询用户"""
        stmt = select(User).where(
            or_(User.username == username_or_email, User.email == username_or_email)
        )
        return db.scalar(stmt)

    @staticmethod
    def update_user_status(db: Session, user_id: uuid.UUID, status: str) -> User:
        """更新用户状态 (e.g. 'active', 'inactive')"""
        user = db.get(User, user_id)
        if not user:
            raise ValueError("用户不存在")
        user.status = status
        user.updated_at = datetime.now(UTC)
        db.flush()
        return user
