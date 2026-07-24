import contextlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapabilityRun,
    AITestDesignRecord,
    Requirement,
    RequirementAttachment,
    TestTask,
    TestTaskRequirement,
)
from testweave.modules.ai_capability.enums import AIRunMode
from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
from testweave.modules.ai_capability.runtime.schemas import AIRunCreateRequest
from testweave.modules.ai_capability.runtime.service import AIRuntimeService
from testweave.modules.ai_capability.runtime.snapshots import calculate_json_hash
from testweave.modules.ai_test_design.builtin_capability import (
    BuiltinAiTestDesignCapabilityService,
)
from testweave.modules.attachments.text_extractor import extract_attachment_text


class AiTestDesignService:
    @staticmethod
    def _get_task_and_requirement(
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        lock_task: bool = False,
    ) -> tuple[TestTask, Requirement]:
        task_stmt = select(TestTask).where(
            TestTask.id == task_id,
            TestTask.project_id == project_id,
        )
        if lock_task:
            task_stmt = task_stmt.with_for_update()
        task = db.scalar(task_stmt)
        if task is None:
            raise AppError(
                code="AI_DESIGN_TASK_NOT_FOUND",
                message="用例设计任务不存在或不属于当前项目",
                status_code=404,
            )
        if task.task_type != "CASE_DESIGN":
            raise AppError(
                code="AI_DESIGN_TASK_TYPE_INVALID",
                message="只有用例设计任务可以创建 AI 测试设计记录",
                status_code=400,
            )

        requirement_rows = (
            db.execute(
                select(Requirement)
                .join(TestTaskRequirement, TestTaskRequirement.requirement_id == Requirement.id)
                .where(
                    TestTaskRequirement.task_id == task.id,
                    Requirement.project_id == project_id,
                )
            )
            .scalars()
            .all()
        )
        if len(requirement_rows) != 1:
            raise AppError(
                code="AI_DESIGN_REQUIREMENT_REQUIRED",
                message="AI 测试设计要求任务恰好关联一个需求",
                status_code=400,
            )
        return task, requirement_rows[0]

    @staticmethod
    def _build_run_input(
        db: Session,
        task: TestTask,
        requirement: Requirement,
        review_mode: str,
    ) -> dict:
        attachments = db.scalars(
            select(RequirementAttachment)
            .where(
                RequirementAttachment.requirement_id == requirement.id,
                RequirementAttachment.project_id == requirement.project_id,
                RequirementAttachment.status == "ACTIVE",
            )
            .order_by(RequirementAttachment.uploaded_at.asc())
        ).all()
        return {
            "task": {
                "id": str(task.id),
                "taskNo": task.task_no,
                "title": task.title,
                "description": task.description,
                "testGoal": task.test_goal,
                "excludedScope": task.excluded_scope,
            },
            "requirement": {
                "id": str(requirement.id),
                "requirementNo": requirement.requirement_no,
                "title": requirement.title,
                "description": requirement.description,
                "acceptanceCriteria": requirement.acceptance_criteria,
                "priority": requirement.priority,
                "updatedAt": requirement.updated_at.isoformat(),
            },
            "attachments": [
                {
                    "id": str(attachment.id),
                    "fileName": attachment.original_filename,
                    "contentType": attachment.content_type,
                    "description": attachment.description,
                    "sha256": attachment.sha256,
                    "extractedText": extract_attachment_text(attachment.storage_key),
                }
                for attachment in attachments
            ],
            "reviewMode": review_mode,
        }

    @classmethod
    def create_record(
        cls,
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_permissions: set[str],
        idempotency_key: str,
        runtime_settings: AIRuntimeSettings,
        review_mode: str = "TRACEABLE",
    ) -> tuple[AITestDesignRecord, bool]:
        clean_key = idempotency_key.strip()
        if not clean_key:
            raise AppError(
                code="AI_DESIGN_IDEMPOTENCY_REQUIRED",
                message="新建生成记录必须提供 Idempotency-Key",
                status_code=400,
            )
        if len(clean_key) > 128:
            raise AppError(
                code="AI_DESIGN_IDEMPOTENCY_INVALID",
                message="Idempotency-Key 长度不能超过 128 个字符",
                status_code=400,
            )
        if review_mode not in {"TRACEABLE", "INTRINSIC"}:
            raise AppError(
                code="AI_DESIGN_REVIEW_MODE_INVALID",
                message="评审模式只支持 TRACEABLE 或 INTRINSIC",
                status_code=400,
            )

        existing = db.scalar(
            select(AITestDesignRecord).where(
                AITestDesignRecord.task_id == task_id,
                AITestDesignRecord.created_by == actor_id,
                AITestDesignRecord.idempotency_key == clean_key,
            )
        )
        if existing is not None:
            if existing.project_id != project_id:
                raise AppError(
                    code="AI_DESIGN_IDEMPOTENCY_CONFLICT",
                    message="相同 Idempotency-Key 已用于其他项目",
                    status_code=409,
                )
            return existing, False

        task, requirement = cls._get_task_and_requirement(db, project_id, task_id, lock_task=True)
        capability = BuiltinAiTestDesignCapabilityService.ensure_published(db, actor_id)
        run_input = cls._build_run_input(db, task, requirement, review_mode)
        # 释放该任务下所有旧生成链轮次的活跃运行并发数，标记为成功，以释放运行并发限额并规避 RUN_BUDGET_EXCEEDED 限制
        from testweave.db.models import AICapabilityRun
        from testweave.modules.ai_capability.enums import CapabilityRunStatus

        old_run_ids = db.scalars(
            select(AITestDesignRecord.run_id).where(AITestDesignRecord.task_id == task_id)
        ).all()
        if old_run_ids:
            db.query(AICapabilityRun).filter(
                AICapabilityRun.id.in_(old_run_ids),
                AICapabilityRun.status.in_(
                    [
                        CapabilityRunStatus.PENDING,
                        CapabilityRunStatus.RUNNING,
                        CapabilityRunStatus.WAITING_HUMAN,
                        CapabilityRunStatus.WAITING_RETRY,
                    ]
                ),
            ).update({"status": CapabilityRunStatus.SUCCEEDED}, synchronize_session="fetch")
            db.flush()

        runtime_key = f"ai-design-{calculate_json_hash({'task': str(task_id), 'key': clean_key})}"
        run, run_created = AIRuntimeService.create_run(
            db=db,
            project_id=project_id,
            capability_id=capability.id,
            request=AIRunCreateRequest(runMode=AIRunMode.NORMAL, input=run_input),
            idempotency_key=runtime_key,
            actor_id=actor_id,
            actor_permissions=actor_permissions,
            runtime_settings=runtime_settings,
        )

        record_for_run = db.scalar(
            select(AITestDesignRecord).where(AITestDesignRecord.run_id == run.id)
        )
        if record_for_run is not None:
            return record_for_run, False

        # Runtime 会提交创建事务，因此这里重新锁定任务，串行分配轮次号。
        db.scalar(select(TestTask).where(TestTask.id == task.id).with_for_update())
        max_record_no = (
            db.scalar(
                select(func.max(AITestDesignRecord.record_no)).where(
                    AITestDesignRecord.project_id == project_id,
                    AITestDesignRecord.task_id == task_id,
                )
            )
            or 0
        )
        record_no = max_record_no + 1
        record = AITestDesignRecord(
            project_id=project_id,
            task_id=task_id,
            run_id=run.id,
            record_no=record_no,
            title=f"第 {record_no} 轮 · {task.title}",
            idempotency_key=clean_key,
            last_opened_stage="requirement-analysis",
            created_by=actor_id,
        )
        db.add(record)
        db.commit()
        return record, run_created

    @staticmethod
    def list_records(
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        can_manage: bool = False,
    ) -> list[AITestDesignRecord]:
        stmt = select(AITestDesignRecord).where(
            AITestDesignRecord.project_id == project_id,
            AITestDesignRecord.task_id == task_id,
        )
        records = list(db.scalars(stmt.order_by(AITestDesignRecord.record_no.desc())).all())
        if not records:
            # 自动补偿检查：如果当前任务尚无生成记录，尝试查询 candidate_submissions 是否存在待挂载产物
            from testweave.db.models import CandidateSubmission
            from testweave.modules.ai_capability.external_agent.external_candidate_bridge_service import (
                ExternalCandidateBridgeService,
            )

            unmounted_subs = list(
                db.scalars(
                    select(CandidateSubmission)
                    .where(
                        CandidateSubmission.project_id == project_id,
                        (CandidateSubmission.task_id == task_id)
                        | (CandidateSubmission.task_id.is_(None)),
                    )
                    .order_by(CandidateSubmission.created_at.asc())
                ).all()
            )
            if unmounted_subs:
                for sub in unmounted_subs:
                    if not sub.task_id:
                        sub.task_id = task_id
                        db.add(sub)
                    with contextlib.suppress(Exception):
                        ExternalCandidateBridgeService.mount_candidate_set_revision(
                            db=db,
                            project_id=project_id,
                            task_id=task_id,
                            user_id=sub.submitted_by_user_id,
                            artifact_type=sub.artifact_type,
                            validated_payload=sub.payload_json,
                            submission_id=sub.id,
                        )
                db.commit()
                records = list(db.scalars(stmt.order_by(AITestDesignRecord.record_no.desc())).all())

        # 仅当存在多个轮次时，过滤掉那些没有任何候选版本产物的旧历史轮次，最新一轮必须保留
        if len(records) > 1:
            from testweave.db.models import AIArtifactSetRevision

            latest_record = records[0]
            filtered = [latest_record]
            for r in records[1:]:
                has_set = (
                    db.scalar(
                        select(AIArtifactSetRevision.id)
                        .where(AIArtifactSetRevision.run_id == r.run_id)
                        .limit(1)
                    )
                    is not None
                )
                if has_set:
                    filtered.append(r)
            records = filtered

        return records

    @classmethod
    def get_resume_record(
        cls,
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor_id: uuid.UUID,
        can_manage: bool = False,
    ) -> AITestDesignRecord | None:
        records = cls.list_records(db, project_id, task_id, actor_id, can_manage)
        if not records:
            return None
        run_ids = [record.run_id for record in records]
        active_run_ids = set(
            db.scalars(
                select(AICapabilityRun.id).where(
                    AICapabilityRun.id.in_(run_ids),
                    AICapabilityRun.status.not_in(["SUCCEEDED", "CANCELLED"]),
                )
            ).all()
        )
        return next((record for record in records if record.run_id in active_run_ids), records[0])

    @classmethod
    def delete_record(cls, db: Session, record: AITestDesignRecord) -> None:
        from testweave.db.models import (
            AIArtifactSetRevision,
            AIArtifactSetRevisionMember,
            AICapabilityRun,
            AICurrentAcceptedRevisionSet,
        )
        from testweave.modules.ai_capability.enums import CapabilityRunStatus

        # 1. 物理删除所有 accepted 状态指针
        db.query(AICurrentAcceptedRevisionSet).filter(
            AICurrentAcceptedRevisionSet.run_id == record.run_id
        ).delete()

        # 2. 物理删除 set revisions 关联的 members 关系
        set_ids = db.scalars(
            select(AIArtifactSetRevision.id).where(AIArtifactSetRevision.run_id == record.run_id)
        ).all()
        if set_ids:
            db.query(AIArtifactSetRevisionMember).filter(
                AIArtifactSetRevisionMember.set_revision_id.in_(set_ids)
            ).delete()

        # 3. 物理删除 set revisions
        db.query(AIArtifactSetRevision).filter(
            AIArtifactSetRevision.run_id == record.run_id
        ).delete()

        # 4. 强制将对应的 CapabilityRun 状态修改为 SUCCEEDED，释放其对运行并发指标的占用
        db.query(AICapabilityRun).filter(AICapabilityRun.id == record.run_id).update(
            {"status": CapabilityRunStatus.SUCCEEDED}, synchronize_session="fetch"
        )

        # 5. 物理删除该 AI 测试设计生成轮次
        db.delete(record)
        db.commit()
