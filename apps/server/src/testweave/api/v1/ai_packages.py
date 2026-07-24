from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import AIOptimizationSuggestion, AIWorkspacePackage, User
from testweave.modules.ai_capabilities.package_service import PackageService
from testweave.shared.permissions import PROJECT_READ, PROJECT_UPDATE

router = APIRouter(tags=["AI Capability Workspace Packages"])


class CreateWorkspacePackageRequest(BaseModel):
    capability_id: str
    package_type: str = Field(..., pattern="^(FEEDBACK|EVALUATION|OPTIMIZATION)$")
    base_version_id: str | None = None
    candidate_version_id: str | None = None
    suggestion_ids: list[str] | None = None
    evaluation_set_revision_id: str | None = None


@router.get("/projects/{projectId}/optimization-suggestions")
def list_optimization_suggestions(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> list[dict[str, Any]]:
    stmt = select(AIOptimizationSuggestion).where(
        (AIOptimizationSuggestion.project_id == projectId)
        | (AIOptimizationSuggestion.project_id.is_(None))
    )
    suggs = db.scalars(stmt).all()
    return [
        {
            "id": str(s.id),
            "suggestion_type": s.suggestion_type,
            "title": s.title,
            "description": s.description,
            "evidence_count": s.evidence_count,
            "suggested_action_area": s.suggested_action_area,
            "status": s.status,
            "created_at": s.created_at.isoformat(),
        }
        for s in suggs
    ]


@router.post("/projects/{projectId}/workspace-packages")
def create_workspace_package(
    payload: CreateWorkspacePackageRequest = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    pkg = PackageService.create_workspace_package(
        db=db,
        capability_id=payload.capability_id,
        package_type=payload.package_type,
        base_version_id=payload.base_version_id,
        candidate_version_id=payload.candidate_version_id,
        suggestion_ids=payload.suggestion_ids,
        evaluation_set_revision_id=payload.evaluation_set_revision_id,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(pkg.id),
        "package_type": pkg.package_type,
        "package_hash": pkg.package_hash,
        "status": pkg.status,
        "evidence_manifest": pkg.evidence_manifest_json,
    }


@router.post("/projects/{projectId}/workspace-packages/{packageId}/revoke")
def revoke_workspace_package(
    packageId: UUID = Path(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    pkg = PackageService.revoke_workspace_package(
        db=db, package_id=str(packageId), actor_id=str(current_user.id)
    )
    db.commit()
    return {"id": str(pkg.id), "status": pkg.status}


# Gateway 获取接口
@router.get("/agent/v1/capabilities/{capabilityId}/optimization-packages/{packageId}")
def get_gateway_optimization_package(
    capabilityId: UUID = Path(...),
    packageId: UUID = Path(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AIWorkspacePackage).where(
        AIWorkspacePackage.id == packageId,
        AIWorkspacePackage.capability_id == capabilityId,
        AIWorkspacePackage.status == "READY",
    )
    pkg = db.scalar(stmt)
    if not pkg:
        raise AppError(code="PACKAGE_NOT_FOUND", message="Package 不存在或已撤销", status_code=404)

    return {
        "package_id": str(pkg.id),
        "capability_id": str(pkg.capability_id),
        "package_type": pkg.package_type,
        "package_hash": pkg.package_hash,
        "evidence_manifest": pkg.evidence_manifest_json,
    }
