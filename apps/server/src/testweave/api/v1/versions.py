import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.db.models import User
from testweave.modules.versions.service import VersionService
from testweave.shared.permissions import VERSION_READ, VERSION_MANAGE

router = APIRouter(prefix="/projects/{projectId}/versions", tags=["versions"])


# Pydantic Schemas
class VersionCreateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    owner_id: uuid.UUID
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None


class VersionUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    owner_id: uuid.UUID
    status: str
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    row_version: int = Field(..., alias="rowVersion")

    model_config = {
        "populate_by_name": True
    }


class VersionResponse(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    status: str
    owner_id: uuid.UUID = Field(..., alias="ownerId")
    planned_start_at: Any = Field(..., alias="plannedStartAt")
    planned_end_at: Any = Field(..., alias="plannedEndAt")
    row_version: int = Field(..., alias="rowVersion")
    created_at: Any = Field(..., alias="createdAt")
    updated_at: Any = Field(..., alias="updatedAt")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class VersionListResponse(BaseModel):
    items: list[VersionResponse]
    total: int


@router.get("", response_model=VersionListResponse)
def list_versions(
    projectId: uuid.UUID,
    name_or_key: str | None = None,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(VERSION_READ)),
) -> Any:
    """获取当前项目下的版本列表"""
    items, total = VersionService.list_versions(
        db,
        project_id=projectId,
        name_or_key=name_or_key,
        status=status,
        owner_id=owner_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [VersionResponse.model_validate(v) for v in items],
        "total": total,
    }


@router.post("", response_model=VersionResponse, status_code=201)
def create_version(
    projectId: uuid.UUID,
    payload: VersionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(VERSION_MANAGE)),
) -> Any:
    """在当前项目下创建新版本"""
    version = VersionService.create_version(
        db,
        project_id=projectId,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        owner_id=payload.owner_id,
        planned_start_at=payload.planned_start_at,
        planned_end_at=payload.planned_end_at,
        actor_id=current_user.id,
        request_id=request.state.request_id,
    )
    db.commit()
    return VersionResponse.model_validate(version)


@router.get("/{versionId}", response_model=VersionResponse)
def get_version(
    projectId: uuid.UUID,
    versionId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(VERSION_READ)),
) -> Any:
    """获取特定版本的详细信息"""
    version = VersionService.get_version(db, project_id=projectId, version_id=versionId)
    if not version:
        from testweave.core.errors import AppError
        raise AppError(code="VERSION_NOT_FOUND", message="版本不存在或不属于当前项目", status_code=404)
    return VersionResponse.model_validate(version)


@router.patch("/{versionId}", response_model=VersionResponse)
def update_version(
    projectId: uuid.UUID,
    versionId: uuid.UUID,
    payload: VersionUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(VERSION_MANAGE)),
) -> Any:
    """更新特定版本（含乐观锁并发控制）"""
    version = VersionService.update_version(
        db,
        project_id=projectId,
        version_id=versionId,
        name=payload.name,
        description=payload.description,
        owner_id=payload.owner_id,
        status=payload.status,
        planned_start_at=payload.planned_start_at,
        planned_end_at=payload.planned_end_at,
        actor_id=current_user.id,
        request_id=request.state.request_id,
        expected_row_version=payload.row_version,
    )
    db.commit()
    return VersionResponse.model_validate(version)


@router.post("/{versionId}/archive", response_model=VersionResponse)
def archive_version(
    projectId: uuid.UUID,
    versionId: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(VERSION_MANAGE)),
) -> Any:
    """归档特定版本"""
    version = VersionService.archive_version(
        db,
        project_id=projectId,
        version_id=versionId,
        actor_id=current_user.id,
        request_id=request.state.request_id,
    )
    db.commit()
    return VersionResponse.model_validate(version)


@router.post("/{versionId}/restore", response_model=VersionResponse)
def restore_version(
    projectId: uuid.UUID,
    versionId: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(VERSION_MANAGE)),
) -> Any:
    """恢复特定归档版本"""
    version = VersionService.restore_version(
        db,
        project_id=projectId,
        version_id=versionId,
        actor_id=current_user.id,
        request_id=request.state.request_id,
    )
    db.commit()
    return VersionResponse.model_validate(version)
