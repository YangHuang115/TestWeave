import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactSetRevision,
    AIFeedback,
    AIFieldLock,
    AIStepExecution,
    AITestDesignRecord,
    Project,
    ProjectMember,
    User,
)
from testweave.modules.ai_capability.revision import (
    FeedbackService,
    FieldLockService,
    RegenerationService,
)
from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
from testweave.modules.ai_capability.runtime.service import AIRuntimeService
from testweave.modules.ai_test_design.constants import STAGE_DEFINITIONS
from testweave.modules.ai_test_design.query_service import AiTestDesignQueryService
from testweave.modules.ai_test_design.revision_service import AiTestDesignRevisionService
from testweave.modules.ai_test_design.service import AiTestDesignService
from testweave.shared.permissions import AGENT_MANAGE, AGENT_USE, get_permissions_for_role

router = APIRouter(
    prefix="/projects/{projectId}/test-tasks/{taskId}/ai-design",
    tags=["ai-test-design"],
)


class CreateRecordRequest(BaseModel):
    reviewMode: str = Field(default="TRACEABLE", pattern="^(TRACEABLE|INTRINSIC)$")


class SaveStageRevisionRequest(BaseModel):
    baseSetRevisionId: uuid.UUID
    expectedSetHash: str = Field(min_length=1)
    items: list[dict[str, Any]] = Field(min_length=1)


class AcceptStageRequest(BaseModel):
    setRevisionId: uuid.UUID
    expectedCurrentSetRevisionId: str | None = None
    decisionSnapshot: dict[str, Any] = Field(default_factory=dict)


class CreateStageFeedbackRequest(BaseModel):
    targetType: str = Field(pattern="^(FIELD|ARTIFACT|STEP)$")
    category: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=5000)
    targetItemId: uuid.UUID | None = None
    targetRevisionId: uuid.UUID | None = None
    targetStepExecutionId: uuid.UUID | None = None
    jsonPointer: str | None = Field(default=None, max_length=256)


class CreateStageFieldLockRequest(BaseModel):
    itemId: uuid.UUID
    revisionId: uuid.UUID
    jsonPointer: str = Field(min_length=1, max_length=256)


class CreateStageRegenerationRequest(BaseModel):
    targetItemStableKeys: list[str] = Field(min_length=1)
    baseSetRevisionId: uuid.UUID
    feedbackIds: list[uuid.UUID] = Field(default_factory=list)


def get_runtime_settings() -> AIRuntimeSettings:
    return AIRuntimeSettings()


def _actor_permissions(db: Session, project_id: uuid.UUID, user: User) -> set[str]:
    if user.is_system_admin:
        return {"system.admin", AGENT_USE, AGENT_MANAGE}
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    return get_permissions_for_role(member.role_id) if member else set()


def _record_access(
    db: Session,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    record_id: uuid.UUID,
    user: User,
) -> tuple[AITestDesignRecord, set[str]]:
    permissions = _actor_permissions(db, project_id, user)
    record = AiTestDesignQueryService.get_record(
        db=db,
        project_id=project_id,
        task_id=task_id,
        record_id=record_id,
        actor_id=user.id,
        can_manage=AGENT_MANAGE in permissions,
    )
    return record, permissions


def _stage(stage_key: str) -> dict[str, str]:
    stage = STAGE_DEFINITIONS.get(stage_key)
    if stage is None:
        raise AppError(
            code="AI_DESIGN_STAGE_NOT_FOUND",
            message="AI 测试设计阶段不存在",
            status_code=404,
        )
    return stage


@router.get(
    "/records",
    summary="列出当前任务的 AI 测试设计生成链记录",
)
async def list_ai_test_design_records(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    permissions = _actor_permissions(db, projectId, current_user)
    records = AiTestDesignService.list_records(
        db=db,
        project_id=projectId,
        task_id=taskId,
        actor_id=current_user.id,
        can_manage=AGENT_MANAGE in permissions,
    )
    resumed = AiTestDesignService.get_resume_record(
        db=db,
        project_id=projectId,
        task_id=taskId,
        actor_id=current_user.id,
        can_manage=AGENT_MANAGE in permissions,
    )
    return {
        "items": [AiTestDesignQueryService.summarize_record(db, record) for record in records],
        "resumeRecordId": str(resumed.id) if resumed else None,
    }


@router.post(
    "/records",
    status_code=status.HTTP_202_ACCEPTED,
    summary="显式新建一轮 AI 测试设计生成链",
)
async def create_ai_test_design_record(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    payload: CreateRecordRequest,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
    runtime_settings: AIRuntimeSettings = Depends(get_runtime_settings),
) -> dict[str, Any]:
    if not idempotency_key:
        raise AppError(
            code="AI_DESIGN_IDEMPOTENCY_REQUIRED",
            message="新建生成记录必须提供 Idempotency-Key",
            status_code=400,
        )
    permissions = _actor_permissions(db, projectId, current_user)
    record, created = AiTestDesignService.create_record(
        db=db,
        project_id=projectId,
        task_id=taskId,
        actor_id=current_user.id,
        actor_permissions=permissions,
        idempotency_key=idempotency_key,
        runtime_settings=runtime_settings,
        review_mode=payload.reviewMode,
    )
    response.headers["Location"] = (
        f"/api/v1/projects/{projectId}/test-tasks/{taskId}/ai-design/records/{record.id}"
    )
    response.headers["Idempotency-Replay"] = "false" if created else "true"
    return AiTestDesignQueryService.summarize_record(db, record)


@router.get(
    "/records/{recordId}",
    summary="恢复指定生成链及阶段的完整工作台状态",
)
async def get_ai_test_design_record(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stage: str = Query(default="requirement-analysis"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    return AiTestDesignQueryService.get_workbench_state(db, record, stage)


@router.delete(
    "/records/{recordId}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="物理删除指定的 AI 测试设计生成链轮次",
)
async def delete_ai_test_design_record(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_MANAGE)),
) -> None:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    AiTestDesignService.delete_record(db, record)


@router.post(
    "/records/{recordId}/stages/{stageKey}/revisions",
    status_code=status.HTTP_201_CREATED,
    summary="将人工编辑保存为新的完整候选版本",
)
async def save_ai_test_design_stage_revision(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    payload: SaveStageRevisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    set_revision = AiTestDesignRevisionService.save_stage_revision(
        db=db,
        record=record,
        stage_key=stageKey,
        base_set_revision_id=payload.baseSetRevisionId,
        expected_set_hash=payload.expectedSetHash,
        items=payload.items,
        actor_id=current_user.id,
    )
    db.commit()
    return AiTestDesignQueryService._set_detail(db, set_revision) or {}


@router.post(
    "/records/{recordId}/stages/{stageKey}/accept",
    summary="接受阶段候选版本并恢复对应人工门禁",
)
async def accept_ai_test_design_stage(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    payload: AcceptStageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, permissions = _record_access(db, projectId, taskId, recordId, current_user)
    accepted = AiTestDesignRevisionService.accept_stage(
        db=db,
        record=record,
        stage_key=stageKey,
        set_revision_id=payload.setRevisionId,
        expected_current_set_revision_id=payload.expectedCurrentSetRevisionId,
        decision_snapshot=payload.decisionSnapshot,
        actor_id=current_user.id,
        actor_permissions=permissions,
    )
    return {
        "status": "ACCEPTED",
        "currentSetRevisionId": str(accepted.current_set_revision_id),
        "acceptanceSequence": accepted.acceptance_sequence,
        "rowVersion": accepted.row_version,
    }


@router.post(
    "/records/{recordId}/stages/{stageKey}/feedback",
    status_code=status.HTTP_201_CREATED,
    summary="为当前阶段创建字段、产物或步骤级反馈",
)
async def create_ai_test_design_feedback(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    payload: CreateStageFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    stage = _stage(stageKey)
    if payload.targetType in {"FIELD", "ARTIFACT"}:
        item = db.get(AIArtifactItem, payload.targetItemId) if payload.targetItemId else None
        revision = (
            db.get(AIArtifactRevision, payload.targetRevisionId)
            if payload.targetRevisionId
            else None
        )
        if (
            item is None
            or revision is None
            or item.run_id != record.run_id
            or item.producer_node_id != stage["nodeId"]
            or revision.artifact_item_id != item.id
        ):
            raise AppError(
                code="FEEDBACK_TARGET_INVALID",
                message="反馈目标不属于当前生成记录和阶段",
                status_code=400,
            )
    if payload.targetType == "STEP":
        step = (
            db.get(AIStepExecution, payload.targetStepExecutionId)
            if payload.targetStepExecutionId
            else None
        )
        if (
            step is None
            or step.run_id != record.run_id
            or step.node_id not in {stage["nodeId"], stage["gateNodeId"]}
        ):
            raise AppError(
                code="FEEDBACK_TARGET_INVALID",
                message="反馈步骤不属于当前生成记录和阶段",
                status_code=400,
            )
    feedback = FeedbackService.create_feedback(
        db=db,
        project_id=str(projectId),
        run_id=str(record.run_id),
        target_type=payload.targetType,
        category=payload.category,
        comment=payload.comment,
        target_item_id=str(payload.targetItemId) if payload.targetItemId else None,
        target_revision_id=(str(payload.targetRevisionId) if payload.targetRevisionId else None),
        target_step_execution_id=(
            str(payload.targetStepExecutionId) if payload.targetStepExecutionId else None
        ),
        json_pointer=payload.jsonPointer,
        user_id=str(current_user.id),
    )
    db.commit()
    return {"id": str(feedback.id), "status": feedback.status}


@router.post(
    "/records/{recordId}/stages/{stageKey}/field-locks",
    status_code=status.HTTP_201_CREATED,
    summary="锁定当前阶段指定版本字段",
)
async def create_ai_test_design_field_lock(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    payload: CreateStageFieldLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    stage = _stage(stageKey)
    item = db.get(AIArtifactItem, payload.itemId)
    revision = db.get(AIArtifactRevision, payload.revisionId)
    if (
        item is None
        or revision is None
        or item.run_id != record.run_id
        or item.producer_node_id != stage["nodeId"]
        or revision.artifact_item_id != item.id
    ):
        raise AppError(
            code="LOCK_TARGET_INVALID",
            message="锁定目标不属于当前生成记录和阶段",
            status_code=400,
        )
    lock = FieldLockService.create_field_lock(
        db=db,
        project_id=str(projectId),
        run_id=str(record.run_id),
        node_id=stage["nodeId"],
        artifact_item_id=str(item.id),
        anchor_revision_id=str(revision.id),
        json_pointer=payload.jsonPointer,
        user_id=str(current_user.id),
    )
    db.commit()
    return {"id": str(lock.id), "status": lock.status, "valueHash": lock.value_hash}


@router.post(
    "/records/{recordId}/stages/{stageKey}/field-locks/{lockId}/release",
    summary="释放当前阶段字段锁",
)
async def release_ai_test_design_field_lock(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    lockId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    stage = _stage(stageKey)
    lock = db.get(AIFieldLock, lockId)
    if lock is None or lock.run_id != record.run_id or lock.node_id != stage["nodeId"]:
        raise AppError(code="LOCK_TARGET_INVALID", message="字段锁不存在", status_code=404)
    released = FieldLockService.release_field_lock(
        db, str(lock.id), released_by=str(current_user.id)
    )
    db.commit()
    return {"id": str(released.id), "status": released.status}


@router.post(
    "/records/{recordId}/stages/{stageKey}/regeneration-requests",
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建带反馈快照的局部重生成请求",
)
async def create_ai_test_design_regeneration_request(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    payload: CreateStageRegenerationRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, _permissions = _record_access(db, projectId, taskId, recordId, current_user)
    stage = _stage(stageKey)
    if not idempotency_key or not idempotency_key.strip():
        raise AppError(
            code="AI_DESIGN_IDEMPOTENCY_REQUIRED",
            message="局部重生成请求必须提供 Idempotency-Key",
            status_code=400,
        )
    base_set = db.get(AIArtifactSetRevision, payload.baseSetRevisionId)
    if (
        base_set is None
        or base_set.run_id != record.run_id
        or base_set.producer_node_id != stage["nodeId"]
    ):
        raise AppError(
            code="REGENERATION_BASE_CHANGED",
            message="重生成基准不属于当前生成记录和阶段",
            status_code=409,
        )
    for feedback_id in payload.feedbackIds:
        feedback = db.get(AIFeedback, feedback_id)
        if feedback is None or feedback.run_id != record.run_id:
            raise AppError(
                code="FEEDBACK_TARGET_INVALID",
                message="重生成请求包含不属于当前记录的反馈",
                status_code=400,
            )
    request = RegenerationService.create_regeneration_request(
        db=db,
        project_id=str(projectId),
        run_id=str(record.run_id),
        node_id=stage["nodeId"],
        target_item_stable_keys=payload.targetItemStableKeys,
        base_set_revision_id=str(base_set.id),
        feedback_ids=[str(feedback_id) for feedback_id in payload.feedbackIds],
        idempotency_key=idempotency_key.strip(),
        requested_by=str(current_user.id),
    )
    db.commit()
    return {
        "id": str(request.id),
        "status": request.status,
        "requestFingerprint": request.request_fingerprint,
    }


@router.post(
    "/records/{recordId}/stages/{stageKey}/retry",
    summary="安全重试当前阶段最新失败步骤",
)
async def retry_ai_test_design_stage(
    projectId: uuid.UUID,
    taskId: uuid.UUID,
    recordId: uuid.UUID,
    stageKey: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission(AGENT_USE)),
) -> dict[str, Any]:
    record, permissions = _record_access(db, projectId, taskId, recordId, current_user)
    stage = _stage(stageKey)
    step = db.scalar(
        select(AIStepExecution)
        .where(
            AIStepExecution.run_id == record.run_id,
            AIStepExecution.node_id == stage["nodeId"],
        )
        .order_by(AIStepExecution.attempt.desc())
        .limit(1)
    )
    if step is None or step.status != "FAILED":
        raise AppError(
            code="RUN_STEP_NOT_RETRYABLE",
            message="当前阶段没有可重试的失败步骤",
            status_code=400,
        )
    retried = AIRuntimeService.retry_step(
        db=db,
        project_id=projectId,
        run_id=record.run_id,
        step_execution_id=step.id,
        actor_id=current_user.id,
        actor_permissions=permissions,
    )
    return retried.model_dump(mode="json")
