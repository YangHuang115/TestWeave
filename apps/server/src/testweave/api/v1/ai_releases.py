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
from testweave.db.models import (
    AICapabilityDeployment,
    User,
)
from testweave.modules.ai_capabilities.release_service import ReleaseService
from testweave.shared.permissions import PROJECT_READ, PROJECT_UPDATE

router = APIRouter(tags=["AI Capability Releases"])


# Schemas
class CreateReleaseRequestPayload(BaseModel):
    candidate_version_id: str
    evaluation_run_id: str | None = None
    comparison_id: str | None = None
    reason: str | None = None


class StartCanaryPayload(BaseModel):
    release_request_id: str
    canary_basis_points: int = Field(..., ge=1, le=9999)
    reason: str


class AdjustCanaryPayload(BaseModel):
    canary_basis_points: int = Field(..., ge=1, le=9999)
    expected_deployment_revision: int
    reason: str


class PromotePayload(BaseModel):
    expected_deployment_revision: int
    reason: str


class RollbackPayload(BaseModel):
    target_version_id: str
    expected_deployment_revision: int
    reason: str = Field(..., min_length=1)


# Routes
@router.get("/projects/{projectId}/capabilities/{capabilityId}/deployment")
def get_capability_deployment(
    projectId: UUID = Path(...),
    capabilityId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> dict[str, Any]:
    stmt = select(AICapabilityDeployment).where(
        AICapabilityDeployment.capability_id == capabilityId
    )
    deploy = db.scalar(stmt)
    if not deploy:
        return {"status": "NOT_INITIALIZED", "canary_basis_points": 0}

    return {
        "id": str(deploy.id),
        "capability_id": str(deploy.capability_id),
        "stable_version_id": str(deploy.stable_version_id),
        "canary_version_id": str(deploy.canary_version_id) if deploy.canary_version_id else None,
        "canary_basis_points": deploy.canary_basis_points,
        "deployment_revision": deploy.deployment_revision,
        "status": deploy.status,
    }


@router.post("/projects/{projectId}/capabilities/{capabilityId}/release-requests")
def create_release_request(
    capabilityId: UUID = Path(...),
    payload: CreateReleaseRequestPayload = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    rel_req = ReleaseService.create_release_request(
        db=db,
        project_id=str(projectId),
        capability_id=str(capabilityId),
        candidate_version_id=payload.candidate_version_id,
        evaluation_run_id=payload.evaluation_run_id,
        comparison_id=payload.comparison_id,
        reason=payload.reason,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(rel_req.id),
        "status": rel_req.status,
        "blocking_checks": rel_req.blocking_checks_json,
        "advisories": rel_req.advisories_json,
        "request_fingerprint": rel_req.request_fingerprint,
    }


@router.post("/projects/{projectId}/capabilities/{capabilityId}/deployments/start-canary")
def start_canary(
    capabilityId: UUID = Path(...),
    payload: StartCanaryPayload = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    deploy = ReleaseService.start_canary(
        db=db,
        release_request_id=payload.release_request_id,
        canary_basis_points=payload.canary_basis_points,
        reason=payload.reason,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(deploy.id),
        "canary_version_id": str(deploy.canary_version_id),
        "canary_basis_points": deploy.canary_basis_points,
        "deployment_revision": deploy.deployment_revision,
    }


@router.post("/projects/{projectId}/capabilities/{capabilityId}/deployments/adjust-canary")
def adjust_canary(
    capabilityId: UUID = Path(...),
    payload: AdjustCanaryPayload = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    stmt = select(AICapabilityDeployment).where(
        AICapabilityDeployment.capability_id == capabilityId
    )
    deploy_exist = db.scalar(stmt)
    if not deploy_exist:
        raise AppError(code="DEPLOYMENT_NOT_FOUND", message="部署不存在", status_code=404)

    deploy = ReleaseService.adjust_canary(
        db=db,
        deployment_id=str(deploy_exist.id),
        canary_basis_points=payload.canary_basis_points,
        reason=payload.reason,
        expected_deployment_revision=payload.expected_deployment_revision,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(deploy.id),
        "canary_basis_points": deploy.canary_basis_points,
        "deployment_revision": deploy.deployment_revision,
    }


@router.post("/projects/{projectId}/capabilities/{capabilityId}/deployments/promote")
def promote(
    capabilityId: UUID = Path(...),
    payload: PromotePayload = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    stmt = select(AICapabilityDeployment).where(
        AICapabilityDeployment.capability_id == capabilityId
    )
    deploy_exist = db.scalar(stmt)
    if not deploy_exist:
        raise AppError(code="DEPLOYMENT_NOT_FOUND", message="部署不存在", status_code=404)

    deploy = ReleaseService.promote(
        db=db,
        deployment_id=str(deploy_exist.id),
        reason=payload.reason,
        expected_deployment_revision=payload.expected_deployment_revision,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(deploy.id),
        "stable_version_id": str(deploy.stable_version_id),
        "canary_version_id": None,
        "canary_basis_points": 0,
        "deployment_revision": deploy.deployment_revision,
    }


@router.post("/projects/{projectId}/capabilities/{capabilityId}/deployments/rollback")
def rollback(
    capabilityId: UUID = Path(...),
    payload: RollbackPayload = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    deploy = ReleaseService.rollback(
        db=db,
        capability_id=str(capabilityId),
        target_version_id=payload.target_version_id,
        reason=payload.reason,
        expected_deployment_revision=payload.expected_deployment_revision,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(deploy.id),
        "stable_version_id": str(deploy.stable_version_id),
        "deployment_revision": deploy.deployment_revision,
        "status": "ROLLED_BACK",
    }
