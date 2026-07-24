import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import Project, User
from testweave.modules.ai_capability.runtime.config import AIProviderSettings, AIRuntimeSettings
from testweave.modules.ai_capability.runtime.schemas import (
    AIRunCreateRequest,
    AIRunDetailResponse,
    AIRunEventsPollResponse,
    AIRunResponse,
    AIStepExecutionResponse,
    HumanDecisionSubmitRequest,
)
from testweave.modules.ai_capability.runtime.service import AIRuntimeService

router = APIRouter()


def get_runtime_settings() -> AIRuntimeSettings:
    return AIRuntimeSettings()


def get_provider_settings() -> AIProviderSettings:
    return AIProviderSettings()


def get_user_permissions(user: User) -> set[str]:
    perms = {"agent.use"}
    if user.is_system_admin:
        perms.add("system.admin")
        perms.add("agent.manage")
    return perms


@router.post(
    "/projects/{projectId}/ai-capabilities/{capabilityId}/runs",
    response_model=AIRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建并启动 AI 能力运行 (异步 202 快速响应)",
)
def create_capability_run(
    projectId: uuid.UUID,
    capabilityId: uuid.UUID,
    request: AIRunCreateRequest,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
    runtime_settings: AIRuntimeSettings = Depends(get_runtime_settings),
) -> AIRunResponse:
    if not idempotency_key or not idempotency_key.strip():
        raise AppError(
            code="RUN_IDEMPOTENCY_CONFLICT",
            message="创建运行请求必须在 Header 中显式携带 'Idempotency-Key'",
            status_code=400,
        )

    permissions = get_user_permissions(current_user)
    run, _is_created = AIRuntimeService.create_run(
        db=db,
        project_id=projectId,
        capability_id=capabilityId,
        request=request,
        idempotency_key=idempotency_key.strip(),
        actor_id=current_user.id,
        actor_permissions=permissions,
        runtime_settings=runtime_settings,
    )

    response.headers["Location"] = f"/api/v1/projects/{projectId}/ai-runs/{run.id}"
    return AIRuntimeService._build_run_response(run, current_user.id, permissions)


@router.get(
    "/projects/{projectId}/ai-runs/{runId}",
    response_model=AIRunDetailResponse,
    summary="获取 AI 运行记录详情与全量步骤时间线",
)
def get_capability_run_detail(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> AIRunDetailResponse:
    permissions = get_user_permissions(current_user)
    return AIRuntimeService.get_run_detail(
        db=db,
        project_id=projectId,
        run_id=runId,
        actor_id=current_user.id,
        actor_permissions=permissions,
    )


@router.get(
    "/projects/{projectId}/ai-runs/{runId}/events",
    response_model=AIRunEventsPollResponse,
    summary="游标轮询 AI 运行事件流 (Cursor Polling)",
)
def poll_capability_run_events(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    afterSequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> AIRunEventsPollResponse:
    return AIRuntimeService.poll_events(
        db=db,
        project_id=projectId,
        run_id=runId,
        after_sequence=afterSequence,
        limit=limit,
    )


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/cancel",
    response_model=AIRunResponse,
    summary="请求安全取消 AI 运行记录",
)
def cancel_capability_run(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> AIRunResponse:
    permissions = get_user_permissions(current_user)
    return AIRuntimeService.cancel_run(
        db=db,
        project_id=projectId,
        run_id=runId,
        actor_id=current_user.id,
        actor_permissions=permissions,
    )


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/steps/{stepExecutionId}/human-decision",
    response_model=AIStepExecutionResponse,
    summary="提交 Human Gate 交互节点确认或拒绝决策",
)
def submit_human_decision(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    stepExecutionId: uuid.UUID,
    request: HumanDecisionSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> AIStepExecutionResponse:
    permissions = get_user_permissions(current_user)
    return AIRuntimeService.submit_human_decision(
        db=db,
        project_id=projectId,
        run_id=runId,
        step_execution_id=stepExecutionId,
        request=request,
        actor_id=current_user.id,
        actor_permissions=permissions,
    )


@router.post(
    "/projects/{projectId}/ai-runs/{runId}/steps/{stepExecutionId}/retry",
    response_model=AIStepExecutionResponse,
    summary="人工手动重试指定失败步骤 (创建 Attempt + 1)",
)
def retry_step_execution(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    stepExecutionId: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> AIStepExecutionResponse:
    permissions = get_user_permissions(current_user)
    return AIRuntimeService.retry_step(
        db=db,
        project_id=projectId,
        run_id=runId,
        step_execution_id=stepExecutionId,
        actor_id=current_user.id,
        actor_permissions=permissions,
    )


@router.get(
    "/projects/{projectId}/runs/{runId}/external-tasks",
    summary="获取指定 Run 关联的外部 Task 列表 (平台只读)",
)
def list_run_external_tasks(
    projectId: uuid.UUID,
    runId: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    _project: Project = Depends(require_project_permission("agent.use")),
) -> dict[str, Any]:
    return {
        "tasks": [],
        "message": "旧版外部 Worker Task 表已退役",
    }
