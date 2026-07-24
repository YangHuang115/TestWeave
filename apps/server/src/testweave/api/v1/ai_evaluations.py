import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.db.models import (
    AIEvaluationCaseRecommendation,
    AIEvaluationSet,
    User,
)
from testweave.modules.ai_capabilities.evaluation_service import EvaluationService
from testweave.shared.permissions import PROJECT_READ, PROJECT_UPDATE

router = APIRouter(tags=["AI Capability Evaluation"])


# Schemas
class EvaluationSetCreateRequest(BaseModel):
    set_key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class SetRevisionCreateRequest(BaseModel):
    case_revision_ids: list[str]
    evaluator_profile: dict[str, Any] | None = None


class AcceptRecommendationRequest(BaseModel):
    case_name: str
    redacted_inputs: dict[str, Any]
    declarative_assertions: list[Any]
    human_decision_fixture: dict[str, Any] | None = None


class EvaluationRunCreateRequest(BaseModel):
    capability_id: str
    capability_version_id: str
    set_revision_id: str
    repetitions: int = Field(1, ge=1, le=10)


class ComparisonCreateRequest(BaseModel):
    baseline_run_id: str
    candidate_run_id: str


# Routes
@router.get("/projects/{projectId}/evaluation-sets")
def list_evaluation_sets(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> list[dict[str, Any]]:
    stmt = select(AIEvaluationSet).where(
        (AIEvaluationSet.project_id == projectId) | (AIEvaluationSet.scope_type == "OFFICIAL")
    )
    sets = db.scalars(stmt).all()
    return [
        {
            "id": str(s.id),
            "project_id": str(s.project_id) if s.project_id else None,
            "scope_type": s.scope_type,
            "set_key": s.set_key,
            "name": s.name,
            "description": s.description,
            "current_revision_id": str(s.current_revision_id) if s.current_revision_id else None,
        }
        for s in sets
    ]


@router.post("/projects/{projectId}/evaluation-sets")
def create_evaluation_set(
    payload: EvaluationSetCreateRequest = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    eval_set = AIEvaluationSet(
        id=uuid.uuid4(),
        project_id=projectId,
        scope_type="PROJECT",
        set_key=payload.set_key,
        name=payload.name,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(eval_set)
    db.commit()
    return {"id": str(eval_set.id), "set_key": eval_set.set_key, "name": eval_set.name}


@router.post("/projects/{projectId}/evaluation-sets/{setId}/revisions")
def create_set_revision(
    setId: UUID = Path(...),
    payload: SetRevisionCreateRequest = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    srev = EvaluationService.create_evaluation_set_revision(
        db=db,
        set_id=str(setId),
        case_revision_ids=payload.case_revision_ids,
        evaluator_profile=payload.evaluator_profile,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(srev.id),
        "revision_no": srev.revision_no,
        "revision_hash": srev.revision_hash,
    }


@router.get("/projects/{projectId}/case-recommendations")
def list_recommendations(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> list[dict[str, Any]]:
    stmt = select(AIEvaluationCaseRecommendation).where(
        AIEvaluationCaseRecommendation.project_id == projectId
    )
    recs = db.scalars(stmt).all()
    return [
        {
            "id": str(r.id),
            "source_type": r.source_type,
            "source_id": r.source_id,
            "suggested_inputs": r.suggested_inputs_json,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in recs
    ]


@router.post("/projects/{projectId}/case-recommendations/{id}/accept")
def accept_recommendation(
    id: UUID = Path(...),
    payload: AcceptRecommendationRequest = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    case_rev = EvaluationService.accept_recommendation(
        db=db,
        recommendation_id=str(id),
        case_name=payload.case_name,
        redacted_inputs=payload.redacted_inputs,
        declarative_assertions=payload.declarative_assertions,
        human_decision_fixture=payload.human_decision_fixture,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(case_rev.id),
        "case_id": str(case_rev.case_id),
        "revision_no": case_rev.revision_no,
    }


@router.post("/projects/{projectId}/evaluation-runs")
def create_evaluation_run(
    payload: EvaluationRunCreateRequest = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    eval_run = EvaluationService.create_evaluation_run(
        db=db,
        capability_id=payload.capability_id,
        capability_version_id=payload.capability_version_id,
        set_revision_id=payload.set_revision_id,
        repetitions=payload.repetitions,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {"id": str(eval_run.id), "status": eval_run.status, "total_cases": eval_run.total_cases}


@router.post("/projects/{projectId}/evaluation-comparisons")
def create_comparison(
    payload: ComparisonCreateRequest = Body(...),
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(PROJECT_UPDATE)),
) -> dict[str, Any]:
    comp = EvaluationService.create_comparison(
        db=db,
        baseline_run_id=payload.baseline_run_id,
        candidate_run_id=payload.candidate_run_id,
        actor_id=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(comp.id),
        "status": comp.status,
        "not_comparable_reason": comp.not_comparable_reason,
        "summary_diff": comp.summary_diff_json,
    }
