import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user, require_system_admin
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError, ErrorResponse
from testweave.db.models import Project, User
from testweave.modules.audit.service import AuditService
from testweave.modules.projects.service import ProjectService
from testweave.shared.permissions import (
    ADMIN_READ,
    PROJECT_MEMBER_MANAGE,
    PROJECT_READ,
    PROJECT_UPDATE,
    get_permissions_for_role,
)

router = APIRouter(prefix="/projects", tags=["projects"])


# Pydantic Schemas
class ProjectCreateRequest(BaseModel):
    key: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = None
    timezone: str = "UTC"


class ProjectUpdateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = None
    timezone: str = "UTC"


class ProjectResponse(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    status: str
    timezone: str
    role_id: str | None
    created_at: Any
    updated_at: Any


class ProjectContextResponse(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    status: str
    timezone: str
    role_id: str | None
    permissions: list[str]


class MemberAddRequest(BaseModel):
    user_id: uuid.UUID
    role_id: str


class MemberRoleUpdateRequest(BaseModel):
    role_id: str


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    email: str
    display_name: str
    role_id: str
    status: str
    joined_at: Any


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    object_type: str
    object_id: str
    summary: str
    request_id: str
    created_at: Any


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """获取当前用户有权访问的项目列表"""
    return ProjectService.list_projects(
        db,
        user_id=current_user.id,
        is_system_admin=current_user.is_system_admin,
    )


@router.post("", response_model=ProjectResponse, responses={403: {"model": ErrorResponse}})
def create_project(
    request: Request,
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_system_admin),
) -> Any:
    """系统管理员创建新项目"""
    try:
        project = ProjectService.create_project(
            db,
            key=payload.key,
            name=payload.name,
            description=payload.description,
            timezone_str=payload.timezone,
            owner_id=current_user.id,
            request_id=request.state.request_id,
        )
        db.commit()
        # 组装返回数据，包含 role_id="project_admin"
        return {
            "id": project.id,
            "key": project.key,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "timezone": project.timezone,
            "role_id": "project_admin",
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
    except ValueError as e:
        db.rollback()
        raise AppError(
            code="PROJECT_KEY_ALREADY_EXISTS",
            message=str(e),
            status_code=409,
        ) from None


@router.get("/{projectId}", response_model=ProjectResponse)
def get_project(
    project: Project = Depends(require_project_permission(PROJECT_READ)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """查询项目详情"""
    # 查找角色
    member = ProjectService.get_member(db, project.id, current_user.id)
    role_id = (
        member.role_id if member else ("system_admin" if current_user.is_system_admin else None)
    )
    return {
        "id": project.id,
        "key": project.key,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "timezone": project.timezone,
        "role_id": role_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.patch("/{projectId}", response_model=ProjectResponse)
def update_project(
    request: Request,
    payload: ProjectUpdateRequest,
    project: Project = Depends(require_project_permission(PROJECT_UPDATE)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """更新项目信息"""
    try:
        updated = ProjectService.update_project(
            db,
            project_id=project.id,
            name=payload.name,
            description=payload.description,
            timezone_str=payload.timezone,
            actor_id=current_user.id,
            request_id=request.state.request_id,
        )
        db.commit()

        member = ProjectService.get_member(db, project.id, current_user.id)
        role_id = (
            member.role_id if member else ("system_admin" if current_user.is_system_admin else None)
        )
        return {
            "id": updated.id,
            "key": updated.key,
            "name": updated.name,
            "description": updated.description,
            "status": updated.status,
            "timezone": updated.timezone,
            "role_id": role_id,
            "created_at": updated.created_at,
            "updated_at": updated.updated_at,
        }
    except ValueError as e:
        db.rollback()
        raise AppError(
            code="BAD_REQUEST",
            message=str(e),
            status_code=400,
        ) from None


@router.post("/{projectId}/archive", response_model=ProjectResponse)
def archive_project(
    request: Request,
    project: Project = Depends(require_project_permission(PROJECT_UPDATE)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """归档项目 (置为只读)"""
    try:
        updated = ProjectService.archive_project(
            db,
            project_id=project.id,
            actor_id=current_user.id,
            request_id=request.state.request_id,
        )
        db.commit()

        member = ProjectService.get_member(db, project.id, current_user.id)
        role_id = (
            member.role_id if member else ("system_admin" if current_user.is_system_admin else None)
        )
        return {
            "id": updated.id,
            "key": updated.key,
            "name": updated.name,
            "description": updated.description,
            "status": updated.status,
            "timezone": updated.timezone,
            "role_id": role_id,
            "created_at": updated.created_at,
            "updated_at": updated.updated_at,
        }
    except ValueError as e:
        db.rollback()
        raise AppError(
            code="BAD_REQUEST",
            message=str(e),
            status_code=400,
        ) from None


@router.get("/{projectId}/context", response_model=ProjectContextResponse)
def get_project_context(
    project: Project = Depends(require_project_permission(PROJECT_READ)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """获取当前项目的上下文与用户在该项目中的权限"""
    member = ProjectService.get_member(db, project.id, current_user.id)
    if not member:
        if current_user.is_system_admin:
            role_id = "system_admin"
            permissions = list(
                get_permissions_for_role("project_admin")
            )  # 系统管理员代理访问时视为有管理权
        else:
            role_id = None
            permissions = []
    else:
        role_id = member.role_id
        permissions = list(get_permissions_for_role(role_id))

    return {
        "id": project.id,
        "key": project.key,
        "name": project.name,
        "status": project.status,
        "timezone": project.timezone,
        "role_id": role_id,
        "permissions": permissions,
    }


@router.get("/{projectId}/members", response_model=list[MemberResponse])
def list_members(
    project: Project = Depends(require_project_permission(PROJECT_READ)),
    db: Session = Depends(get_db),
) -> Any:
    """获取项目成员列表"""
    return ProjectService.list_members(db, project.id)


@router.post("/{projectId}/members", response_model=MemberResponse)
def add_member(
    request: Request,
    payload: MemberAddRequest,
    project: Project = Depends(require_project_permission(PROJECT_MEMBER_MANAGE)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """添加项目成员"""
    try:
        member = ProjectService.add_member(
            db,
            project_id=project.id,
            user_id=payload.user_id,
            role_id=payload.role_id,
            actor_id=current_user.id,
            request_id=request.state.request_id,
        )
        db.commit()

        # 查询成员详细信息
        user = db.get(User, payload.user_id)
        assert user is not None
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "role_id": member.role_id,
            "status": user.status,
            "joined_at": member.joined_at,
        }
    except ValueError as e:
        db.rollback()
        raise AppError(
            code="BAD_REQUEST",
            message=str(e),
            status_code=400,
        ) from None


@router.patch("/{projectId}/members/{userId}", response_model=MemberResponse)
def update_member_role(
    request: Request,
    userId: uuid.UUID,
    payload: MemberRoleUpdateRequest,
    project: Project = Depends(require_project_permission(PROJECT_MEMBER_MANAGE)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """修改项目成员角色"""
    try:
        member = ProjectService.update_member_role(
            db,
            project_id=project.id,
            user_id=userId,
            role_id=payload.role_id,
            actor_id=current_user.id,
            request_id=request.state.request_id,
        )
        db.commit()

        user = db.get(User, userId)
        assert user is not None
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "role_id": member.role_id,
            "status": user.status,
            "joined_at": member.joined_at,
        }

    except ValueError as e:
        db.rollback()
        raise AppError(
            code="BAD_REQUEST",
            message=str(e),
            status_code=400,
        ) from None


@router.delete("/{projectId}/members/{userId}")
def remove_member(
    request: Request,
    userId: uuid.UUID,
    project: Project = Depends(require_project_permission(PROJECT_MEMBER_MANAGE)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """移出项目成员"""
    try:
        ProjectService.remove_member(
            db,
            project_id=project.id,
            user_id=userId,
            actor_id=current_user.id,
            request_id=request.state.request_id,
        )
        db.commit()
        return {"status": "ok"}
    except ValueError as e:
        db.rollback()
        raise AppError(
            code="BAD_REQUEST",
            message=str(e),
            status_code=400,
        ) from None


@router.get("/{projectId}/audit-events", response_model=list[AuditEventResponse])
def list_audit_events(
    project: Project = Depends(require_project_permission(ADMIN_READ)),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> Any:
    """获取项目的审计日志列表"""
    return AuditService.list_project_events(db, project_id=project.id, limit=limit, offset=offset)
