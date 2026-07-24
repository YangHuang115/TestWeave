import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import ExternalAgentToken, ProjectMember, User
from testweave.modules.ai_capability.config import get_external_agent_config

SUPPORTED_SCOPES: dict[str, dict[str, Any]] = {
    "workspace:spec": {
        "description": "获取 Workspace 代码生成与隔离规范 Spec",
        "min_role": "VIEWER",  # VIEWER, EDITOR, ADMIN, OWNER
    },
    "workspace:artifact": {
        "description": "获取/同步工作区工程文件与附件",
        "min_role": "VIEWER",
    },
    "revision:candidate": {
        "description": "从外部接入系统提交 Candidate Revision 候选版本",
        "min_role": "EDITOR",
    },
    "revision:publish_request": {
        "description": "提交 Candidate 发布申请/发布草稿",
        "min_role": "EDITOR",
    },
    "test_task.read": {
        "description": "读取项目测试任务列表与任务详细信息",
        "min_role": "VIEWER",
    },
    "requirement.read": {
        "description": "读取项目需求列表与关联需求正文文档",
        "min_role": "VIEWER",
    },
}

ROLE_HIERARCHY = {
    "VIEWER": 1,
    "EDITOR": 2,
    "ADMIN": 3,
    "OWNER": 4,
}


def compute_token_hash(token_str: str) -> str:
    return hashlib.sha256(token_str.encode("utf-8")).hexdigest()


class ExternalAgentTokenService:
    @staticmethod
    def get_supported_scopes() -> dict[str, dict[str, Any]]:
        return SUPPORTED_SCOPES

    @staticmethod
    def create_token(
        db: Session,
        name: str,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        scopes: list[str],
        ttl_days: int | None = None,
    ) -> tuple[ExternalAgentToken, str]:
        # 校验 scopes 合法性
        invalid_scopes = [s for s in scopes if s not in SUPPORTED_SCOPES]
        if invalid_scopes:
            raise AppError(
                code="INVALID_TOKEN_SCOPE",
                message=f"包含不受支持的 Scope: {', '.join(invalid_scopes)}",
                status_code=400,
            )

        config = get_external_agent_config()
        prefix = config.token_prefix
        raw_secret = secrets.token_urlsafe(24)
        raw_token = f"{prefix}{raw_secret}"
        token_hash = compute_token_hash(raw_token)
        token_prefix_display = raw_token[:10]

        days = ttl_days if ttl_days is not None else config.default_token_ttl_days
        expires_at = datetime.now(UTC) + timedelta(days=days)

        token_obj = ExternalAgentToken(
            id=uuid.uuid4(),
            token_hash=token_hash,
            token_prefix=token_prefix_display,
            name=name.strip(),
            project_id=project_id,
            created_by_user_id=user_id,
            scopes=list(set(scopes)),
            expires_at=expires_at,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(token_obj)
        db.commit()
        db.refresh(token_obj)
        return token_obj, raw_token

    @staticmethod
    def revoke_token(db: Session, token_id: uuid.UUID, project_id: uuid.UUID) -> None:
        token = db.scalar(
            select(ExternalAgentToken).where(
                ExternalAgentToken.id == token_id,
                ExternalAgentToken.project_id == project_id,
            )
        )
        if not token:
            raise AppError(code="TOKEN_NOT_FOUND", message="指定 Token 不存在", status_code=404)

        if token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
            db.commit()

    @staticmethod
    def list_project_tokens(db: Session, project_id: uuid.UUID) -> list[ExternalAgentToken]:
        stmt = (
            select(ExternalAgentToken)
            .where(ExternalAgentToken.project_id == project_id)
            .order_by(ExternalAgentToken.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def authenticate_token(
        db: Session, raw_token: str
    ) -> tuple[ExternalAgentToken, User, str, list[str]]:
        """
        校验 Token 有效性并实时计算用户在项目中的真实有效权限交集。
        返回: (token_obj, user_obj, user_project_role, effective_scopes)
        """
        config = get_external_agent_config()
        if not config.enabled:
            raise AppError(
                code="EXTERNAL_AGENT_DISABLED",
                message="External Agent 功能未启用",
                status_code=503,
            )

        if not raw_token or not raw_token.startswith(config.token_prefix):
            raise AppError(
                code="INVALID_EXTERNAL_TOKEN",
                message="Token 格式非法或前缀不匹配",
                status_code=401,
            )

        token_hash = compute_token_hash(raw_token)
        token = db.scalar(
            select(ExternalAgentToken).where(ExternalAgentToken.token_hash == token_hash)
        )
        if not token:
            raise AppError(
                code="INVALID_EXTERNAL_TOKEN",
                message="Token 不存在或已失效",
                status_code=401,
            )

        now = datetime.now(UTC)
        if token.revoked_at is not None:
            raise AppError(
                code="TOKEN_REVOKED",
                message="Token 已被撤销",
                status_code=401,
            )

        if token.expires_at:
            exp_at = (
                token.expires_at.replace(tzinfo=UTC)
                if token.expires_at.tzinfo is None
                else token.expires_at
            )
            if exp_at < now:
                raise AppError(
                    code="TOKEN_EXPIRED",
                    message="Token 已过期",
                    status_code=401,
                )

        # 获取创建者 User
        user = db.get(User, token.created_by_user_id)
        if not user or user.status.lower() != "active":
            raise AppError(
                code="TOKEN_USER_INVALID",
                message="Token 关联的用户账户不可用",
                status_code=401,
            )

        # 判断用户在指定项目中的实时角色
        # 超级管理员全局 OWNER 权限
        if getattr(user, "is_system_admin", False):
            user_role = "OWNER"
        else:
            member = db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == token.project_id,
                    ProjectMember.user_id == user.id,
                )
            )
            if not member:
                raise AppError(
                    code="TOKEN_PERMISSION_DENIED",
                    message="Token 关联用户已不在该项目中，权限失效",
                    status_code=403,
                )
            role_str = member.role_id.removeprefix("project_").upper()
            user_role = role_str

        user_role_level = ROLE_HIERARCHY.get(user_role, 0)
        if user_role_level < 1:
            raise AppError(
                code="TOKEN_PERMISSION_DENIED",
                message="无项目访问权限",
                status_code=403,
            )

        # 实时计算 Token Scopes 与用户项目角色的交集
        effective_scopes: list[str] = []
        for scope in token.scopes:
            scope_info = SUPPORTED_SCOPES.get(scope)
            if not scope_info:
                continue
            min_role_level = ROLE_HIERARCHY.get(scope_info["min_role"], 99)
            if user_role_level >= min_role_level:
                effective_scopes.append(scope)

        # 更新最近使用时间
        token.last_used_at = now
        db.commit()

        return token, user, user_role, effective_scopes

    @staticmethod
    def verify_scope(effective_scopes: list[str], required_scope: str | list[str]) -> None:
        required_list = [required_scope] if isinstance(required_scope, str) else required_scope

        # 向后兼容：读取任务与需求 (test_task.read / requirement.read) 允许由包含 workspace:spec 或 revision:candidate 的旧 Token 直接满足
        has_direct = any(s in effective_scopes for s in required_list)
        is_read_compatible = (
            "test_task.read" in required_list or "requirement.read" in required_list
        ) and ("workspace:spec" in effective_scopes or "revision:candidate" in effective_scopes)

        if not (has_direct or is_read_compatible):
            req_str = " | ".join(required_list)
            raise AppError(
                code="SCOPE_PERMISSION_DENIED",
                message=f"Lack required scope ({req_str}) or user role degraded",
                status_code=403,
            )
