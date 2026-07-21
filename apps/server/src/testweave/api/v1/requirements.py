from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.db.models import Requirement, User, VersionRequirement
from testweave.modules.attachments.schemas import AttachmentResponse
from testweave.modules.attachments.service import AttachmentService
from testweave.modules.requirements.service import RequirementService
from testweave.shared.permissions import VERSION_MANAGE, VERSION_READ

router = APIRouter(prefix="/projects/{projectId}")


# ==============================================================================
# Pydantic Schemas
# ==============================================================================
class RequirementCreateRequest(BaseModel):
    requirement_no: str | None = Field(None, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    priority: str = Field("MEDIUM", pattern="^(HIGH|MEDIUM|LOW)$")
    owner_id: UUID | None = None


class RequirementUpdateRequest(BaseModel):
    requirement_no: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    priority: str = Field(..., pattern="^(HIGH|MEDIUM|LOW)$")
    owner_id: UUID | None = None
    status: str = Field(..., pattern="^(DRAFT|READY|CANCELLED|ARCHIVED)$")
    rowVersion: int = Field(..., alias="rowVersion")
    force_change_no: bool = Field(False)

    class Config:
        populate_by_name = True


class RequirementResponse(BaseModel):
    id: UUID
    project_id: UUID
    requirement_no: str
    title: str
    description: str | None
    priority: str
    status: str
    owner_id: UUID | None
    row_version: int = Field(..., serialization_alias="rowVersion")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ==============================================================================
# API Endpoints
# ==============================================================================

@router.post(
    "/versions/{versionId}/requirements",
    response_model=RequirementResponse,
    status_code=201,
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def create_requirement(
    projectId: UUID = Path(...),
    versionId: UUID = Path(...),
    payload: RequirementCreateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    # 1. 创建需求
    req = RequirementService.create_requirement(
        db,
        project_id=str(projectId),
        requirement_no=payload.requirement_no,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        owner_id=str(payload.owner_id) if payload.owner_id else None,
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    
    # 2. 与版本做绑定
    RequirementService.associate_to_version(
        db,
        project_id=str(projectId),
        requirement_id=str(req.id),
        version_id=str(versionId),
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
    return req


@router.get(
    "/requirements",
    response_model=list[RequirementResponse],
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def list_project_requirements(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
) -> list[Requirement]:
    stmt = (
        select(Requirement)
        .where(Requirement.project_id == projectId)
        .order_by(Requirement.created_at.desc())
    )
    return list(db.scalars(stmt).all())


@router.get(
    "/versions/{versionId}/requirements",
    response_model=list[RequirementResponse],
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def list_version_requirements(
    projectId: UUID = Path(...),
    versionId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Requirement)
        .join(VersionRequirement, VersionRequirement.requirement_id == Requirement.id)
        .where(
            Requirement.project_id == projectId,
            VersionRequirement.version_id == versionId
        )
        .order_by(Requirement.created_at.desc())
    )
    return db.scalars(stmt).all()


@router.get(
    "/requirements/{requirementId}",
    response_model=RequirementResponse,
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def get_requirement(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    return RequirementService.get_requirement_by_id(db, str(projectId), str(requirementId))


@router.patch(
    "/requirements/{requirementId}",
    response_model=RequirementResponse,
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def update_requirement(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    payload: RequirementUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    req = RequirementService.update_requirement(
        db,
        project_id=str(projectId),
        requirement_id=str(requirementId),
        requirement_no=payload.requirement_no,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        owner_id=str(payload.owner_id) if payload.owner_id else None,
        status=payload.status,
        expected_row_version=payload.rowVersion,
        actor_id=str(current_user.id),
        request_id=request_id,
        force_change_no=payload.force_change_no,
    )
    db.commit()
    return req


@router.delete(
    "/versions/{versionId}/requirements/{requirementId}",
    status_code=204,
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def dissociate_requirement_from_version(
    projectId: UUID = Path(...),
    versionId: UUID = Path(...),
    requirementId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    RequirementService.dissociate_from_version(
        db,
        project_id=str(projectId),
        requirement_id=str(requirementId),
        version_id=str(versionId),
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()


@router.post(
    "/requirements/{requirementId}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
async def upload_attachment(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    att = await AttachmentService.upload_attachment(
        db,
        project_id=str(projectId),
        requirement_id=str(requirementId),
        file=file,
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
    return att


@router.get(
    "/requirements/{requirementId}/attachments",
    response_model=list[AttachmentResponse],
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def list_attachments(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    return AttachmentService.list_attachments(db, str(projectId), str(requirementId))


@router.get(
    "/requirements/{requirementId}/attachments/{attachmentId}",
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
async def download_attachment(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    attachmentId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    stream, filename, content_type = await AttachmentService.get_attachment_stream(
        db,
        project_id=str(projectId),
        requirement_id=str(requirementId),
        attachment_id=str(attachmentId),
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    encoded_filename = quote(filename)
    return StreamingResponse(
        stream,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.delete(
    "/requirements/{requirementId}/attachments/{attachmentId}",
    status_code=204,
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def archive_attachment(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    attachmentId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    AttachmentService.archive_attachment(
        db,
        project_id=str(projectId),
        requirement_id=str(requirementId),
        attachment_id=str(attachmentId),
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
