import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactSetRevision,
    AICapabilityRun,
    AIFieldLock,
    AIHumanGateAction,
    AIRegenerationRequest,
    AIStepExecution,
    AIStepOutputSnapshot,
)
from testweave.modules.ai_capability.enums import (
    AIRunEventType,
    CapabilityRunStatus,
    ExecNodeType,
    StepExecutionStatus,
)
from testweave.modules.ai_capability.runtime.config import AIProviderSettings, AIRuntimeSettings
from testweave.modules.ai_capability.runtime.event_store import EventStore
from testweave.modules.ai_capability.runtime.executors import (
    BaseExecutor,
    HumanExecutor,
    SkillExecutor,
    TransformExecutor,
    ValidatorExecutor,
)
from testweave.modules.ai_capability.runtime.graph import WorkflowGraph
from testweave.modules.ai_capability.runtime.input_mapping import InputMappingDSL
from testweave.modules.ai_capability.runtime.provider import (
    FakeModelProvider,
    ModelProvider,
    OpenAICompatibleProviderAdapter,
)
from testweave.modules.ai_capability.runtime.snapshots import calculate_json_hash
from testweave.modules.ai_capability.runtime.state_machine import StateMachine

logger = logging.getLogger("testweave.ai_runtime_worker")


class AIRuntimeWorker:
    """M09 AI Capability P2 内部独立 Worker"""

    def __init__(
        self,
        db_engine: Any,
        runtime_settings: AIRuntimeSettings,
        provider_settings: AIProviderSettings,
        custom_provider: ModelProvider | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.engine_or_session = db_engine
        self.runtime_settings = runtime_settings
        self.provider_settings = provider_settings
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

        if custom_provider:
            self.provider = custom_provider
        elif provider_settings.provider_type == "fake":
            self.provider = FakeModelProvider()
        else:
            self.provider = OpenAICompatibleProviderAdapter(provider_settings)

        self.executors: dict[str, BaseExecutor] = {
            ExecNodeType.SKILL: SkillExecutor(),
            ExecNodeType.TRANSFORM: TransformExecutor(),
            ExecNodeType.VALIDATOR: ValidatorExecutor(),
            ExecNodeType.HUMAN: HumanExecutor(),
        }

    def _get_db_session(self) -> tuple[Session, bool]:
        """获取或创建 DB Session (如果是共享 Session 返回 is_owned=False)"""
        if isinstance(self.engine_or_session, Session):
            return self.engine_or_session, False
        return Session(self.engine_or_session), True

    async def run_once(self) -> bool:
        """执行单次轮询与工作单元 (适用于 --once 与测试验证)"""
        now = datetime.now(UTC)

        # 1. 扫描超时或过期的 RUNNING Claim 并进行恢复退避处理
        self._recover_expired_claims(now)
        self._recover_expired_regeneration_requests(now)

        # 2. 从数据库安全抢占一个待集成的节点
        claimed_task = self._claim_next_step(now)
        if claimed_task:
            run_id, step_id, claim_owner, claim_version = claimed_task

            # 3. 异步在数据库事务外执行节点逻辑
            try:
                await self._execute_claimed_step(run_id, step_id, claim_owner, claim_version)
            except Exception as e:
                logger.exception(f"Worker {self.worker_id} 执行节点异常: {e}")
            return True

        # 4. 普通 DAG 节点空闲时，执行 P3 局部重生成队列。
        regeneration_request_id = self._claim_next_regeneration_request(now)
        if regeneration_request_id is None:
            return False
        await self._execute_claimed_regeneration(regeneration_request_id)
        return True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """死循环运行 Worker 挂起调度"""
        logger.info(f"AIRuntimeWorker [{self.worker_id}] 已启动")
        poll_interval = self.runtime_settings.poll_interval_ms / 1000.0

        while stop_event is None or not stop_event.is_set():
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(poll_interval)

    def _recover_expired_claims(self, now: datetime) -> None:
        """扫描并修复 expired claim 过期的步骤"""
        db, is_owned = self._get_db_session()
        try:
            expired_steps = db.scalars(
                select(AIStepExecution)
                .where(
                    AIStepExecution.status == StepExecutionStatus.RUNNING,
                    AIStepExecution.claim_expires_at.is_not(None),
                    AIStepExecution.claim_expires_at <= now,
                )
                .limit(20)
            ).all()

            for step in expired_steps:
                run = db.scalar(select(AICapabilityRun).where(AICapabilityRun.id == step.run_id))
                if not run:
                    continue

                # 标旧 Step 为 FAILED
                step.status = StepExecutionStatus.FAILED
                step.error_code = "RUN_WORKER_CLAIM_EXPIRED"
                step.error_summary = "Worker Claim TTL 超时失效"
                step.completed_at = now

                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.STEP_FAILED,
                    payload={
                        "node_id": step.node_id,
                        "attempt": step.attempt,
                        "error_code": step.error_code,
                    },
                    step_execution_id=step.id,
                )

                # 判断可重试性
                if (
                    step.attempt < self.runtime_settings.max_attempts
                    and not run.cancel_requested_at
                ):
                    next_attempt = step.attempt + 1
                    backoff_sec = self.runtime_settings.retry_base_seconds ** (step.attempt - 1)
                    available_at = now + timedelta(seconds=backoff_sec)

                    new_step = AIStepExecution(
                        run_id=run.id,
                        node_id=step.node_id,
                        node_type=step.node_type,
                        node_name=step.node_name,
                        attempt=next_attempt,
                        status=StepExecutionStatus.PENDING,
                        available_at=available_at,
                        retry_of_id=step.id,
                        retryable=True,
                    )
                    db.add(new_step)

                    StateMachine.validate_run_transition(
                        run.status, CapabilityRunStatus.WAITING_RETRY
                    )
                    run.status = CapabilityRunStatus.WAITING_RETRY
                    EventStore.emit_event(
                        db,
                        run=run,
                        event_type=AIRunEventType.RUN_WAITING_RETRY,
                        payload={"retry_at": available_at.isoformat()},
                    )
                else:
                    StateMachine.validate_run_transition(run.status, CapabilityRunStatus.FAILED)
                    run.status = CapabilityRunStatus.FAILED
                    run.error_code = "RUN_WORKER_CLAIM_EXPIRED"
                    run.error_summary = f"节点 '{step.node_id}' 执行超时失联且重试耗尽"
                    run.completed_at = now
                    EventStore.emit_event(
                        db,
                        run=run,
                        event_type=AIRunEventType.RUN_FAILED,
                        payload={"error_code": run.error_code},
                    )

            db.commit()
        finally:
            if is_owned:
                db.close()

    def _recover_expired_regeneration_requests(self, now: datetime) -> None:
        """将失联的局部重生成请求标记失败，避免永久显示为执行中。"""
        db, is_owned = self._get_db_session()
        try:
            expired_at = now - timedelta(seconds=self.runtime_settings.claim_ttl_seconds)
            requests = db.scalars(
                select(AIRegenerationRequest)
                .where(
                    AIRegenerationRequest.status == "RUNNING",
                    AIRegenerationRequest.started_at.is_not(None),
                    AIRegenerationRequest.started_at <= expired_at,
                )
                .limit(20)
            ).all()
            for request in requests:
                request.status = "FAILED"
                request.error_code = "REGENERATION_CLAIM_EXPIRED"
                request.error_summary = "局部重生成 Worker 执行超时，请重新发起"
                request.completed_at = now
            if requests:
                db.commit()
        finally:
            if is_owned:
                db.close()

    def _claim_next_regeneration_request(self, now: datetime) -> uuid.UUID | None:
        """排他领取一条待执行的局部重生成请求。"""
        db, is_owned = self._get_db_session()
        try:
            request = db.scalar(
                select(AIRegenerationRequest)
                .join(AICapabilityRun, AIRegenerationRequest.run_id == AICapabilityRun.id)
                .where(
                    AIRegenerationRequest.status == "PENDING",
                    AICapabilityRun.status.in_(
                        [
                            CapabilityRunStatus.PENDING,
                            CapabilityRunStatus.RUNNING,
                            CapabilityRunStatus.WAITING_RETRY,
                            CapabilityRunStatus.WAITING_HUMAN,
                        ]
                    ),
                    AICapabilityRun.cancel_requested_at.is_(None),
                )
                .order_by(AIRegenerationRequest.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if request is None:
                return None
            request.status = "RUNNING"
            request.started_at = now
            request.error_code = None
            request.error_summary = None
            db.commit()
            return request.id
        finally:
            if is_owned:
                db.close()

    def _claim_next_step(self, now: datetime) -> tuple[uuid.UUID, uuid.UUID, str, int] | None:
        """使用 FOR UPDATE SKIP LOCKED 在排他事务中安全抢占节点"""
        db, is_owned = self._get_db_session()
        try:
            # 找到可领取的 Step:
            # PENDING, available_at <= now, 所属 Run 未取消未终止
            stmt = (
                select(AIStepExecution)
                .join(AICapabilityRun, AIStepExecution.run_id == AICapabilityRun.id)
                .where(
                    AIStepExecution.status == StepExecutionStatus.PENDING,
                    or_(
                        AIStepExecution.available_at.is_(None),
                        AIStepExecution.available_at <= now,
                    ),
                    AICapabilityRun.status.in_(
                        [
                            CapabilityRunStatus.PENDING,
                            CapabilityRunStatus.RUNNING,
                            CapabilityRunStatus.WAITING_RETRY,
                            CapabilityRunStatus.WAITING_HUMAN,
                        ]
                    ),
                    AICapabilityRun.cancel_requested_at.is_(None),
                )
                .order_by(AIStepExecution.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            step = db.scalar(stmt)
            if not step:
                return None

            run = db.scalar(
                select(AICapabilityRun).where(AICapabilityRun.id == step.run_id).with_for_update()
            )
            if not run:
                return None

            # 更新抢占标志
            claim_owner = self.worker_id
            ttl = timedelta(seconds=self.runtime_settings.claim_ttl_seconds)
            claim_expires_at = now + ttl
            claim_version = step.claim_version + 1

            step.status = StepExecutionStatus.RUNNING
            step.claim_owner = claim_owner
            step.claim_expires_at = claim_expires_at
            step.claim_version = claim_version
            step.started_at = now

            if run.status != CapabilityRunStatus.RUNNING:
                if run.status == CapabilityRunStatus.PENDING:
                    run.started_at = now
                StateMachine.validate_run_transition(run.status, CapabilityRunStatus.RUNNING)
                run.status = CapabilityRunStatus.RUNNING
                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.RUN_STARTED,
                    payload={"started_at": now.isoformat()},
                )

            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.STEP_STARTED,
                payload={"node_id": step.node_id, "attempt": step.attempt},
                step_execution_id=step.id,
            )

            db.commit()
            return (run.id, step.id, claim_owner, claim_version)
        finally:
            if is_owned:
                db.close()

    async def _execute_claimed_step(
        self,
        run_id: uuid.UUID,
        step_id: uuid.UUID,
        claim_owner: str,
        claim_version: int,
    ) -> None:
        """读取快照、解析依赖、执行 Executor，并在新事务中提交完整结果"""
        snapshot = {}
        node_def = {}
        node_id = ""
        resolved_input = {}
        human_decision = None

        db, is_owned = self._get_db_session()
        try:
            step = db.scalar(select(AIStepExecution).where(AIStepExecution.id == step_id))
            run = db.scalar(select(AICapabilityRun).where(AICapabilityRun.id == run_id))

            if not step or not run:
                return

            snapshot = run.execution_snapshot
            graph = WorkflowGraph(snapshot.get("workflow", {}))
            node_id = step.node_id
            node_def = graph.nodes.get(node_id, {})

            # 准备解构上游依赖节点输出
            completed_steps = db.scalars(
                select(AIStepExecution).where(
                    AIStepExecution.run_id == run_id,
                    AIStepExecution.status == StepExecutionStatus.SUCCEEDED,
                )
            ).all()

            upstream_outputs: dict[str, dict[str, Any]] = {}
            for cs in completed_steps:
                output_snap = db.scalar(
                    select(AIStepOutputSnapshot).where(
                        AIStepOutputSnapshot.step_execution_id == cs.id
                    )
                )
                if output_snap:
                    upstream_outputs[cs.node_id] = output_snap.output_snapshot

            allowed_ancestors = graph.get_ancestors(node_id)
            input_def = node_def.get("input")

            # 解析 DSL 输入
            try:
                resolved_input = InputMappingDSL.resolve_mapping(
                    input_def=input_def,
                    capability_input=run.input_snapshot,
                    upstream_outputs=upstream_outputs,
                    allowed_upstream_node_ids=allowed_ancestors,
                )
                resolved_input = self._augment_with_accepted_context(
                    db=db,
                    run=run,
                    step=step,
                    node_def=node_def,
                    resolved_input=resolved_input,
                )
            except AppError as e:
                self._record_step_failure(step_id, e.code, e.message, retryable=False)
                return

            if step.input_context_snapshot_id:
                # 在调用 Provider 之前冻结并提交真实上游 ContextSnapshot。
                db.commit()

            # 如果为 HUMAN 节点，尝试读取已存在的 human decision
            if step.node_type == ExecNodeType.HUMAN:
                human_action_rec = db.scalar(
                    select(AIHumanGateAction).where(
                        AIHumanGateAction.step_execution_id == step_id,
                        AIHumanGateAction.attempt == step.attempt,
                    )
                )
                if human_action_rec:
                    human_decision = {
                        "action": human_action_rec.action,
                        "decision": human_action_rec.decision_snapshot,
                    }
        finally:
            if is_owned:
                db.close()

        # 检查节点执行目标: PLATFORM_NATIVE 还是 EXTERNAL_AGENT
        executor_meta = node_def.get("executor", {})
        if executor_meta.get("kind") == "EXTERNAL_AGENT":
            self._record_step_failure(
                step_id,
                "EXTERNAL_WORKER_RETIRED",
                "旧版外部 Agent Worker 协议已退役，请升级使用无状态 Client API",
                retryable=False,
            )
            return

        # 调用具体的 Executor
        executor = self.executors.get(node_def.get("type", "").upper())
        if not executor:
            self._record_step_failure(
                step_id,
                "RUN_CAPABILITY_NOT_RUNNABLE",
                f"找不到节点类型 '{node_def.get('type')}' 的执行器",
                retryable=False,
            )
            return

        start_time = datetime.now(UTC)
        try:
            res = await executor.execute(
                node_id=node_id,
                node_def=node_def,
                resolved_input=resolved_input,
                execution_snapshot=snapshot,
                provider=self.provider,
                human_decision=human_decision,
            )
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            self._record_step_success(
                step_id, claim_owner, claim_version, resolved_input, res, duration_ms
            )

        except AppError as ae:
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            self._record_step_failure(
                step_id, ae.code, ae.message, retryable=True, duration_ms=duration_ms
            )
        except Exception as ex:
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            self._record_step_failure(
                step_id,
                "RUN_PROVIDER_UNAVAILABLE",
                str(ex),
                retryable=True,
                duration_ms=duration_ms,
            )

    async def _execute_claimed_regeneration(self, request_id: uuid.UUID) -> None:
        """使用冻结反馈和当前上游快照执行真实局部重生成。"""
        try:
            prepared = self._prepare_regeneration_context(request_id)
            response = await self.provider.invoke_structured_json(
                instructions=prepared["instructions"],
                input_data=prepared["input_data"],
                output_schema=prepared["output_schema"],
                model_policy=prepared["model_policy"],
                timeout_seconds=self.runtime_settings.step_timeout_seconds,
                max_output_bytes=self.runtime_settings.max_output_bytes,
            )
            try:
                jsonschema.validate(
                    instance=response.content_json,
                    schema=prepared["output_schema"],
                )
            except jsonschema.ValidationError as exc:
                raise AppError(
                    code="REGENERATION_RESPONSE_INVALID",
                    message=f"局部重生成响应不符合结构约束: {exc.message}",
                    status_code=400,
                ) from exc

            from testweave.modules.ai_capability.revision import (
                DependencyService,
                RegenerationService,
            )

            db, is_owned = self._get_db_session()
            try:
                new_set = RegenerationService.process_regeneration_response(
                    db=db,
                    regeneration_request_id=str(request_id),
                    replacements=response.content_json["replacements"],
                    capability_version_id=prepared["capability_version_id"],
                    package_fingerprint=prepared["package_fingerprint"],
                    execution_snapshot_hash=prepared["execution_snapshot_hash"],
                    node_config=prepared["node_def"],
                    run_input=prepared["run_input"],
                    input_fingerprint=prepared["input_fingerprint"],
                )
                for upstream_node_id, manifest in prepared["upstream_manifest"].items():
                    DependencyService.record_dependency_edge(
                        db=db,
                        project_id=prepared["project_id"],
                        run_id=prepared["run_id"],
                        upstream_node_id=upstream_node_id,
                        upstream_set_revision_id=manifest["set_revision_id"],
                        downstream_node_id=prepared["node_id"],
                        downstream_context_snapshot_id=prepared["context_snapshot_id"],
                        downstream_output_set_revision_id=str(new_set.id),
                    )
                db.commit()
            finally:
                if is_owned:
                    db.close()
        except AppError as exc:
            self._record_regeneration_failure(request_id, exc.code, exc.message)
        except Exception as exc:
            self._record_regeneration_failure(
                request_id,
                "RUN_PROVIDER_UNAVAILABLE",
                str(exc),
            )

    def _prepare_regeneration_context(self, request_id: uuid.UUID) -> dict[str, Any]:
        from testweave.modules.ai_capability.revision import ContextService, SetRevisionService

        db, is_owned = self._get_db_session()
        try:
            request = db.get(AIRegenerationRequest, request_id)
            if request is None or request.status != "RUNNING":
                raise AppError(
                    code="REGENERATION_TARGET_INVALID",
                    message="局部重生成请求不存在或未被正确领取",
                    status_code=409,
                )
            run = db.get(AICapabilityRun, request.run_id)
            base_set = db.get(AIArtifactSetRevision, request.base_set_revision_id)
            if run is None or base_set is None:
                raise AppError(
                    code="REGENERATION_BASE_CHANGED",
                    message="局部重生成基准或关联运行已不存在",
                    status_code=409,
                )

            workflow = run.execution_snapshot.get("workflow", {})
            node_def = workflow.get("nodes", {}).get(request.node_id)
            if not isinstance(node_def, dict):
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message=f"局部重生成节点 {request.node_id} 不存在",
                    status_code=400,
                )
            projection = node_def.get("artifact_projection")
            if not isinstance(projection, dict):
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message=f"节点 {request.node_id} 未声明产物映射",
                    status_code=400,
                )

            latest_set_id = db.scalar(
                select(AIArtifactSetRevision.id)
                .where(
                    AIArtifactSetRevision.run_id == run.id,
                    AIArtifactSetRevision.producer_node_id == request.node_id,
                )
                .order_by(AIArtifactSetRevision.set_revision_no.desc())
                .limit(1)
            )
            if latest_set_id != base_set.id:
                raise AppError(
                    code="REGENERATION_BASE_CHANGED",
                    message="局部重生成基准已变化，请重新加载并再次提交",
                    status_code=409,
                )

            upstream_node_ids = node_def.get("accepted_upstream_nodes", [])
            context = ContextService.materialize_context_snapshot(
                db=db,
                project_id=str(run.project_id),
                run_id=str(run.id),
                node_id=request.node_id,
                purpose="REGENERATION",
                capability_version_id=str(run.capability_version_id),
                package_fingerprint=run.execution_snapshot.get("package_fingerprint", ""),
                execution_snapshot_hash=run.execution_snapshot_hash or "",
                node_config=node_def,
                run_input=run.input_snapshot,
                upstream_node_ids=upstream_node_ids,
                source_regeneration_request_id=str(request.id),
                provider_name=self.provider_settings.provider_type,
                model_name=self.provider_settings.quality_model or None,
            )

            members = SetRevisionService.get_set_revision_members(db, str(base_set.id))
            targets = set(request.request_snapshot.get("target_item_stable_keys", []))
            target_items = [
                {
                    "targetRef": f"target-{item.stable_key}",
                    "stableKey": item.stable_key,
                    "baseRevisionId": str(revision.id),
                    "content": revision.content,
                }
                for _member, item, revision in members
                if item.stable_key in targets
            ]
            if len(target_items) != len(targets):
                raise AppError(
                    code="REGENERATION_TARGET_INVALID",
                    message="局部重生成目标与基准完整集合不一致",
                    status_code=409,
                )

            item_ids = [item.id for _member, item, _revision in members]
            locks = db.scalars(
                select(AIFieldLock).where(
                    AIFieldLock.artifact_item_id.in_(item_ids),
                    AIFieldLock.status == "ACTIVE",
                )
            ).all()
            locked_fields = [
                {
                    "stableKey": next(
                        item.stable_key
                        for _member, item, _revision in members
                        if item.id == lock.artifact_item_id
                    ),
                    "jsonPointer": lock.json_pointer,
                    "valueHash": lock.value_hash,
                }
                for lock in locks
            ]

            output_schema = self._regeneration_output_schema(
                node_def=node_def,
                target_refs=[item["targetRef"] for item in target_items],
            )
            skill_name = node_def.get("skill", "")
            package_files = run.execution_snapshot.get("package_files", {})
            skill_path = f"skills/{skill_name}/SKILL.md" if skill_name else "SKILL.md"
            base_instructions = package_files.get(skill_path) or package_files.get(
                "SKILL.md", "You are an AI assistant."
            )
            instructions = (
                f"{base_instructions}\n\n"
                "这是局部重生成。只能返回 replacements 中列出的目标项；每个 targetRef "
                "必须原样返回且恰好一次。依据反馈修正 content，不能改写未指定项，也不能"
                "绕过已接受上游上下文或字段锁。"
            )
            prepared = {
                "instructions": instructions,
                "input_data": {
                    "regenerationRequest": {
                        "id": str(request.id),
                        "nodeId": request.node_id,
                        "baseSetRevisionId": str(base_set.id),
                        "baseSetHash": base_set.set_hash,
                        "targetItems": target_items,
                        "feedbackSnapshots": request.request_snapshot.get("feedback_snapshots", []),
                        "lockedFields": locked_fields,
                    },
                    "acceptedUpstreamContext": context.content["upstream_data"],
                    "acceptedUpstreamManifest": context.upstream_manifest,
                    "originalContext": run.input_snapshot,
                },
                "output_schema": output_schema,
                "model_policy": node_def.get("model_policy", "quality_first"),
                "capability_version_id": str(run.capability_version_id),
                "package_fingerprint": run.execution_snapshot.get("package_fingerprint", ""),
                "execution_snapshot_hash": run.execution_snapshot_hash or "",
                "node_def": node_def,
                "run_input": run.input_snapshot,
                "input_fingerprint": context.input_fingerprint,
                "upstream_manifest": context.upstream_manifest,
                "context_snapshot_id": str(context.id),
                "project_id": str(run.project_id),
                "run_id": str(run.id),
                "node_id": request.node_id,
            }
            input_size = len(
                json.dumps(
                    prepared["input_data"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if input_size > self.runtime_settings.max_input_bytes:
                raise AppError(
                    code="RUN_INPUT_TOO_LARGE",
                    message=(
                        "局部重生成输入超过最大大小限制 "
                        f"{self.runtime_settings.max_input_bytes} 字节"
                    ),
                    status_code=400,
                )
            db.commit()
            return prepared
        finally:
            if is_owned:
                db.close()

    @staticmethod
    def _regeneration_output_schema(
        node_def: dict[str, Any], target_refs: list[str]
    ) -> dict[str, Any]:
        output_schema = node_def.get("output_schema")
        projection = node_def.get("artifact_projection", {})
        if not isinstance(output_schema, dict) or not target_refs:
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message="局部重生成缺少输出 Schema 或目标项",
                status_code=400,
            )
        pointer = projection.get("collection_pointer", "")
        if pointer:
            collection_key = str(pointer).strip("/")
            try:
                item_schema = output_schema["properties"][collection_key]["items"]
            except (KeyError, TypeError) as exc:
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message="局部重生成无法解析集合项 Schema",
                    status_code=400,
                ) from exc
        else:
            item_schema = output_schema
        return {
            "type": "object",
            "required": ["replacements"],
            "properties": {
                "replacements": {
                    "type": "array",
                    "minItems": len(target_refs),
                    "maxItems": len(target_refs),
                    "items": {
                        "type": "object",
                        "required": ["targetRef", "content"],
                        "properties": {
                            "targetRef": {"type": "string", "enum": target_refs},
                            "content": item_schema,
                        },
                        "additionalProperties": False,
                    },
                }
            },
            "additionalProperties": False,
        }

    def _record_regeneration_failure(
        self,
        request_id: uuid.UUID,
        error_code: str,
        error_summary: str,
    ) -> None:
        db, is_owned = self._get_db_session()
        try:
            db.rollback()
            request = db.get(AIRegenerationRequest, request_id, with_for_update=True)
            if request is None or request.status == "COMPLETED":
                return
            request.status = "FAILED"
            request.error_code = error_code[:64]
            request.error_summary = error_summary[:2000]
            request.completed_at = datetime.now(UTC)
            db.commit()
        finally:
            if is_owned:
                db.close()

    def _augment_with_accepted_context(
        self,
        db: Session,
        run: AICapabilityRun,
        step: AIStepExecution,
        node_def: dict[str, Any],
        resolved_input: Any,
    ) -> Any:
        """为下游 Skill 冻结当前已接受的完整上游集合，拒绝读取 STALE 数据。"""
        upstream_node_ids = node_def.get("accepted_upstream_nodes", [])
        if not upstream_node_ids:
            return resolved_input
        if not isinstance(upstream_node_ids, list) or not all(
            isinstance(node_id, str) for node_id in upstream_node_ids
        ):
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message=f"节点 {step.node_id} 的 accepted_upstream_nodes 配置无效",
                status_code=400,
            )

        from testweave.modules.ai_capability.revision import ContextService

        context = ContextService.materialize_context_snapshot(
            db=db,
            project_id=str(run.project_id),
            run_id=str(run.id),
            node_id=step.node_id,
            purpose="STEP_EXECUTION",
            capability_version_id=str(run.capability_version_id),
            package_fingerprint=run.execution_snapshot.get("package_fingerprint", ""),
            execution_snapshot_hash=run.execution_snapshot_hash or "",
            node_config=node_def,
            run_input=run.input_snapshot,
            upstream_node_ids=upstream_node_ids,
            source_step_execution_id=str(step.id),
            provider_name=self.provider_settings.provider_type,
            model_name=self.provider_settings.quality_model or None,
        )
        step.input_context_snapshot_id = context.id
        step.input_fingerprint = context.input_fingerprint
        enriched = (
            dict(resolved_input)
            if isinstance(resolved_input, dict)
            else {"mappedInput": resolved_input}
        )
        enriched["acceptedUpstreamContext"] = context.content["upstream_data"]
        enriched["acceptedUpstreamManifest"] = context.upstream_manifest
        db.flush()
        return enriched

    def _record_step_success(
        self,
        step_id: uuid.UUID,
        claim_owner: str,
        claim_version: int,
        resolved_input: Any,
        res: Any,
        duration_ms: int,
    ) -> None:
        now = datetime.now(UTC)
        db, is_owned = self._get_db_session()
        try:
            step = db.scalar(
                select(AIStepExecution).where(AIStepExecution.id == step_id).with_for_update()
            )
            if not step:
                return

            run = db.scalar(
                select(AICapabilityRun).where(AICapabilityRun.id == step.run_id).with_for_update()
            )
            if not run:
                return

            # 校验安全锁与 Claim 抢占
            if step.claim_owner != claim_owner or step.claim_version != claim_version:
                logger.warning(f"丢弃失联 Claim 写回 (step_id={step_id})")
                return

            # 校验取消请求与迟到输出丢弃
            if run.cancel_requested_at:
                step.status = StepExecutionStatus.CANCELLED
                step.completed_at = now
                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.STEP_CANCELLED,
                    payload={"node_id": step.node_id, "attempt": step.attempt},
                    step_execution_id=step.id,
                )
                self._check_run_cancel_completion(db, run, now)
                db.commit()
                return

            # 处理 WAITING_HUMAN 挂起
            if res.waiting_human:
                step.status = StepExecutionStatus.WAITING_HUMAN
                step.input_snapshot = (
                    resolved_input
                    if isinstance(resolved_input, dict)
                    else {"input": resolved_input}
                )
                step.input_summary = {"waiting_human": True, "prompt": res.output.get("prompt")}
                step.duration_ms = duration_ms

                StateMachine.validate_run_transition(run.status, CapabilityRunStatus.WAITING_HUMAN)
                run.status = CapabilityRunStatus.WAITING_HUMAN

                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.STEP_WAITING_HUMAN,
                    payload={"node_id": step.node_id, "attempt": step.attempt},
                    step_execution_id=step.id,
                )
                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.RUN_WAITING_HUMAN,
                    payload={"node_id": step.node_id},
                )
                db.commit()
                return

            # 成功落库: 创建 Candidate Output Snapshot
            out_hash = calculate_json_hash(res.output)
            output_snapshot_rec = AIStepOutputSnapshot(
                step_execution_id=step.id,
                output_snapshot=res.output,
                output_hash=out_hash,
                validator_results=res.validator_results,
            )
            db.add(output_snapshot_rec)

            # 仅对 Workflow 显式声明 artifact_projection 的节点物化 P3 Candidate。
            # 物化失败必须使步骤失败，不能让未经版本化保存的模型输出伪装成成功。
            self._materialize_p3_artifact_revision_set(db, run, step, res.output)

            step.status = StepExecutionStatus.SUCCEEDED
            step.input_snapshot = (
                resolved_input if isinstance(resolved_input, dict) else {"input": resolved_input}
            )
            step.input_summary = (
                {"keys": list(resolved_input.keys())}
                if isinstance(resolved_input, dict)
                else {"type": type(resolved_input).__name__}
            )
            step.provider_name = res.provider_name
            step.model_name = res.model_name
            step.usage_snapshot = res.usage_snapshot
            step.duration_ms = duration_ms
            step.completed_at = now

            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.STEP_SUCCEEDED,
                payload={
                    "node_id": step.node_id,
                    "attempt": step.attempt,
                    "duration_ms": duration_ms,
                },
                step_execution_id=step.id,
            )

            # 解析 DAG，尝试激活下游节点
            graph = WorkflowGraph(run.execution_snapshot.get("workflow", {}))
            completed_steps = db.scalars(
                select(AIStepExecution).where(
                    AIStepExecution.run_id == run.id,
                    AIStepExecution.status == StepExecutionStatus.SUCCEEDED,
                )
            ).all()

            completed_ids = {cs.node_id for cs in completed_steps}
            completed_ids.add(step.node_id)

            # 检查终端节点是否达成
            if graph.sink_node_id in completed_ids:
                StateMachine.validate_run_transition(run.status, CapabilityRunStatus.SUCCEEDED)
                run.status = CapabilityRunStatus.SUCCEEDED
                run.final_output_snapshot_id = output_snapshot_rec.id
                run.completed_at = now

                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.RUN_SUCCEEDED,
                    payload={"completed_at": now.isoformat()},
                )
            else:
                # 为准备就绪的下游节点开启 attempt 1 的 PENDING 记录
                all_step_nodes = db.scalars(
                    select(AIStepExecution.node_id).where(AIStepExecution.run_id == run.id)
                ).all()
                existing_node_ids = set(all_step_nodes)

                pending_candidates = set(graph.nodes.keys()) - existing_node_ids
                runnable_nodes = graph.get_runnable_nodes(completed_ids, pending_candidates)

                for next_node_id in runnable_nodes:
                    n_def = graph.nodes[next_node_id]
                    new_step = AIStepExecution(
                        run_id=run.id,
                        node_id=next_node_id,
                        node_type=n_def.get("type", "").upper(),
                        node_name=n_def.get("name"),
                        attempt=1,
                        status=StepExecutionStatus.PENDING,
                    )
                    db.add(new_step)
                    db.flush()

                    EventStore.emit_event(
                        db,
                        run=run,
                        event_type=AIRunEventType.STEP_QUEUED,
                        payload={"node_id": next_node_id, "attempt": 1},
                        step_execution_id=new_step.id,
                    )

            db.commit()
        finally:
            if is_owned:
                db.close()

    def _record_step_failure(
        self,
        step_id: uuid.UUID,
        error_code: str,
        error_summary: str,
        retryable: bool = True,
        duration_ms: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        db, is_owned = self._get_db_session()
        try:
            step = db.scalar(
                select(AIStepExecution).where(AIStepExecution.id == step_id).with_for_update()
            )
            if not step:
                return

            run = db.scalar(
                select(AICapabilityRun).where(AICapabilityRun.id == step.run_id).with_for_update()
            )
            if not run:
                return

            step.status = StepExecutionStatus.FAILED
            step.error_code = error_code
            step.error_summary = error_summary
            step.duration_ms = duration_ms
            step.completed_at = now

            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.STEP_FAILED,
                payload={
                    "node_id": step.node_id,
                    "attempt": step.attempt,
                    "error_code": error_code,
                },
                step_execution_id=step.id,
            )

            # 校验重试条件
            is_non_retryable_code = error_code in {
                "RUN_INPUT_SCHEMA_INVALID",
                "RUN_VALIDATOR_FAILED",
                "RUN_HUMAN_REJECTED",
                "RUN_CAPABILITY_NOT_RUNNABLE",
            }

            can_retry = (
                retryable
                and not is_non_retryable_code
                and step.attempt < self.runtime_settings.max_attempts
            )

            if can_retry and not run.cancel_requested_at:
                next_attempt = step.attempt + 1
                backoff_sec = self.runtime_settings.retry_base_seconds ** (step.attempt - 1)
                available_at = now + timedelta(seconds=backoff_sec)

                new_step = AIStepExecution(
                    run_id=run.id,
                    node_id=step.node_id,
                    node_type=step.node_type,
                    node_name=step.node_name,
                    attempt=next_attempt,
                    status=StepExecutionStatus.PENDING,
                    available_at=available_at,
                    retry_of_id=step.id,
                    retryable=True,
                )
                db.add(new_step)

                StateMachine.validate_run_transition(run.status, CapabilityRunStatus.WAITING_RETRY)
                run.status = CapabilityRunStatus.WAITING_RETRY
                EventStore.emit_event(
                    db,
                    run=run,
                    event_type=AIRunEventType.RUN_WAITING_RETRY,
                    payload={"retry_at": available_at.isoformat()},
                )
            else:
                # 无法自动重试 -> Fail-fast，并将未开始节点设为 SKIPPED
                all_steps = db.scalars(
                    select(AIStepExecution).where(AIStepExecution.run_id == run.id)
                ).all()

                for s in all_steps:
                    if s.status == StepExecutionStatus.PENDING:
                        s.status = StepExecutionStatus.SKIPPED
                        s.completed_at = now
                        EventStore.emit_event(
                            db,
                            run=run,
                            event_type=AIRunEventType.STEP_SKIPPED,
                            payload={"node_id": s.node_id},
                            step_execution_id=s.id,
                        )

                if run.status not in {CapabilityRunStatus.FAILED, CapabilityRunStatus.CANCELLED}:
                    StateMachine.validate_run_transition(run.status, CapabilityRunStatus.FAILED)
                    run.status = CapabilityRunStatus.FAILED
                    run.error_code = error_code
                    run.error_summary = f"节点 '{step.node_id}' 执行失败: {error_summary}"
                    run.completed_at = now
                    EventStore.emit_event(
                        db,
                        run=run,
                        event_type=AIRunEventType.RUN_FAILED,
                        payload={"error_code": error_code},
                    )

            db.commit()
        finally:
            if is_owned:
                db.close()

    def _check_run_cancel_completion(
        self, db: Session, run: AICapabilityRun, now: datetime
    ) -> None:
        """检查活动中的 Step 是否已全部停止，并完成 Run 最终取消标记"""
        active_steps = db.scalars(
            select(AIStepExecution).where(
                AIStepExecution.run_id == run.id,
                AIStepExecution.status.in_(
                    [
                        StepExecutionStatus.PENDING,
                        StepExecutionStatus.RUNNING,
                        StepExecutionStatus.WAITING_HUMAN,
                    ]
                ),
            )
        ).all()

        if not active_steps:
            StateMachine.validate_run_transition(run.status, CapabilityRunStatus.CANCELLED)
            run.status = CapabilityRunStatus.CANCELLED
            run.completed_at = now
            EventStore.emit_event(
                db,
                run=run,
                event_type=AIRunEventType.RUN_CANCELLED,
                payload={"cancelled_at": now.isoformat()},
            )

    def _materialize_p3_artifact_revision_set(
        self,
        db: Session,
        run: AICapabilityRun,
        step: AIStepExecution,
        output_data: dict[str, Any],
    ) -> Any | None:
        from testweave.modules.ai_capability.revision import (
            AcceptanceService,
            ArtifactService,
            SetRevisionService,
            calculate_input_fingerprint,
            extract_items_from_output,
            generate_item_stable_key,
        )

        workflow = run.execution_snapshot.get("workflow", {})
        node_def = workflow.get("nodes", {}).get(step.node_id, {})
        projection_config = node_def.get("artifact_projection")
        if not isinstance(projection_config, dict):
            return None

        artifact_type = projection_config.get("artifact_type")
        if not isinstance(artifact_type, str) or not artifact_type:
            raise AppError(
                code="REVISION_SCHEMA_INVALID",
                message=f"节点 {step.node_id} 的 artifact_projection 缺少 artifact_type",
                status_code=400,
            )

        from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
            ArtifactSchemaValidator,
        )

        ArtifactSchemaValidator.validate_artifact(artifact_type, output_data)
        items_raw = extract_items_from_output(output_data, projection_config)

        items_and_revs = []
        for idx, raw_item in enumerate(items_raw):
            stable_key = generate_item_stable_key(raw_item, idx)
            item = ArtifactService.get_or_create_artifact_item(
                db=db,
                project_id=str(run.project_id),
                run_id=str(run.id),
                producer_node_id=step.node_id,
                artifact_type=artifact_type,
                stable_key=stable_key,
                created_by=str(run.initiator_id) if run.initiator_id else None,
            )

            rev = ArtifactService.create_artifact_revision(
                db=db,
                project_id=str(run.project_id),
                artifact_item_id=str(item.id),
                content=raw_item,
                source="INITIAL_GENERATION",
                source_step_execution_id=str(step.id),
                schema_snapshot=ArtifactSchemaValidator.get_schema(artifact_type),
                validation_snapshot={"valid": True, "artifactType": artifact_type},
                created_by=str(run.initiator_id) if run.initiator_id else None,
            )
            items_and_revs.append((item, rev))

        input_fp = calculate_input_fingerprint(
            capability_version_id=str(run.capability_version_id),
            package_fingerprint=run.execution_snapshot.get("package_fingerprint", ""),
            execution_snapshot_hash=run.execution_snapshot_hash or "",
            node_id=step.node_id,
            node_config={},
            run_input=run.input_snapshot,
            upstream_set_hashes=[],
        )

        review_policy = (
            projection_config.get("review_policy", "HUMAN_REQUIRED")
            if projection_config
            else "HUMAN_REQUIRED"
        )

        set_rev = SetRevisionService.construct_artifact_set_revision(
            db=db,
            project_id=str(run.project_id),
            run_id=str(run.id),
            producer_node_id=step.node_id,
            input_fingerprint=input_fp,
            items_and_revisions=items_and_revs,
            source_step_execution_id=str(step.id),
            review_status="CANDIDATE",
            validation_status="VALID",
        )
        step.output_revision_set_id = set_rev.id

        if step.input_context_snapshot_id:
            from testweave.db.models import AIContextSnapshot
            from testweave.modules.ai_capability.revision import DependencyService

            context = db.get(AIContextSnapshot, step.input_context_snapshot_id)
            if context:
                for upstream_node_id, manifest in context.upstream_manifest.items():
                    DependencyService.record_dependency_edge(
                        db=db,
                        project_id=str(run.project_id),
                        run_id=str(run.id),
                        upstream_node_id=upstream_node_id,
                        upstream_set_revision_id=manifest["set_revision_id"],
                        downstream_node_id=step.node_id,
                        downstream_context_snapshot_id=str(context.id),
                        downstream_step_execution_id=str(step.id),
                        downstream_output_set_revision_id=str(set_rev.id),
                    )

        EventStore.emit_event(
            db,
            run=run,
            event_type=AIRunEventType.ARTIFACT_SET_CANDIDATE_CREATED,
            payload={
                "node_id": step.node_id,
                "set_revision_id": str(set_rev.id),
                "item_count": set_rev.item_count,
                "review_status": set_rev.review_status,
            },
            step_execution_id=step.id,
        )

        if review_policy == "AUTO_ACCEPT_IF_VALID":
            AcceptanceService.accept_set_revision(db, str(set_rev.id))

        return set_rev
