import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactSetRevision,
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
    AIFeedback,
    AIFieldLock,
    AIRegenerationRequest,
    AIStepExecution,
    AITestDesignRecord,
)
from testweave.modules.ai_capability.revision import FeedbackService, SetRevisionService
from testweave.modules.ai_test_design.constants import STAGE_DEFINITIONS


class AiTestDesignQueryService:
    @staticmethod
    def get_record(
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        record_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        can_manage: bool = False,
    ) -> AITestDesignRecord:
        record = db.get(AITestDesignRecord, record_id)
        if record is None or record.project_id != project_id or record.task_id != task_id:
            raise AppError(
                code="AI_DESIGN_RECORD_NOT_FOUND",
                message="生成记录不存在或无权访问",
                status_code=404,
            )
        return record

    @staticmethod
    def _latest_steps(db: Session, run_id: uuid.UUID) -> dict[str, AIStepExecution]:
        steps = db.scalars(
            select(AIStepExecution)
            .where(AIStepExecution.run_id == run_id)
            .order_by(AIStepExecution.node_id.asc(), AIStepExecution.attempt.desc())
        ).all()
        latest: dict[str, AIStepExecution] = {}
        for step in steps:
            latest.setdefault(step.node_id, step)
        return latest

    @staticmethod
    def _all_sets(db: Session, run_id: uuid.UUID) -> dict[str, list[AIArtifactSetRevision]]:
        sets = db.scalars(
            select(AIArtifactSetRevision)
            .where(AIArtifactSetRevision.run_id == run_id)
            .order_by(
                AIArtifactSetRevision.producer_node_id.asc(),
                AIArtifactSetRevision.set_revision_no.desc(),
            )
        ).all()
        grouped: dict[str, list[AIArtifactSetRevision]] = {}
        for set_revision in sets:
            grouped.setdefault(set_revision.producer_node_id, []).append(set_revision)
        return grouped

    @staticmethod
    def _accepted_sets(db: Session, run_id: uuid.UUID) -> dict[str, AICurrentAcceptedRevisionSet]:
        return {
            accepted.node_id: accepted
            for accepted in db.scalars(
                select(AICurrentAcceptedRevisionSet).where(
                    AICurrentAcceptedRevisionSet.run_id == run_id
                )
            ).all()
        }

    @staticmethod
    def _stage_status(
        stage: dict[str, str],
        run: AICapabilityRun,
        latest_steps: dict[str, AIStepExecution],
        node_sets: list[AIArtifactSetRevision],
        accepted: AICurrentAcceptedRevisionSet | None,
    ) -> str:
        step = latest_steps.get(stage["nodeId"])
        gate = latest_steps.get(stage["gateNodeId"])
        if accepted and accepted.freshness_status == "STALE":
            return "STALE"
        if accepted and accepted.rerun_required:
            return "RERUN_REQUIRED"
        if step and step.status == "FAILED":
            return "GENERATION_FAILED"
        if step and step.status in {"PENDING", "RUNNING", "WAITING_RETRY"}:
            return "GENERATING"
        latest_candidate = next(
            (
                set_revision
                for set_revision in node_sets
                if set_revision.review_status == "CANDIDATE"
            ),
            None,
        )
        if latest_candidate:
            if gate and gate.status == "WAITING_HUMAN":
                return "WAITING_HUMAN"
            return "CANDIDATE"
        if accepted:
            return "ACCEPTED"
        if run.status == "FAILED" and step:
            return "GENERATION_FAILED"
        return "NOT_GENERATED"

    @classmethod
    def summarize_record(cls, db: Session, record: AITestDesignRecord) -> dict[str, Any]:
        run = db.get(AICapabilityRun, record.run_id)
        if run is None:
            raise AppError(
                code="AI_DESIGN_RECORD_INVALID",
                message="生成记录关联的 AI Run 不存在",
                status_code=409,
            )
        latest_steps = cls._latest_steps(db, run.id)
        sets_by_node = cls._all_sets(db, run.id)
        accepted_by_node = cls._accepted_sets(db, run.id)
        stages = []
        for stage_key, stage in STAGE_DEFINITIONS.items():
            node_sets = sets_by_node.get(stage["nodeId"], [])
            accepted = accepted_by_node.get(stage["nodeId"])
            stages.append(
                {
                    "key": stage_key,
                    "label": stage["label"],
                    "status": cls._stage_status(stage, run, latest_steps, node_sets, accepted),
                    "revisionCount": len(node_sets),
                }
            )
        current_stage = next(
            (
                stage["key"]
                for stage in stages
                if stage["status"]
                in {
                    "NOT_GENERATED",
                    "GENERATING",
                    "WAITING_HUMAN",
                    "CANDIDATE",
                    "STALE",
                    "RERUN_REQUIRED",
                    "GENERATION_FAILED",
                }
            ),
            "case-review",
        )
        record_status = {
            "SUCCEEDED": "COMPLETED",
            "CANCELLED": "CANCELLED",
            "FAILED": "FAILED",
            "WAITING_HUMAN": "WAITING_HUMAN",
            "WAITING_RETRY": "RERUN_REQUIRED",
        }.get(run.status, "IN_PROGRESS")
        created_at_val = (
            record.created_at.isoformat()
            if hasattr(record.created_at, "isoformat")
            else str(record.created_at)
        )

        def _get_ts(dt):
            if dt is None:
                return 0.0
            return dt.timestamp() if hasattr(dt, "timestamp") else 0.0

        max_updated = (
            record.updated_at
            if _get_ts(record.updated_at) >= _get_ts(run.updated_at)
            else run.updated_at
        )
        updated_at_val = (
            max_updated.isoformat() if hasattr(max_updated, "isoformat") else str(max_updated)
        )

        return {
            "id": str(record.id),
            "recordNo": record.record_no,
            "title": record.title,
            "status": record_status,
            "runId": str(run.id),
            "runStatus": run.status,
            "currentStage": current_stage,
            "lastOpenedStage": record.last_opened_stage,
            "rowVersion": record.row_version,
            "stages": stages,
            "errorCode": run.error_code,
            "errorSummary": run.error_summary,
            "createdBy": str(record.created_by),
            "createdAt": created_at_val,
            "updatedAt": updated_at_val,
        }

    @staticmethod
    def _set_detail(
        db: Session, set_revision: AIArtifactSetRevision | None
    ) -> dict[str, Any] | None:
        if set_revision is None:
            return None
        members = SetRevisionService.get_set_revision_members(db, str(set_revision.id))
        return {
            "id": str(set_revision.id),
            "revisionNo": set_revision.set_revision_no,
            "baseSetRevisionId": (
                str(set_revision.base_set_revision_id)
                if set_revision.base_set_revision_id
                else None
            ),
            "setHash": set_revision.set_hash,
            "inputContextHash": set_revision.input_fingerprint,
            "itemCount": set_revision.item_count,
            "reviewStatus": set_revision.review_status,
            "validationStatus": set_revision.validation_status,
            "decisionSnapshot": set_revision.decision_snapshot,
            "createdAt": set_revision.created_at.isoformat()
            if hasattr(set_revision.created_at, "isoformat")
            else str(set_revision.created_at),
            "items": [
                {
                    "position": member.position,
                    "itemId": str(item.id),
                    "stableKey": item.stable_key,
                    "artifactType": item.artifact_type,
                    "revisionId": str(revision.id),
                    "revisionNo": revision.revision_no,
                    "source": revision.source,
                    "contentHash": revision.content_hash,
                    "content": revision.content,
                    "createdAt": revision.created_at.isoformat()
                    if hasattr(revision.created_at, "isoformat")
                    else str(revision.created_at),
                }
                for member, item, revision in members
            ],
        }

    @classmethod
    def get_workbench_state(
        cls,
        db: Session,
        record: AITestDesignRecord,
        stage_key: str,
    ) -> dict[str, Any]:
        stage = STAGE_DEFINITIONS.get(stage_key)
        if stage is None:
            raise AppError(
                code="AI_DESIGN_STAGE_NOT_FOUND",
                message="AI 测试设计阶段不存在",
                status_code=404,
            )
        run = db.get(AICapabilityRun, record.run_id)
        if run is None:
            raise AppError(
                code="AI_DESIGN_RECORD_INVALID",
                message="生成记录关联的 AI Run 不存在",
                status_code=409,
            )
        latest_steps = cls._latest_steps(db, run.id)
        sets_by_node = cls._all_sets(db, run.id)
        accepted_by_node = cls._accepted_sets(db, run.id)
        node_id = stage["nodeId"]
        node_sets = sets_by_node.get(node_id, [])
        accepted_pointer = accepted_by_node.get(node_id)
        accepted_set = (
            db.get(AIArtifactSetRevision, accepted_pointer.current_set_revision_id)
            if accepted_pointer
            else None
        )
        candidate_set = next(
            (
                set_revision
                for set_revision in node_sets
                if set_revision.review_status == "CANDIDATE"
            ),
            None,
        )
        stage_status = cls._stage_status(stage, run, latest_steps, node_sets, accepted_pointer)

        node_item_ids = set(
            db.scalars(
                select(AIArtifactItem.id).where(
                    AIArtifactItem.run_id == run.id,
                    AIArtifactItem.producer_node_id == node_id,
                )
            ).all()
        )
        node_step_ids = set(
            db.scalars(
                select(AIStepExecution.id).where(
                    AIStepExecution.run_id == run.id,
                    AIStepExecution.node_id.in_([node_id, stage["gateNodeId"]]),
                )
            ).all()
        )
        feedbacks = [
            feedback
            for feedback in db.scalars(
                select(AIFeedback)
                .where(AIFeedback.run_id == run.id, AIFeedback.status == "ACTIVE")
                .order_by(AIFeedback.created_at.desc())
            ).all()
            if feedback.target_item_id in node_item_ids
            or feedback.target_step_execution_id in node_step_ids
        ]
        locks = db.scalars(
            select(AIFieldLock)
            .where(
                AIFieldLock.run_id == run.id,
                AIFieldLock.node_id == node_id,
                AIFieldLock.status == "ACTIVE",
            )
            .order_by(AIFieldLock.created_at.desc())
        ).all()
        regeneration_requests = db.scalars(
            select(AIRegenerationRequest)
            .where(
                AIRegenerationRequest.run_id == run.id,
                AIRegenerationRequest.node_id == node_id,
            )
            .order_by(AIRegenerationRequest.created_at.desc())
        ).all()
        steps = [
            step for step in latest_steps.values() if step.node_id in {node_id, stage["gateNodeId"]}
        ]
        record_summary = cls.summarize_record(db, record)
        return {
            "record": record_summary,
            "source": run.input_snapshot,
            "stage": {
                "key": stage_key,
                "label": stage["label"],
                "nodeId": node_id,
                "artifactType": stage["artifactType"],
                "status": stage_status,
                "candidateRevision": cls._set_detail(db, candidate_set),
                "acceptedRevision": cls._set_detail(db, accepted_set),
                "acceptedState": (
                    {
                        "freshnessStatus": accepted_pointer.freshness_status,
                        "rerunRequired": accepted_pointer.rerun_required,
                        "rowVersion": accepted_pointer.row_version,
                        "stateReasons": accepted_pointer.state_reasons,
                    }
                    if accepted_pointer
                    else None
                ),
                "revisionHistory": [
                    {
                        "id": str(set_revision.id),
                        "revisionNo": set_revision.set_revision_no,
                        "baseSetRevisionId": (
                            str(set_revision.base_set_revision_id)
                            if set_revision.base_set_revision_id
                            else None
                        ),
                        "setHash": set_revision.set_hash,
                        "reviewStatus": set_revision.review_status,
                        "validationStatus": set_revision.validation_status,
                        "decisionSnapshot": set_revision.decision_snapshot,
                        "itemCount": set_revision.item_count,
                        "createdAt": set_revision.created_at,
                    }
                    for set_revision in node_sets
                ],
                "steps": [
                    {
                        "id": str(step.id),
                        "nodeId": step.node_id,
                        "nodeName": step.node_name,
                        "attempt": step.attempt,
                        "status": step.status,
                        "retryable": step.retryable,
                        "errorCode": step.error_code,
                        "errorSummary": step.error_summary,
                        "startedAt": step.started_at,
                        "completedAt": step.completed_at,
                    }
                    for step in sorted(steps, key=lambda item: item.created_at)
                ],
                "fieldLocks": [
                    {
                        "id": str(lock.id),
                        "itemId": str(lock.artifact_item_id),
                        "revisionId": str(lock.anchor_revision_id),
                        "jsonPointer": lock.json_pointer,
                        "status": lock.status,
                        "createdAt": lock.created_at,
                    }
                    for lock in locks
                ],
                "feedback": [
                    {
                        "id": str(feedback.id),
                        "targetType": feedback.target_type,
                        "targetItemId": (
                            str(feedback.target_item_id) if feedback.target_item_id else None
                        ),
                        "targetRevisionId": (
                            str(feedback.target_revision_id)
                            if feedback.target_revision_id
                            else None
                        ),
                        "jsonPointer": feedback.json_pointer,
                        "category": feedback.category,
                        "comment": feedback.comment,
                        "changeSnapshot": FeedbackService.build_change_snapshot(db, feedback),
                        "createdAt": feedback.created_at,
                    }
                    for feedback in feedbacks
                ],
                "regenerationRequests": [
                    {
                        "id": str(request.id),
                        "status": request.status,
                        "baseSetRevisionId": str(request.base_set_revision_id),
                        "resultSetRevisionId": (
                            str(request.result_set_revision_id)
                            if request.result_set_revision_id
                            else None
                        ),
                        "errorCode": request.error_code,
                        "errorSummary": request.error_summary,
                        "createdAt": request.created_at,
                    }
                    for request in regeneration_requests
                ],
            },
            "run": {
                "id": str(run.id),
                "status": run.status,
                "errorCode": run.error_code,
                "errorSummary": run.error_summary,
                "startedAt": run.started_at,
                "completedAt": run.completed_at,
                "createdAt": run.created_at,
            },
            "allowedActions": {
                "canEdit": run.status not in {"SUCCEEDED", "FAILED", "CANCELLED"},
                "canAccept": run.status not in {"SUCCEEDED", "FAILED", "CANCELLED"},
                "canFeedback": run.status not in {"SUCCEEDED", "FAILED", "CANCELLED"},
                "canRegenerate": run.status not in {"SUCCEEDED", "FAILED", "CANCELLED"},
                "canRetry": any(step.status == "FAILED" and step.retryable for step in steps),
            },
        }
