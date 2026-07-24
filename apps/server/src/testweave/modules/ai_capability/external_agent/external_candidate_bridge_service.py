import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import AITestDesignRecord, TestTask
from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    ArtifactSchemaValidator,
)
from testweave.modules.ai_capability.revision.artifact_service import ArtifactService
from testweave.modules.ai_capability.revision.projection import generate_item_stable_key
from testweave.modules.ai_capability.revision.set_revision_service import SetRevisionService
from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
from testweave.modules.ai_test_design.constants import STAGE_DEFINITIONS
from testweave.modules.ai_test_design.service import AiTestDesignService


class ExternalCandidateBridgeService:
    @classmethod
    def resolve_task(
        cls,
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        task_key: str | None = None,
        requirement_id: uuid.UUID | None = None,
        requirement_key: str | None = None,
    ) -> TestTask | None:
        from sqlalchemy import func

        from testweave.db.models import Requirement, TestTaskRequirement

        # 1. 尝试按 task_id
        if task_id:
            task = db.get(TestTask, task_id)
            if task and task.project_id == project_id:
                return task

        # 2. 尝试按 task_key 匹配
        if task_key and str(task_key).strip():
            clean_key = str(task_key).strip()

            # 2.1 按 task_no (忽略大小写)
            stmt = select(TestTask).where(
                TestTask.project_id == project_id,
                func.lower(TestTask.task_no) == clean_key.lower(),
            )
            task = db.scalar(stmt)
            if task:
                return task

            # 2.2 尝试 UUID 解析
            try:
                task_uuid = uuid.UUID(clean_key)
                task = db.get(TestTask, task_uuid)
                if task and task.project_id == project_id:
                    return task
            except ValueError:
                pass

            # 2.3 尝试看 task_key 是否为 Requirement 的 Key (例如外部 Agent 误将需求单号传在 taskKey)
            stmt_req = select(Requirement).where(
                Requirement.project_id == project_id,
                func.lower(Requirement.requirement_no) == clean_key.lower(),
            )
            req = db.scalar(stmt_req)
            if req:
                stmt_task = (
                    select(TestTask)
                    .join(TestTaskRequirement, TestTaskRequirement.task_id == TestTask.id)
                    .where(
                        TestTask.project_id == project_id,
                        TestTaskRequirement.requirement_id == req.id,
                    )
                )
                task = db.scalar(stmt_task)
                if task:
                    return task

        # 3. 尝试按 requirement_id 或 requirement_key 匹配
        if requirement_id or (requirement_key and str(requirement_key).strip()):
            req = None
            if requirement_id:
                req = db.get(Requirement, requirement_id)
            elif requirement_key and str(requirement_key).strip():
                clean_req_key = str(requirement_key).strip()
                stmt_req = select(Requirement).where(
                    Requirement.project_id == project_id,
                    func.lower(Requirement.requirement_no) == clean_req_key.lower(),
                )
                req = db.scalar(stmt_req)

            if req and req.project_id == project_id:
                stmt_task = (
                    select(TestTask)
                    .join(TestTaskRequirement, TestTaskRequirement.task_id == TestTask.id)
                    .where(
                        TestTask.project_id == project_id,
                        TestTaskRequirement.requirement_id == req.id,
                    )
                )
                task = db.scalar(stmt_task)
                if task:
                    return task

        # 4. 智能兜底：如果项目包含 CASE_DESIGN 类型的用例设计任务，自动定位至最新任务
        stmt_default = (
            select(TestTask)
            .where(
                TestTask.project_id == project_id,
                TestTask.task_type == "CASE_DESIGN",
            )
            .order_by(TestTask.created_at.desc())
        )
        tasks = list(db.scalars(stmt_default).all())
        if tasks:
            return tasks[0]

        return None

    @classmethod
    def ensure_test_design_record(
        cls,
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        artifact_type: str | None = None,
        submission_id: uuid.UUID | None = None,
    ) -> AITestDesignRecord:
        stmt = (
            select(AITestDesignRecord)
            .where(
                AITestDesignRecord.project_id == project_id,
                AITestDesignRecord.task_id == task_id,
            )
            .order_by(AITestDesignRecord.record_no.desc())
        )
        record = db.scalar(stmt)
        if record and artifact_type:
            # 1. 查找当前待挂载 artifact_type 对应的阶段 nodeId
            node_id = None
            for stage_def in STAGE_DEFINITIONS.values():
                if stage_def["artifactType"] == artifact_type:
                    node_id = stage_def["nodeId"]
                    break

            if node_id:
                stage_order = {
                    "requirement_analysis": 1,
                    "test_points": 2,
                    "test_cases": 3,
                    "case_review": 4,
                }
                current_order = stage_order.get(node_id, 0)

                # 2. 查询当前最新一轮中已产生的产物集合
                from testweave.db.models import AIArtifactSetRevision

                set_stmt = select(AIArtifactSetRevision.producer_node_id).where(
                    AIArtifactSetRevision.run_id == record.run_id
                )
                existing_nodes = db.scalars(set_stmt).all()

                # 3. 如果当前最新一轮已产生过当前阶段或后置阶段 of 产物，再次提交该阶段说明开启独立新一轮
                for node in existing_nodes:
                    if stage_order.get(node, 0) >= current_order:
                        record = None
                        break

        if record:
            return record

        # 若当前任务下不存在生成轮次记录，或前一轮已结案，自动初始化首轮/新一轮生成链记录
        idempotency_key = f"ext-auto-init-{task_id}-{uuid.uuid4().hex[:8]}"
        runtime_settings = AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True)
        permissions = {"agent.use", "agent.manage"}

        new_record, _created = AiTestDesignService.create_record(
            db=db,
            project_id=project_id,
            task_id=task_id,
            actor_id=user_id,
            actor_permissions=permissions,
            idempotency_key=idempotency_key,
            runtime_settings=runtime_settings,
            review_mode="TRACEABLE",
        )
        if submission_id:
            new_record.title = (
                f"第 {new_record.record_no} 轮 · 网关提交 (ID: {str(submission_id)[:8]})"
            )
        else:
            new_record.title = f"第 {new_record.record_no} 轮 · 外部 Agent 提交"
        db.commit()
        return new_record

    @classmethod
    def mount_candidate_set_revision(
        cls,
        db: Session,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        artifact_type: str,
        validated_payload: dict[str, Any],
        submission_id: uuid.UUID | None = None,
    ) -> tuple[AITestDesignRecord, Any]:
        # 1. 获取对应阶段的 producer_node_id
        node_id = None
        for stage_def in STAGE_DEFINITIONS.values():
            if stage_def["artifactType"] == artifact_type:
                node_id = stage_def["nodeId"]
                break

        if not node_id:
            raise AppError(
                code="UNSUPPORTED_ARTIFACT_TYPE",
                message=f"不支持直接挂载的工作台 Artifact 类型: {artifact_type}",
                status_code=400,
            )

        # 2. 获取或初始化任务 of AITestDesignRecord
        record = cls.ensure_test_design_record(
            db=db,
            project_id=project_id,
            task_id=task_id,
            user_id=user_id,
            artifact_type=artifact_type,
            submission_id=submission_id,
        )

        # 3. 提取 Candidate 中的 items
        items = ArtifactSchemaValidator.extract_items(artifact_type, validated_payload)
        if not items:
            raise AppError(
                code="REVISION_SET_INCOMPLETE",
                message="提交的 Candidate 不包含有效的产物项",
                status_code=400,
            )

        # 4. 创建或取得各 Item 及其 Revision
        items_and_revisions = []
        for index, item_content in enumerate(items):
            stable_key = generate_item_stable_key(item_content, index)
            item_obj = ArtifactService.get_or_create_artifact_item(
                db=db,
                project_id=str(project_id),
                run_id=str(record.run_id),
                producer_node_id=node_id,
                artifact_type=artifact_type,
                stable_key=stable_key,
                created_by=str(user_id),
            )
            rev_obj = ArtifactService.create_artifact_revision(
                db=db,
                project_id=str(project_id),
                artifact_item_id=str(item_obj.id),
                content=item_content,
                source="INITIAL_GENERATION",
                created_by=str(user_id),
            )
            items_and_revisions.append((item_obj, rev_obj))

        # 5. 构造 Set Revision
        set_revision = SetRevisionService.construct_artifact_set_revision(
            db=db,
            project_id=str(project_id),
            run_id=str(record.run_id),
            producer_node_id=node_id,
            input_fingerprint="external_agent_candidate",
            items_and_revisions=items_and_revisions,
            review_status="CANDIDATE",
        )
        return record, set_revision
