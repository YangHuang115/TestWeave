import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactSetRevision,
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
    AIFeedback,
    AIFieldLock,
    Project,
    User,
)
from testweave.modules.ai_capability.revision import (
    AcceptanceService,
    DiffService,
    FeedbackService,
    FieldLockService,
    RegenerationService,
    SetRevisionService,
)

router = APIRouter()


class AcceptSetRequest(BaseModel):
    expectedCurrentSetRevisionId: str | None = None


class RejectSetRequest(BaseModel):
    reason: str | None = None


class EditSetRequest(BaseModel):
    items: list[dict[str, Any]]
    expectedCurrentSetRevisionId: str | None = None


class CreateFieldLockRequest(BaseModel):
    nodeId: str
    artifactId: str
    anchorRevisionId: str
    jsonPointer: str


class CreateFeedbackRequest(BaseModel):
    targetType: str  # FIELD, ARTIFACT, STEP
    category: str
    comment: str | None = None
    targetItemId: str | None = None
    targetRevisionId: str | None = None
    targetStepExecutionId: str | None = None
    jsonPointer: str | None = None


class CreateRegenerationRequestPayload(BaseModel):
    nodeId: str
    targetItemStableKeys: list[str]
    baseSetRevisionId: str | None = None
    feedbackIds: list[str] | None = None


def get_user_permissions(user: User) -> set[str]:
    perms = {"agent.use"}
    if user.is_system_admin:
        perms.add("system.admin")
        perms.add("agent.manage")
    return perms


def verify_run_access(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID, user: User
) -> AICapabilityRun:
    run = db.get(AICapabilityRun, run_id)
    if not run or run.project_id != project_id:
        raise AppError(
            code="RUN_NOT_FOUND",
            message="运行记录不存在",
            status_code=404,
        )

    perms = get_user_permissions(user)
    if "agent.manage" not in perms and run.initiator_id != user.id:
        raise AppError(
            code="FORBIDDEN",
            message="没有权限操作此运行记录",
            status_code=403,
        )
    return run


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/revision-state",
    summary="获取 AI 运行记录的全局 Revision 状态与已接受黄金集合指针",
)
def get_revision_state(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    run = verify_run_access(db, projectId, runId, current_user)

    accepted_sets = db.query(AICurrentAcceptedRevisionSet).filter_by(run_id=run.id).all()
    field_locks = db.query(AIFieldLock).filter_by(run_id=run.id, status="ACTIVE").all()
    feedbacks = db.query(AIFeedback).filter_by(run_id=run.id, status="ACTIVE").all()

    is_terminal = run.status in ("SUCCEEDED", "FAILED", "CANCELLED")

    return {
        "run_id": str(run.id),
        "run_status": run.status,
        "is_read_only": is_terminal,
        "allowed_actions": {
            "can_accept": not is_terminal,
            "can_reject": not is_terminal,
            "can_edit": not is_terminal,
            "can_lock": not is_terminal,
            "can_feedback": not is_terminal,
            "can_regenerate": not is_terminal,
            "can_rerun": not is_terminal and run.status == "WAITING_RETRY",
        },
        "accepted_revision_sets": [
            {
                "id": str(acc.id),
                "node_id": acc.node_id,
                "current_set_revision_id": str(acc.current_set_revision_id),
                "acceptance_sequence": acc.acceptance_sequence,
                "row_version": acc.row_version,
                "freshness_status": acc.freshness_status,
                "validation_status": acc.validation_status,
                "rerun_required": acc.rerun_required,
                "state_reasons": acc.state_reasons,
                "accepted_at": acc.accepted_at,
            }
            for acc in accepted_sets
        ],
        "active_field_locks_count": len(field_locks),
        "active_feedback_count": len(feedbacks),
    }


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/nodes/{nodeId}/revision-sets",
    summary="获取指定节点的全部 SetRevision 历史",
)
def list_node_set_revisions(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    nodeId: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> list[dict[str, Any]]:
    run = verify_run_access(db, projectId, runId, current_user)
    stmt = (
        select(AIArtifactSetRevision)
        .filter_by(run_id=run.id, producer_node_id=nodeId)
        .order_by(AIArtifactSetRevision.set_revision_no.asc())
    )
    sets = db.scalars(stmt).all()

    return [
        {
            "id": str(s.id),
            "set_revision_no": s.set_revision_no,
            "base_set_revision_id": str(s.base_set_revision_id) if s.base_set_revision_id else None,
            "input_fingerprint": s.input_fingerprint,
            "set_hash": s.set_hash,
            "item_count": s.item_count,
            "review_status": s.review_status,
            "validation_status": s.validation_status,
            "created_at": s.created_at,
        }
        for s in sets
    ]


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/revision-sets/{setRevisionId}",
    summary="获取特定 SetRevision 的完整 10 条成员快照",
)
def get_set_revision_detail(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    setRevisionId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    run = verify_run_access(db, projectId, runId, current_user)

    set_rev = db.get(AIArtifactSetRevision, setRevisionId)
    if not set_rev or set_rev.run_id != run.id:
        raise AppError(code="REVISION_SET_NOT_FOUND", message="SetRevision 不存在", status_code=404)

    members = SetRevisionService.get_set_revision_members(db, str(set_rev.id))

    return {
        "id": str(set_rev.id),
        "run_id": str(set_rev.run_id),
        "producer_node_id": set_rev.producer_node_id,
        "set_revision_no": set_rev.set_revision_no,
        "input_fingerprint": set_rev.input_fingerprint,
        "set_hash": set_rev.set_hash,
        "item_count": set_rev.item_count,
        "review_status": set_rev.review_status,
        "validation_status": set_rev.validation_status,
        "created_at": set_rev.created_at,
        "items": [
            {
                "position": pos,
                "item_id": str(item.id),
                "stable_key": item.stable_key,
                "artifact_type": item.artifact_type,
                "revision_id": str(rev.id),
                "revision_no": rev.revision_no,
                "content_hash": rev.content_hash,
                "content": rev.content,
            }
            for pos, item, rev in members
        ],
    }


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/revision-sets/{setRevisionId}/diff",
    summary="获取指定 SetRevision 相对于 Base SetRevision 的结构化 Diff",
)
def get_set_revision_diff(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    setRevisionId: uuid.UUID,
    baseSetRevisionId: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)
    return DiffService.compare_set_revisions(db, str(baseSetRevisionId), str(setRevisionId))


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/revision-sets/{setRevisionId}/accept",
    summary="接受 SetRevision 候选集合（转换为 Golden Accepted State）",
)
def accept_set_revision(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    setRevisionId: uuid.UUID,
    payload: AcceptSetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)

    workflow_dag = {}  # 依赖拓扑传播
    acc_ptr = AcceptanceService.accept_set_revision(
        db=db,
        set_revision_id=str(setRevisionId),
        expected_current_set_revision_id=payload.expectedCurrentSetRevisionId,
        user_id=str(current_user.id),
        workflow_dag=workflow_dag,
    )
    db.commit()
    return {
        "status": "ACCEPTED",
        "current_accepted_set_id": str(acc_ptr.id),
        "acceptance_sequence": acc_ptr.acceptance_sequence,
    }


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/revision-sets/{setRevisionId}/reject",
    summary="驳回 SetRevision 候选集合",
)
def reject_set_revision(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    setRevisionId: uuid.UUID,
    payload: RejectSetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)
    set_rev = AcceptanceService.reject_set_revision(
        db=db,
        set_revision_id=str(setRevisionId),
        reason=payload.reason,
        user_id=str(current_user.id),
    )
    db.commit()
    return {"status": "REJECTED", "set_revision_id": str(set_rev.id)}


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/field-locks",
    summary="获取指定 Run 的全部活动 FieldLock 列表",
)
def list_field_locks(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> list[dict[str, Any]]:
    verify_run_access(db, projectId, runId, current_user)
    locks = db.query(AIFieldLock).filter_by(run_id=runId, status="ACTIVE").all()
    return [
        {
            "id": str(fl.id),
            "node_id": fl.node_id,
            "artifact_item_id": str(fl.artifact_item_id),
            "anchor_revision_id": str(fl.anchor_revision_id),
            "json_pointer": fl.json_pointer,
            "value_hash": fl.value_hash,
            "status": fl.status,
            "created_at": fl.created_at,
        }
        for fl in locks
    ]


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/field-locks",
    status_code=status.HTTP_201_CREATED,
    summary="创建字段级/整条 FieldLock 锁定",
)
def create_field_lock(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    payload: CreateFieldLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)
    lock = FieldLockService.create_field_lock(
        db=db,
        project_id=str(projectId),
        run_id=str(runId),
        node_id=payload.nodeId,
        artifact_item_id=payload.artifactId,
        anchor_revision_id=payload.anchorRevisionId,
        json_pointer=payload.jsonPointer,
        user_id=str(current_user.id),
    )
    db.commit()
    return {"id": str(lock.id), "status": lock.status, "value_hash": lock.value_hash}


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/field-locks/{fieldLockId}/release",
    summary="释放指定 FieldLock",
)
def release_field_lock(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    fieldLockId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)
    lock = FieldLockService.release_field_lock(
        db=db, field_lock_id=str(fieldLockId), released_by=str(current_user.id)
    )
    db.commit()
    return {"id": str(lock.id), "status": lock.status}


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/feedback",
    summary="获取指定 Run 的全部 Feedback 记录",
)
def list_feedback(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> list[dict[str, Any]]:
    verify_run_access(db, projectId, runId, current_user)
    feedbacks = db.query(AIFeedback).filter_by(run_id=runId, status="ACTIVE").all()
    return [
        {
            "id": str(f.id),
            "target_type": f.target_type,
            "target_item_id": str(f.target_item_id) if f.target_item_id else None,
            "target_revision_id": str(f.target_revision_id) if f.target_revision_id else None,
            "json_pointer": f.json_pointer,
            "category": f.category,
            "comment": f.comment,
            "status": f.status,
            "created_at": f.created_at,
        }
        for f in feedbacks
    ]


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/feedback",
    status_code=status.HTTP_201_CREATED,
    summary="创建 FIELD / ARTIFACT / STEP 级别的 Feedback",
)
def create_feedback(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    payload: CreateFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)
    fb = FeedbackService.create_feedback(
        db=db,
        project_id=str(projectId),
        run_id=str(runId),
        target_type=payload.targetType,
        category=payload.category,
        comment=payload.comment,
        target_item_id=payload.targetItemId,
        target_revision_id=payload.targetRevisionId,
        target_step_execution_id=payload.targetStepExecutionId,
        json_pointer=payload.jsonPointer,
        user_id=str(current_user.id),
    )
    db.commit()
    return {"id": str(fb.id), "status": fb.status}


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/regeneration-requests",
    status_code=status.HTTP_201_CREATED,
    summary="提交局部重生成请求 (带 7 条目标与 Feedback 快照)",
)
def create_regeneration_request(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    payload: CreateRegenerationRequestPayload,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    verify_run_access(db, projectId, runId, current_user)
    regen_req = RegenerationService.create_regeneration_request(
        db=db,
        project_id=str(projectId),
        run_id=str(runId),
        node_id=payload.nodeId,
        target_item_stable_keys=payload.targetItemStableKeys,
        base_set_revision_id=payload.baseSetRevisionId,
        feedback_ids=payload.feedbackIds,
        idempotency_key=idempotency_key,
        requested_by=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(regen_req.id),
        "status": regen_req.status,
        "request_fingerprint": regen_req.request_fingerprint,
    }


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/rerun-required",
    summary="触发服务端重跑受影响步骤 (UPSTREAM_CHANGE 拓扑重跑)",
)
def rerun_required_steps(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    run = verify_run_access(db, projectId, runId, current_user)

    if run.status != "WAITING_RETRY":
        raise AppError(
            code="RERUN_NOT_REQUIRED",
            message="运行当前未处于 WAITING_RETRY 挂起状态",
            status_code=400,
        )

    run.status = "RUNNING"
    db.commit()
    return {"status": "RUNNING", "message": "重新调度启动受影响步骤"}
