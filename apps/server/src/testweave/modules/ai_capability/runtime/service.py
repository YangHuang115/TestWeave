import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityPackage,
    AICapabilityRun,
    AICapabilityVersion,
    AIHumanGateAction,
    AIStepExecution,
    AIStepOutputSnapshot,
    Project,
)
from testweave.modules.ai_capability.enums import (
    AIRunEventType,
    AIRunMode,
    CapabilityRunStatus,
    CapabilityVersionStatus,
    StepExecutionStatus,
)
from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
from testweave.modules.ai_capability.runtime.event_store import EventStore
from testweave.modules.ai_capability.runtime.graph import WorkflowGraph
from testweave.modules.ai_capability.runtime.schemas import (
    AIRunCreateRequest,
    AIRunDetailResponse,
    AIRunEventItem,
    AIRunEventsPollResponse,
    AIRunResponse,
    AIStepExecutionResponse,
    HumanDecisionSubmitRequest,
)
from testweave.modules.ai_capability.runtime.snapshots import (
    ExecutionSnapshotBuilder,
    calculate_json_hash,
)
from testweave.modules.ai_capability.runtime.state_machine import StateMachine


class AIRuntimeService:
    """M09 P2 平台原生 AI 运行服务层"""

    @classmethod
    def create_run(
        cls,
        db: Session,
        project_id: uuid.UUID,
        capability_id: uuid.UUID,
        request: AIRunCreateRequest,
        idempotency_key: str,
        actor_id: uuid.UUID,
        actor_permissions: set[str],
        runtime_settings: AIRuntimeSettings,
    ) -> tuple[AICapabilityRun, bool]:
        """创建运行记录 (如果幂等命返回已有 Run，新建则返回 True)"""
        # 1. 项目隔离与存在性校验
        project = db.scalar(select(Project).where(Project.id == project_id))
        if not project:
            raise AppError(code="RUN_NOT_FOUND", message="项目不存在", status_code=404)

        if project.status == "ARCHIVED":
            raise AppError(
                code="PROJECT_ARCHIVED", message="已归档项目禁止新建 AI 运行", status_code=400
            )

        # 2. 检查 Runtime 配置开启
        if not runtime_settings.enabled:
            raise AppError(
                code="RUN_RUNTIME_DISABLED",
                message="AI 运行时服务当前未启用 (TESTWEAVE_AI_RUNTIME__ENABLED=false)",
                status_code=503,
            )

        # 3. 幂等校验 (project_id, initiator_id, idempotency_key)
        request_fp = calculate_json_hash(
            {
                "runMode": request.runMode,
                "capabilityVersionId": str(request.capabilityVersionId)
                if request.capabilityVersionId
                else None,
                "input": request.input,
            }
        )

        stmt_idemp = select(AICapabilityRun).where(
            AICapabilityRun.project_id == project_id,
            AICapabilityRun.initiator_id == actor_id,
            AICapabilityRun.idempotency_key == idempotency_key,
        )
        existing_run = db.scalar(stmt_idemp)
        if existing_run:
            if existing_run.request_fingerprint == request_fp:
                return existing_run, False
            else:
                raise AppError(
                    code="RUN_IDEMPOTENCY_CONFLICT",
                    message="相同的 Idempotency-Key 携带了不同的请求参数",
                    status_code=409,
                )

        # 4. 校验能力实体与平台原生模式
        cap = db.scalar(
            select(AICapability).where(
                AICapability.id == capability_id,
                or_(
                    AICapability.project_id == project_id,
                    AICapability.project_id.is_(None),  # 官方能力
                ),
            )
        )
        if not cap:
            raise AppError(
                code="RUN_NOT_FOUND", message="AI 能力不存在或无法在该项目使用", status_code=404
            )

        # 5. 校验运行模式 (NORMAL vs PREVIEW) 与版本资格
        cap_version: AICapabilityVersion | None = None

        if request.runMode == AIRunMode.PREVIEW:
            if "agent.manage" not in actor_permissions and "system.admin" not in actor_permissions:
                raise AppError(
                    code="PERMISSION_DENIED",
                    message="预览运行 (PREVIEW) 仅限具备 agent.manage 权限的用户操作",
                    status_code=403,
                )
            if not request.capabilityVersionId:
                raise AppError(
                    code="RUN_VERSION_NOT_RUNNABLE",
                    message="PREVIEW 模式下必须提供显式的 capabilityVersionId",
                    status_code=400,
                )

            cap_version = db.scalar(
                select(AICapabilityVersion).where(
                    AICapabilityVersion.id == request.capabilityVersionId,
                    AICapabilityVersion.capability_id == capability_id,
                )
            )
            if not cap_version:
                raise AppError(
                    code="RUN_NOT_FOUND", message="指定的 AI 能力版本不存在", status_code=404
                )
        else:
            # NORMAL 模式: 找已发布的版本
            if cap.current_published_version_id:
                cap_version = db.scalar(
                    select(AICapabilityVersion).where(
                        AICapabilityVersion.id == cap.current_published_version_id
                    )
                )
            if not cap_version:
                # 若没有已发布版本，试找符合 PUBLISHED 状态的版本
                cap_version = db.scalar(
                    select(AICapabilityVersion).where(
                        AICapabilityVersion.capability_id == capability_id,
                        AICapabilityVersion.status == CapabilityVersionStatus.PUBLISHED,
                    )
                )
            if not cap_version:
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message="该能力尚未发布（缺少 PUBLISHED 版本），无法进行正式运行",
                    status_code=400,
                )

        if cap_version.compatibility_level != "PLATFORM_NATIVE":
            comp_level = cap_version.compatibility_level or "UNKNOWN"
            raise AppError(
                code="RUN_CAPABILITY_NOT_NATIVE",
                message=f"P2 阶段仅支持 PLATFORM_NATIVE 能力，当前为 '{comp_level}'",
                status_code=400,
            )

        # 6. 读取能力包 Snapshot 文件
        package = db.scalar(
            select(AICapabilityPackage).where(
                AICapabilityPackage.capability_version_id == cap_version.id
            )
        )
        if not package or not package.files_snapshot:
            raise AppError(
                code="RUN_PACKAGE_INTEGRITY_ERROR",
                message="AI 能力包内容缺失或损坏",
                status_code=400,
            )

        workflow_snapshot = cap_version.workflow_snapshot or package.files_snapshot.get(
            "workflow.json", {}
        )
        if not workflow_snapshot:
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message="能力包中缺少 workflow 规则定义",
                status_code=400,
            )

        # 7. Workflow DAG 拓扑校验
        graph = WorkflowGraph(workflow_snapshot)

        # 8. 校验输入 Schema
        input_schema = cap_version.input_schema or package.files_snapshot.get(
            "schemas/input.schema.json"
        )
        input_size = len(
            json.dumps(request.input, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if input_size > runtime_settings.max_input_bytes:
            raise AppError(
                code="RUN_INPUT_TOO_LARGE",
                message=f"运行输入超过最大大小限制 {runtime_settings.max_input_bytes} 字节",
                status_code=400,
            )
        if input_schema and isinstance(input_schema, dict):
            import jsonschema

            try:
                jsonschema.validate(instance=request.input, schema=input_schema)
            except jsonschema.ValidationError as ve:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"运行输入校验失败: {ve.message}",
                    status_code=400,
                ) from ve

        # 9. 项目最大活跃并发数限制校验
        active_runs_count = (
            db.scalar(
                select(func.count(AICapabilityRun.id)).where(
                    AICapabilityRun.project_id == project_id,
                    AICapabilityRun.status.in_(
                        [
                            CapabilityRunStatus.PENDING,
                            CapabilityRunStatus.RUNNING,
                            CapabilityRunStatus.WAITING_HUMAN,
                            CapabilityRunStatus.WAITING_RETRY,
                        ]
                    ),
                )
            )
            or 0
        )
        if active_runs_count >= runtime_settings.project_max_active_runs:
            limit_val = runtime_settings.project_max_active_runs
            raise AppError(
                code="RUN_BUDGET_EXCEEDED",
                message=f"当前项目活跃运行并发数已达上限 ({limit_val})",
                status_code=429,
            )

        # 10. 构建固定执行快照
        exec_snapshot, exec_hash = ExecutionSnapshotBuilder.build_snapshot(
            capability_id=str(capability_id),
            capability_version_id=str(cap_version.id),
            package_fingerprint=package.package_fingerprint,
            workflow_snapshot=workflow_snapshot,
            package_files=package.files_snapshot,
            model_provider_type="openai_compatible",
            model_name="quality_first",
        )

        trace_id = f"tr-{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC)

        run = AICapabilityRun(
            capability_version_id=cap_version.id,
            project_id=project_id,
            initiator_id=actor_id,
            trace_id=trace_id,
            status=CapabilityRunStatus.PENDING,
            run_mode=request.runMode,
            input_snapshot=request.input,
            execution_snapshot=exec_snapshot,
            execution_snapshot_hash=exec_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fp,
            next_event_sequence=1,
            created_at=now,
        )
        db.add(run)
        db.flush()

        # 创建写 RUN_CREATED 事件
        EventStore.emit_event(
            db,
            run=run,
            event_type=AIRunEventType.RUN_CREATED,
            payload={
                "capability_id": str(capability_id),
                "capability_version_id": str(cap_version.id),
                "run_mode": request.runMode,
            },
        )

        # 为根就绪节点创建 attempt 1 的 PENDING 记录
        runnable_node_ids = graph.get_runnable_nodes(
            completed_node_ids=set(), pending_node_ids=set(graph.nodes.keys())
        )
        for r_node_id in runnable_node_ids:
            n_def = graph.nodes[r_node_id]
            step = AIStepExecution(
                run_id=run.id,
                node_id=r_node_id,
                node_type=n_def.get("type", "").upper(),
                node_name=n_def.get("name"),
                attempt=1,
                status=StepExecutionStatus.PENDING,
            )
            db.add(step)
            db.flush()

            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.STEP_QUEUED,
                payload={"node_id": r_node_id, "attempt": 1},
                step_execution_id=step.id,
            )

        db.commit()
        return run, True

    @classmethod
    def get_run_detail(
        cls,
        db: Session,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_permissions: set[str],
    ) -> AIRunDetailResponse:
        """读取 Run 运行详情 (带全量步骤与候选输出)"""
        run = db.scalar(
            select(AICapabilityRun).where(
                AICapabilityRun.id == run_id,
                AICapabilityRun.project_id == project_id,
            )
        )
        if not run:
            raise AppError(code="RUN_NOT_FOUND", message="AI 运行记录不存在", status_code=404)

        # 获取所有步骤
        steps = db.scalars(
            select(AIStepExecution)
            .where(AIStepExecution.run_id == run.id)
            .order_by(AIStepExecution.created_at.asc(), AIStepExecution.attempt.asc())
        ).all()

        step_responses = []
        for s in steps:
            out_snap = db.scalar(
                select(AIStepOutputSnapshot).where(AIStepOutputSnapshot.step_execution_id == s.id)
            )
            step_responses.append(
                AIStepExecutionResponse(
                    id=s.id,
                    runId=s.run_id,
                    nodeId=s.node_id,
                    nodeType=s.node_type,
                    nodeName=s.node_name,
                    attempt=s.attempt,
                    status=StepExecutionStatus(s.status),
                    inputSummary=s.input_summary,
                    outputSnapshot=out_snap.output_snapshot if out_snap else None,
                    validatorResults=out_snap.validator_results if out_snap else None,
                    retryable=s.retryable,
                    errorCode=s.error_code,
                    errorSummary=s.error_summary,
                    providerName=s.provider_name,
                    modelName=s.model_name,
                    durationMs=s.duration_ms,
                    startedAt=s.started_at,
                    completedAt=s.completed_at,
                    createdAt=s.created_at,
                )
            )

        final_out = None
        if run.final_output_snapshot_id:
            final_rec = db.scalar(
                select(AIStepOutputSnapshot).where(
                    AIStepOutputSnapshot.id == run.final_output_snapshot_id
                )
            )
            if final_rec:
                final_out = final_rec.output_snapshot

        allowed_actions = cls._calculate_allowed_actions(run, actor_id, actor_permissions)

        return AIRunDetailResponse(
            id=run.id,
            capabilityId=run.capability_version.capability_id,
            capabilityVersionId=run.capability_version_id,
            projectId=run.project_id,
            initiatorId=run.initiator_id,
            traceId=run.trace_id,
            runMode=AIRunMode(run.run_mode),
            status=CapabilityRunStatus(run.status),
            cancelRequested=run.cancel_requested_at is not None,
            allowedActions=allowed_actions,
            errorCode=run.error_code,
            errorSummary=run.error_summary,
            startedAt=run.started_at,
            completedAt=run.completed_at,
            createdAt=run.created_at,
            inputSnapshot=run.input_snapshot,
            executionSnapshotHash=run.execution_snapshot_hash,
            finalOutputSnapshot=final_out,
            steps=step_responses,
        )

    @classmethod
    def poll_events(
        cls,
        db: Session,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> AIRunEventsPollResponse:
        """游标轮询取事件"""
        run = db.scalar(
            select(AICapabilityRun).where(
                AICapabilityRun.id == run_id,
                AICapabilityRun.project_id == project_id,
            )
        )
        if not run:
            raise AppError(code="RUN_NOT_FOUND", message="AI 运行记录不存在", status_code=404)

        raw_events = EventStore.query_events_after(
            db, run_id=run.id, after_sequence=after_sequence, limit=limit
        )
        items = [
            AIRunEventItem(
                eventId=e.id,
                runId=e.run_id,
                stepExecutionId=e.step_execution_id,
                sequence=e.sequence,
                eventType=AIRunEventType(e.event_type),
                traceId=e.trace_id,
                payload=e.payload,
                occurredAt=e.occurred_at,
            )
            for e in raw_events
        ]

        next_seq = items[-1].sequence if items else after_sequence
        has_more = len(items) >= min(max(limit, 1), 200)

        return AIRunEventsPollResponse(
            items=items,
            nextSequence=next_seq,
            hasMore=has_more,
            runStatus=CapabilityRunStatus(run.status),
            cancelRequested=run.cancel_requested_at is not None,
        )

    @classmethod
    def cancel_run(
        cls,
        db: Session,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_permissions: set[str],
    ) -> AIRunResponse:
        """请求安全取消 Run"""
        run = db.scalar(
            select(AICapabilityRun)
            .where(
                AICapabilityRun.id == run_id,
                AICapabilityRun.project_id == project_id,
            )
            .with_for_update()
        )
        if not run:
            raise AppError(code="RUN_NOT_FOUND", message="AI 运行记录不存在", status_code=404)

        # 检查操作权限: 发起人本人 or agent.manage or system.admin
        is_initiator = run.initiator_id == actor_id
        is_manager = "agent.manage" in actor_permissions or "system.admin" in actor_permissions
        if not is_initiator and not is_manager:
            raise AppError(
                code="PERMISSION_DENIED",
                message="仅运行发起人或管理员具备取消运行权限",
                status_code=403,
            )

        if StateMachine.is_run_terminal(run.status):
            raise AppError(
                code="RUN_ALREADY_TERMINAL",
                message=f"运行已处于终态 ({run.status})，无法取消",
                status_code=400,
            )

        now = datetime.now(UTC)
        if not run.cancel_requested_at:
            run.cancel_requested_at = now
            run.cancel_requested_by = actor_id

            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.RUN_CANCEL_REQUESTED,
                payload={"requested_by": str(actor_id)},
            )

        # 检查是否有正在运行中的活动 Step
        running_steps = db.scalars(
            select(AIStepExecution).where(
                AIStepExecution.run_id == run.id,
                AIStepExecution.status == StepExecutionStatus.RUNNING,
            )
        ).all()

        if not running_steps:
            # 当前没有运行中的步骤，可立即将挂起/就绪节点设为 CANCELLED
            pending_or_waiting = db.scalars(
                select(AIStepExecution).where(
                    AIStepExecution.run_id == run.id,
                    AIStepExecution.status.in_(
                        [
                            StepExecutionStatus.PENDING,
                            StepExecutionStatus.WAITING_HUMAN,
                        ]
                    ),
                )
            ).all()

            for ps in pending_or_waiting:
                ps.status = StepExecutionStatus.CANCELLED
                ps.completed_at = now
                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.STEP_CANCELLED,
                    payload={"node_id": ps.node_id, "attempt": ps.attempt},
                    step_execution_id=ps.id,
                )

            StateMachine.validate_run_transition(run.status, CapabilityRunStatus.CANCELLED)
            run.status = CapabilityRunStatus.CANCELLED
            run.completed_at = now
            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.RUN_CANCELLED,
                payload={"cancelled_at": now.isoformat()},
            )

        db.commit()
        return cls._build_run_response(run, actor_id, actor_permissions)

    @classmethod
    def submit_human_decision(
        cls,
        db: Session,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        step_execution_id: uuid.UUID,
        request: HumanDecisionSubmitRequest,
        actor_id: uuid.UUID,
        actor_permissions: set[str],
    ) -> AIStepExecutionResponse:
        """人类节点决策提交与恢复"""
        run = db.scalar(
            select(AICapabilityRun)
            .where(
                AICapabilityRun.id == run_id,
                AICapabilityRun.project_id == project_id,
            )
            .with_for_update()
        )
        if not run:
            raise AppError(code="RUN_NOT_FOUND", message="AI 运行记录不存在", status_code=404)

        step = db.scalar(
            select(AIStepExecution)
            .where(
                AIStepExecution.id == step_execution_id,
                AIStepExecution.run_id == run_id,
            )
            .with_for_update()
        )
        if not step:
            raise AppError(code="RUN_NOT_FOUND", message="指定的步骤记录不存在", status_code=404)

        if step.status != StepExecutionStatus.WAITING_HUMAN:
            raise AppError(
                code="RUN_STEP_NOT_RETRYABLE",
                message=f"该步骤未处于 WAITING_HUMAN 阶段 (当前为 {step.status})",
                status_code=400,
            )

        # 检查并发提交幂等与冲突
        dec_hash = calculate_json_hash({"action": request.action, "decision": request.decision})
        existing_action = db.scalar(
            select(AIHumanGateAction).where(
                AIHumanGateAction.step_execution_id == step.id,
                AIHumanGateAction.attempt == step.attempt,
            )
        )
        if existing_action:
            if existing_action.decision_hash == dec_hash:
                out_snap = db.scalar(
                    select(AIStepOutputSnapshot).where(
                        AIStepOutputSnapshot.step_execution_id == step.id
                    )
                )
                return AIStepExecutionResponse(
                    id=step.id,
                    runId=step.run_id,
                    nodeId=step.node_id,
                    nodeType=step.node_type,
                    nodeName=step.node_name,
                    attempt=step.attempt,
                    status=StepExecutionStatus(step.status),
                    inputSummary=step.input_summary,
                    outputSnapshot=out_snap.output_snapshot if out_snap else None,
                    retryable=step.retryable,
                    createdAt=step.created_at,
                )
            else:
                raise AppError(
                    code="RUN_HUMAN_DECISION_CONFLICT",
                    message="同一个 Human 节点不能提交两次不同的决策",
                    status_code=409,
                )

        now = datetime.now(UTC)
        # 记录 Action 实体
        action_rec = AIHumanGateAction(
            run_id=run.id,
            step_execution_id=step.id,
            attempt=step.attempt,
            action=request.action,
            decision_snapshot=request.decision,
            decision_hash=dec_hash,
            submitted_by=actor_id,
            submitted_at=now,
        )
        db.add(action_rec)

        EventStore.emit_event(
            db,
            run=run,
            event_type=AIRunEventType.HUMAN_DECISION_SUBMITTED,
            payload={"node_id": step.node_id, "action": request.action},
            step_execution_id=step.id,
        )

        # 重置 Step 状态为 PENDING 以便 Worker 重新领取处理该步骤逻辑
        step.status = StepExecutionStatus.PENDING
        step.available_at = now

        db.commit()
        out_snap = db.scalar(
            select(AIStepOutputSnapshot).where(AIStepOutputSnapshot.step_execution_id == step.id)
        )
        return AIStepExecutionResponse(
            id=step.id,
            runId=step.run_id,
            nodeId=step.node_id,
            nodeType=step.node_type,
            nodeName=step.node_name,
            attempt=step.attempt,
            status=StepExecutionStatus(step.status),
            inputSummary=step.input_summary,
            outputSnapshot=out_snap.output_snapshot if out_snap else None,
            retryable=step.retryable,
            createdAt=step.created_at,
        )

    @classmethod
    def retry_step(
        cls,
        db: Session,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        step_execution_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_permissions: set[str],
    ) -> AIStepExecutionResponse:
        """人工重试失败的步骤"""
        run = db.scalar(
            select(AICapabilityRun)
            .where(
                AICapabilityRun.id == run_id,
                AICapabilityRun.project_id == project_id,
            )
            .with_for_update()
        )
        if not run:
            raise AppError(code="RUN_NOT_FOUND", message="AI 运行记录不存在", status_code=404)

        step = db.scalar(
            select(AIStepExecution)
            .where(
                AIStepExecution.id == step_execution_id,
                AIStepExecution.run_id == run_id,
            )
            .with_for_update()
        )
        if not step:
            raise AppError(code="RUN_NOT_FOUND", message="指定的步骤记录不存在", status_code=404)

        if step.status != StepExecutionStatus.FAILED or not step.retryable:
            raise AppError(
                code="RUN_STEP_NOT_RETRYABLE",
                message="只能重试处于 FAILED 状态且允许重试的步骤",
                status_code=400,
            )

        # 校验是否为该节点最新 Attempt
        latest_attempt = db.scalar(
            select(AIStepExecution.attempt)
            .where(
                AIStepExecution.run_id == run_id,
                AIStepExecution.node_id == step.node_id,
            )
            .order_by(AIStepExecution.attempt.desc())
        )
        if step.attempt != latest_attempt:
            raise AppError(
                code="RUN_STEP_NOT_RETRYABLE",
                message="只能重试该节点的最新尝试记录",
                status_code=400,
            )

        now = datetime.now(UTC)
        next_attempt = step.attempt + 1

        new_step = AIStepExecution(
            run_id=run.id,
            node_id=step.node_id,
            node_type=step.node_type,
            node_name=step.node_name,
            attempt=next_attempt,
            status=StepExecutionStatus.PENDING,
            available_at=now,
            retry_of_id=step.id,
            retryable=True,
        )
        db.add(new_step)

        if run.status != CapabilityRunStatus.RUNNING:
            StateMachine.validate_run_transition(run.status, CapabilityRunStatus.RUNNING)
            run.status = CapabilityRunStatus.RUNNING

        EventStore.emit_event(
            db,
            run=run,
            event_type=AIRunEventType.STEP_RETRY_SCHEDULED,
            payload={"node_id": step.node_id, "attempt": next_attempt},
            step_execution_id=new_step.id,
        )

        db.commit()
        return AIStepExecutionResponse(
            id=new_step.id,
            runId=new_step.run_id,
            nodeId=new_step.node_id,
            nodeType=new_step.node_type,
            nodeName=new_step.node_name,
            attempt=new_step.attempt,
            status=StepExecutionStatus(new_step.status),
            retryable=True,
            createdAt=new_step.created_at,
        )

    @classmethod
    def _calculate_allowed_actions(
        cls, run: AICapabilityRun, actor_id: uuid.UUID, permissions: set[str]
    ) -> list[str]:
        actions = []
        is_initiator = run.initiator_id == actor_id
        is_manager = "agent.manage" in permissions or "system.admin" in permissions

        if not StateMachine.is_run_terminal(run.status) and (is_initiator or is_manager):
            actions.append("cancel")

        if run.status == CapabilityRunStatus.WAITING_HUMAN and (is_initiator or is_manager):
            actions.append("submitHumanDecision")

        if run.status in {CapabilityRunStatus.FAILED, CapabilityRunStatus.WAITING_RETRY} and (
            is_initiator or is_manager
        ):
            actions.append("retryStep")

        return actions

    @classmethod
    def _build_run_response(
        cls, run: AICapabilityRun, actor_id: uuid.UUID, permissions: set[str]
    ) -> AIRunResponse:
        return AIRunResponse(
            id=run.id,
            capabilityId=run.capability_version.capability_id,
            capabilityVersionId=run.capability_version_id,
            projectId=run.project_id,
            initiatorId=run.initiator_id,
            traceId=run.trace_id,
            runMode=AIRunMode(run.run_mode),
            status=CapabilityRunStatus(run.status),
            cancelRequested=run.cancel_requested_at is not None,
            allowedActions=cls._calculate_allowed_actions(run, actor_id, permissions),
            errorCode=run.error_code,
            errorSummary=run.error_summary,
            startedAt=run.started_at,
            completedAt=run.completed_at,
            createdAt=run.created_at,
        )
