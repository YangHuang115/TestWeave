import uuid

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.core.errors import AppError
from testweave.db.models import Project, ProjectMember, User
from testweave.modules.audit.service import AuditService
from testweave.shared.permissions import PROJECT_UPDATE, get_permissions_for_role


class ProjectPermissionChecker:
    def __init__(self, permission_code: str):
        self.permission_code = permission_code

    async def __call__(
        self,
        request: Request,
        projectId: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> Project:
        # 绑定 projectId 到请求 state，便于 requestId 日志记录
        request.state.project_id = projectId

        # 1. 校验项目是否存在
        project = db.get(Project, projectId)
        if not project:
            # 权限错误或不存在错误不得泄露跨项目对象是否存在。
            # 为了符合项目本身 404，我们返回项目不存在。
            raise AppError(
                code="PROJECT_NOT_FOUND",
                message="项目不存在或已被删除",
                status_code=404,
            )

        # 2. 校验归档项目的写保护。如果项目已归档且是写请求，
        # 并且校验的不是项目本身的更新权限，则拒绝写入。
        if (
            project.status == "archived"
            and request.method in ["POST", "PUT", "PATCH", "DELETE"]
            and self.permission_code != PROJECT_UPDATE
        ):
            raise AppError(
                code="PROJECT_ARCHIVED",
                message="项目已归档，处于只读状态，无法进行写操作",
                status_code=403,
            )

        # 3. 校验成员关系与权限
        # 检查当前用户是否为项目成员
        stmt = (
            select(ProjectMember)
            .where(ProjectMember.project_id == projectId)
            .where(ProjectMember.user_id == current_user.id)
        )
        member = db.scalar(stmt)

        if not member:
            # 如果是系统管理员，他可以旁路通过（但访问会被审计）
            if current_user.is_system_admin:
                # 记录高权限越权管理访问审计
                AuditService.log_event(
                    db,
                    project_id=projectId,
                    actor_id=current_user.id,
                    action="system_admin_bypass_access",
                    object_type="project",
                    object_id=str(projectId),
                    summary=f"系统管理员高权限访问项目数据：需要权限码 '{self.permission_code}'",
                    request_id=request.state.request_id,
                )
                return project
            else:
                raise AppError(
                    code="PROJECT_ACCESS_DENIED",
                    message="您不是该项目的成员，无权访问",
                    status_code=403,
                )

        # 校验项目级角色所拥有的权限码
        user_permissions = get_permissions_for_role(member.role_id)
        if self.permission_code not in user_permissions:
            raise AppError(
                code="FORBIDDEN",
                message="您的项目角色权限不足，拒绝访问",
                status_code=403,
            )

        return project


def require_project_permission(permission_code: str) -> ProjectPermissionChecker:
    """参数化依赖注入，用于校验当前登录用户在指定项目 projectId 下是否具备指定权限码"""
    return ProjectPermissionChecker(permission_code)
