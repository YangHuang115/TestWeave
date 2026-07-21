from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.db.models import User
from testweave.modules.cases.service import CaseModuleService
from testweave.shared.permissions import VERSION_MANAGE, VERSION_READ

router = APIRouter(prefix="/projects/{projectId}")


# ==============================================================================
# Pydantic Schemas
# ==============================================================================
class CaseModuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    parentId: UUID | None = Field(None, alias="parentId")
    description: str | None = None
    sortOrder: int | None = Field(0, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)


class CaseModuleUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    sortOrder: int | None = Field(0, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)


class CaseModuleMoveRequest(BaseModel):
    targetParentId: UUID | None = Field(None, alias="targetParentId")

    model_config = ConfigDict(populate_by_name=True)


class CaseModuleResponse(BaseModel):
    id: UUID
    project_id: UUID = Field(..., serialization_alias="projectId")
    parent_id: UUID | None = Field(None, serialization_alias="parentId")
    name: str
    description: str | None
    sort_order: int = Field(..., serialization_alias="sortOrder")
    archived_at: datetime | None = Field(None, serialization_alias="archivedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# ==============================================================================
# API Endpoints
# ==============================================================================
@router.get("/case-modules/tree")
def get_module_tree(
    projectId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_READ)),
) -> list[dict[str, Any]]:
    """获取用例模块树状结构"""
    return CaseModuleService.get_module_tree(db, str(projectId))


@router.post("/case-modules", response_model=CaseModuleResponse)
def create_module(
    projectId: UUID,
    payload: CaseModuleCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> CaseModuleResponse:
    """新建用例模块"""
    module = CaseModuleService.create_module(
        db,
        project_id=str(projectId),
        name=payload.name,
        parent_id=str(payload.parentId) if payload.parentId else None,
        description=payload.description,
        sort_order=payload.sortOrder if payload.sortOrder is not None else 0,
    )
    db.commit()
    return CaseModuleResponse.model_validate(module)


@router.put("/case-modules/{moduleId}", response_model=CaseModuleResponse)
def update_module(
    projectId: UUID,
    moduleId: UUID,
    payload: CaseModuleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> CaseModuleResponse:
    """修改用例模块基本信息"""
    module = CaseModuleService.update_module(
        db,
        project_id=str(projectId),
        module_id=str(moduleId),
        name=payload.name,
        description=payload.description,
        sort_order=payload.sortOrder if payload.sortOrder is not None else 0,
    )

    db.commit()
    return CaseModuleResponse.model_validate(module)


@router.put("/case-modules/{moduleId}/move", response_model=CaseModuleResponse)
def move_module(
    projectId: UUID,
    moduleId: UUID,
    payload: CaseModuleMoveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> CaseModuleResponse:
    """移动模块（防循环）"""
    module = CaseModuleService.move_module(
        db,
        project_id=str(projectId),
        module_id=str(moduleId),
        target_parent_id=str(payload.targetParentId) if payload.targetParentId else None,
    )
    db.commit()
    return CaseModuleResponse.model_validate(module)


@router.post("/case-modules/{moduleId}/archive", response_model=CaseModuleResponse)
def archive_module(
    projectId: UUID,
    moduleId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> CaseModuleResponse:
    """归档模块（受防空拦截限制）"""
    module = CaseModuleService.archive_module(
        db,
        project_id=str(projectId),
        module_id=str(moduleId),
    )
    db.commit()
    return CaseModuleResponse.model_validate(module)
