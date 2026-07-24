import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactSetRevision,
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
)
from testweave.modules.ai_capability.revision.field_lock_service import FieldLockService
from testweave.modules.ai_capability.revision.propagation_service import PropagationService
from testweave.modules.ai_capability.revision.set_revision_service import SetRevisionService


class AcceptanceService:
    @staticmethod
    def accept_set_revision(
        db: Session,
        set_revision_id: str,
        expected_current_set_revision_id: str | None = None,
        user_id: str | None = None,
        workflow_dag: dict[str, list[str]] | None = None,
        decision_snapshot: dict | None = None,
    ) -> AICurrentAcceptedRevisionSet:
        set_uuid = uuid.UUID(str(set_revision_id))

        # 1. FOR UPDATE 锁定 SetRevision 与 Run
        set_rev = db.get(AIArtifactSetRevision, set_uuid, with_for_update=True)
        if not set_rev:
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message=f"SetRevision {set_revision_id} 不存在",
                status_code=404,
            )

        run = db.get(AICapabilityRun, set_rev.run_id, with_for_update=True)
        if not run:
            raise AppError(
                code="REVISION_SET_INVALID",
                message="关联的 Run 不存在",
                status_code=404,
            )

        # 校验 Run 非终态
        if run.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            raise AppError(
                code="REVISION_RUN_READ_ONLY",
                message=f"终态 Run (status={run.status}) 只读，禁止修改与接受 Revision",
                status_code=400,
            )

        # 校验 Set 状态 (必须为 CANDIDATE 且 VALID)
        if set_rev.review_status != "CANDIDATE":
            raise AppError(
                code="REVISION_SET_ALREADY_DECIDED",
                message=f"SetRevision 并非 CANDIDATE 状态 (当前: {set_rev.review_status})",
                status_code=400,
            )

        if set_rev.validation_status == "INVALID":
            raise AppError(
                code="REVISION_SET_INVALID",
                message="INVALID 的 SetRevision 禁止接受",
                status_code=400,
            )

        # 2. 校验 FieldLock
        members = SetRevisionService.get_set_revision_members(db, str(set_rev.id))
        items_and_revs = [(item, rev) for _, item, rev in members]
        FieldLockService.verify_field_locks_for_items(db, items_and_revs)

        # 3. 锁定并校验 Current Accepted 指针 (CAS 竞态防护)
        stmt_curr = (
            select(AICurrentAcceptedRevisionSet)
            .where(
                AICurrentAcceptedRevisionSet.run_id == run.id,
                AICurrentAcceptedRevisionSet.node_id == set_rev.producer_node_id,
            )
            .with_for_update()
        )
        curr_ptr = db.scalar(stmt_curr)

        if (
            expected_current_set_revision_id
            and curr_ptr
            and str(curr_ptr.current_set_revision_id) != expected_current_set_revision_id
        ):
            raise AppError(
                code="REVISION_ACCEPT_CONFLICT",
                message="基准 Current Set 已被其他请求更新，存在并发冲突",
                status_code=409,
            )

        old_set_hash = None
        if curr_ptr:
            old_set = db.get(AIArtifactSetRevision, curr_ptr.current_set_revision_id)
            if old_set:
                old_set_hash = old_set.set_hash

        # 4. 更新 SetRevision 为 ACCEPTED
        set_rev.review_status = "ACCEPTED"
        set_rev.decision_by = uuid.UUID(str(user_id)) if user_id else None
        set_rev.decision_at = datetime.now(UTC)
        set_rev.decision_snapshot = decision_snapshot

        # 5. 更新/创建 当前 Accepted 指针
        if not curr_ptr:
            curr_ptr = AICurrentAcceptedRevisionSet(
                project_id=set_rev.project_id,
                run_id=set_rev.run_id,
                node_id=set_rev.producer_node_id,
                current_set_revision_id=set_rev.id,
                acceptance_sequence=1,
                row_version=1,
                accepted_by=uuid.UUID(str(user_id)) if user_id else None,
                accepted_at=datetime.now(UTC),
                freshness_status="CURRENT",
                validation_status="VALID",
                rerun_required=False,
            )
            db.add(curr_ptr)
        else:
            curr_ptr.current_set_revision_id = set_rev.id
            curr_ptr.acceptance_sequence += 1
            curr_ptr.row_version += 1
            curr_ptr.accepted_by = uuid.UUID(str(user_id)) if user_id else None
            curr_ptr.accepted_at = datetime.now(UTC)
            curr_ptr.freshness_status = "CURRENT"
            curr_ptr.validation_status = "VALID"
            curr_ptr.rerun_required = False

        db.flush()

        # 6. 如果 Set Hash 改变，传播下游 STALE 状态
        if old_set_hash and old_set_hash != set_rev.set_hash and workflow_dag:
            PropagationService.propagate_upstream_change(
                db=db,
                run_id=str(run.id),
                upstream_node_id=set_rev.producer_node_id,
                new_upstream_set_hash=set_rev.set_hash,
                workflow_dag=workflow_dag,
            )

        return curr_ptr

    @staticmethod
    def reject_set_revision(
        db: Session,
        set_revision_id: str,
        reason: str | None = None,
        user_id: str | None = None,
    ) -> AIArtifactSetRevision:
        set_uuid = uuid.UUID(str(set_revision_id))
        set_rev = db.get(AIArtifactSetRevision, set_uuid, with_for_update=True)
        if not set_rev:
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message=f"SetRevision {set_revision_id} 不存在",
                status_code=404,
            )

        run = db.get(AICapabilityRun, set_rev.run_id)
        if run and run.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            raise AppError(
                code="REVISION_RUN_READ_ONLY",
                message="终态 Run 禁止修改/驳回 Revision",
                status_code=400,
            )

        if set_rev.review_status != "CANDIDATE":
            raise AppError(
                code="REVISION_SET_ALREADY_DECIDED",
                message=f"SetRevision 并非 CANDIDATE 状态 (当前: {set_rev.review_status})",
                status_code=400,
            )

        set_rev.review_status = "REJECTED"
        set_rev.decision_by = uuid.UUID(str(user_id)) if user_id else None
        set_rev.decision_at = datetime.now(UTC)
        set_rev.decision_reason = reason
        db.flush()
        return set_rev
