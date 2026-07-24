import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactSetRevision,
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
    AIStepExecution,
    AITestDesignRecord,
)
from testweave.modules.ai_capability.enums import HumanAction
from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    ArtifactSchemaValidator,
)
from testweave.modules.ai_capability.revision import (
    AcceptanceService,
    ArtifactService,
    FieldLockService,
    SetRevisionService,
)
from testweave.modules.ai_capability.revision.canonical_json import calculate_canonical_hash
from testweave.modules.ai_capability.revision.projection import generate_item_stable_key
from testweave.modules.ai_capability.runtime.schemas import HumanDecisionSubmitRequest
from testweave.modules.ai_capability.runtime.service import AIRuntimeService
from testweave.modules.ai_test_design.constants import STAGE_DEFINITIONS, WORKFLOW_DAG


class AiTestDesignRevisionService:
    @staticmethod
    def _stage(stage_key: str) -> dict[str, str]:
        stage = STAGE_DEFINITIONS.get(stage_key)
        if stage is None:
            raise AppError(
                code="AI_DESIGN_STAGE_NOT_FOUND",
                message="AI 测试设计阶段不存在",
                status_code=404,
            )
        return stage

    @staticmethod
    def _verify_record_run(db: Session, record: AITestDesignRecord) -> AICapabilityRun:
        run = db.get(AICapabilityRun, record.run_id)
        if run is None:
            raise AppError(
                code="AI_DESIGN_RECORD_INVALID",
                message="生成记录关联的 AI Run 不存在",
                status_code=409,
            )
        if run.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise AppError(
                code="REVISION_RUN_READ_ONLY",
                message="已结束的生成记录只读；如需继续修改请新建一轮",
                status_code=400,
            )
        return run

    @staticmethod
    def _payload_for_items(
        artifact_type: str,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if artifact_type in {
            "requirement_analysis@1.0",
            "test_case_review_report@1.0",
        }:
            if len(items) != 1:
                raise AppError(
                    code="REVISION_SET_INCOMPLETE",
                    message="需求分析和评审报告必须各包含一个完整产物",
                    status_code=400,
                )
            return items[0]
        if artifact_type == "test_point_set@1.0":
            return {"schemaVersion": "1.0", "points": items}
        if artifact_type == "test_case_set@1.0":
            return {"schemaVersion": "1.0", "cases": items}
        raise AppError(
            code="UNSUPPORTED_ARTIFACT_TYPE",
            message=f"不支持的工作台 Artifact 类型: {artifact_type}",
            status_code=400,
        )

    @classmethod
    def save_stage_revision(
        cls,
        db: Session,
        record: AITestDesignRecord,
        stage_key: str,
        base_set_revision_id: uuid.UUID,
        expected_set_hash: str,
        items: list[dict[str, Any]],
        actor_id: uuid.UUID,
    ) -> AIArtifactSetRevision:
        run = cls._verify_record_run(db, record)
        stage = cls._stage(stage_key)
        node_id = stage["nodeId"]
        artifact_type = stage["artifactType"]

        base_set = db.get(AIArtifactSetRevision, base_set_revision_id, with_for_update=True)
        if base_set is None or base_set.run_id != run.id or base_set.producer_node_id != node_id:
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message="编辑基准版本不存在或不属于当前阶段",
                status_code=404,
            )
        if base_set.set_hash != expected_set_hash:
            raise AppError(
                code="AI_DESIGN_CONTEXT_CONFLICT",
                message="当前版本已变化，请重新加载后再保存",
                status_code=409,
            )

        latest_set_id = db.scalar(
            select(AIArtifactSetRevision.id)
            .where(
                AIArtifactSetRevision.run_id == run.id,
                AIArtifactSetRevision.producer_node_id == node_id,
            )
            .order_by(AIArtifactSetRevision.set_revision_no.desc())
            .limit(1)
        )
        if latest_set_id != base_set.id:
            raise AppError(
                code="AI_DESIGN_CONTEXT_CONFLICT",
                message="编辑基准已不是最新版本，请重新加载",
                status_code=409,
            )

        payload = cls._payload_for_items(artifact_type, items)
        ArtifactSchemaValidator.validate_artifact(artifact_type, payload)
        base_members = SetRevisionService.get_set_revision_members(db, str(base_set.id))
        base_by_key = {item.stable_key: (item, revision) for _, item, revision in base_members}

        stable_keys: set[str] = set()
        items_and_revisions = []
        strict_schema = ArtifactSchemaValidator.get_workbench_schema(artifact_type)
        for index, content in enumerate(items):
            stable_key = generate_item_stable_key(content, index)
            if stable_key in stable_keys:
                raise AppError(
                    code="REVISION_SET_INVALID",
                    message=f"完整集合中存在重复 stableKey: {stable_key}",
                    status_code=400,
                )
            stable_keys.add(stable_key)
            base_pair = base_by_key.get(stable_key)
            item = ArtifactService.get_or_create_artifact_item(
                db=db,
                project_id=str(record.project_id),
                run_id=str(run.id),
                producer_node_id=node_id,
                artifact_type=artifact_type,
                stable_key=stable_key,
                created_by=str(actor_id),
            )
            if base_pair and base_pair[1].content_hash == calculate_canonical_hash(content):
                revision = base_pair[1]
            else:
                parent_ids = [str(base_pair[1].id)] if base_pair else None
                revision = ArtifactService.create_artifact_revision(
                    db=db,
                    project_id=str(record.project_id),
                    artifact_item_id=str(item.id),
                    content=content,
                    source="USER_EDIT",
                    parent_revision_ids=parent_ids,
                    schema_snapshot=strict_schema,
                    validation_snapshot={"valid": True, "artifactType": artifact_type},
                    created_by=str(actor_id),
                )
            items_and_revisions.append((item, revision))

        FieldLockService.verify_field_locks_for_items(db, items_and_revisions)
        new_set = SetRevisionService.construct_artifact_set_revision(
            db=db,
            project_id=str(record.project_id),
            run_id=str(run.id),
            producer_node_id=node_id,
            input_fingerprint=base_set.input_fingerprint,
            items_and_revisions=items_and_revisions,
            base_set_revision_id=str(base_set.id),
            review_status="CANDIDATE",
            validation_status="VALID",
            validation_snapshot={"valid": True, "artifactType": artifact_type},
        )
        if base_set.review_status == "CANDIDATE":
            base_set.review_status = "SUPERSEDED"
        record.row_version += 1
        record.updated_at = datetime.now(UTC)
        db.flush()
        return new_set

    @staticmethod
    def _validate_human_gate(
        stage_key: str,
        contents: list[dict[str, Any]],
    ) -> None:
        if stage_key == "requirement-analysis":
            unresolved = [
                question.get("id")
                for question in contents[0].get("questions", [])
                if question.get("blocking") and question.get("status") == "PENDING"
            ]
            if unresolved:
                raise AppError(
                    code="AI_DESIGN_BLOCKING_QUESTIONS",
                    message=f"仍有 {len(unresolved)} 个阻塞问题未处理，不能进入测试点生成",
                    status_code=400,
                )
        elif stage_key == "test-points":
            if not any(content.get("allowCaseGeneration") is True for content in contents):
                raise AppError(
                    code="AI_DESIGN_TEST_POINT_SELECTION_REQUIRED",
                    message="请至少选择一个允许生成用例的测试点",
                    status_code=400,
                )
        elif stage_key == "case-review":
            findings = contents[0].get("findings", [])
            pending = [
                finding.get("stableKey")
                for finding in findings
                if finding.get("decision") == "PENDING"
            ]
            if pending:
                raise AppError(
                    code="AI_DESIGN_FINDING_DECISION_REQUIRED",
                    message=f"仍有 {len(pending)} 条 Finding 未处理",
                    status_code=400,
                )
            rejected_without_reason = [
                finding.get("stableKey")
                for finding in findings
                if finding.get("decision") == "REJECTED"
                and not str(finding.get("decisionReason", "")).strip()
            ]
            if rejected_without_reason:
                raise AppError(
                    code="AI_DESIGN_FINDING_REJECTION_REASON_REQUIRED",
                    message="驳回 Finding 时必须填写人工决策原因",
                    status_code=400,
                )

    @classmethod
    def accept_stage(
        cls,
        db: Session,
        record: AITestDesignRecord,
        stage_key: str,
        set_revision_id: uuid.UUID,
        expected_current_set_revision_id: str | None,
        decision_snapshot: dict[str, Any],
        actor_id: uuid.UUID,
        actor_permissions: set[str],
    ) -> AICurrentAcceptedRevisionSet:
        run = cls._verify_record_run(db, record)
        stage = cls._stage(stage_key)
        set_revision = db.get(AIArtifactSetRevision, set_revision_id)
        if (
            set_revision is None
            or set_revision.run_id != run.id
            or set_revision.producer_node_id != stage["nodeId"]
        ):
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message="候选版本不存在或不属于当前阶段",
                status_code=404,
            )
        latest_set_id = db.scalar(
            select(AIArtifactSetRevision.id)
            .where(
                AIArtifactSetRevision.run_id == run.id,
                AIArtifactSetRevision.producer_node_id == stage["nodeId"],
            )
            .order_by(AIArtifactSetRevision.set_revision_no.desc())
            .limit(1)
        )
        if latest_set_id != set_revision.id:
            raise AppError(
                code="AI_DESIGN_CONTEXT_CONFLICT",
                message="候选版本已不是当前最新版本，请重新加载",
                status_code=409,
            )
        current_pointer = db.scalar(
            select(AICurrentAcceptedRevisionSet).where(
                AICurrentAcceptedRevisionSet.run_id == run.id,
                AICurrentAcceptedRevisionSet.node_id == stage["nodeId"],
            )
        )
        current_id = str(current_pointer.current_set_revision_id) if current_pointer else None
        if current_id != expected_current_set_revision_id:
            raise AppError(
                code="AI_DESIGN_CONTEXT_CONFLICT",
                message="当前已接受版本已变化，请重新加载后再确认",
                status_code=409,
            )
        members = SetRevisionService.get_set_revision_members(db, str(set_revision.id))
        contents = [revision.content for _, _, revision in members]
        cls._validate_human_gate(stage_key, contents)

        accepted = AcceptanceService.accept_set_revision(
            db=db,
            set_revision_id=str(set_revision.id),
            expected_current_set_revision_id=expected_current_set_revision_id,
            user_id=str(actor_id),
            workflow_dag=WORKFLOW_DAG,
            decision_snapshot=decision_snapshot,
        )

        gate_step = db.scalar(
            select(AIStepExecution)
            .where(
                AIStepExecution.run_id == run.id,
                AIStepExecution.node_id == stage["gateNodeId"],
            )
            .order_by(AIStepExecution.attempt.desc())
            .limit(1)
        )
        if gate_step and gate_step.status == "WAITING_HUMAN":
            accepted_items = contents
            if stage_key == "test-points":
                accepted_items = [
                    content for content in contents if content.get("allowCaseGeneration") is True
                ]
            decision = {
                "acceptedSetRevisionId": str(set_revision.id),
                "acceptedSetHash": set_revision.set_hash,
                "acceptedItems": accepted_items,
                "decisionSnapshot": decision_snapshot,
            }
            AIRuntimeService.submit_human_decision(
                db=db,
                project_id=record.project_id,
                run_id=run.id,
                step_execution_id=gate_step.id,
                request=HumanDecisionSubmitRequest(
                    action=HumanAction.CONTINUE,
                    decision=decision,
                ),
                actor_id=actor_id,
                actor_permissions=actor_permissions,
            )
        else:
            db.commit()
        return accepted
