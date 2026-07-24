import uuid
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import AICapability
from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    ArtifactSchemaValidator,
)
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


class CandidateSubmissionService:
    @classmethod
    def submit_candidate_revision(
        cls,
        db: Session,
        token_project_id: uuid.UUID,
        user_id: uuid.UUID,
        effective_scopes: list[str],
        capability_id: uuid.UUID | None,
        artifact_type: str,
        payload: dict[str, Any],
        task_id: uuid.UUID | None = None,
        task_key: str | None = None,
        requirement_id: uuid.UUID | None = None,
        requirement_key: str | None = None,
        auto_publish: bool = False,
        summary: str | None = None,
    ) -> dict[str, Any]:
        from testweave.modules.ai_capability.external_agent.external_candidate_bridge_service import (
            ExternalCandidateBridgeService,
        )

        # 1. 校验 Scope 映射
        ExternalAgentTokenService.verify_scope(effective_scopes, "revision:candidate")
        if auto_publish:
            raise AppError(
                code="EXTERNAL_AUTO_PUBLISH_FORBIDDEN",
                message="外接 Agent 只能提交 Candidate，不能直接发布正式资产",
                status_code=400,
            )

        capability = None
        if capability_id:
            capability = db.get(AICapability, capability_id)

        if not capability and token_project_id:
            from sqlalchemy import select

            stmt = (
                select(AICapability)
                .where(AICapability.project_id == token_project_id)
                .order_by(AICapability.created_at.desc())
            )
            capability = db.scalar(stmt)

        if not capability and token_project_id:
            capability = AICapability(
                project_id=token_project_id,
                scope="PROJECT",
                namespace="testweave",
                code="default_test_point_generation",
                name="默认 AI 测试点与用例生成能力包",
                category="TEST_POINT_GENERATION",
            )
            db.add(capability)
            db.flush()
            db.commit()

        if not capability:
            raise AppError(
                code="CAPABILITY_NOT_FOUND",
                message="能力包不存在或不属于当前 Token 项目",
                status_code=404,
            )
        capability_id = capability.id

        # 2. 解析与校验 task_id / task_key / requirement_id / requirement_key
        task = ExternalCandidateBridgeService.resolve_task(
            db=db,
            project_id=token_project_id,
            task_id=task_id,
            task_key=task_key,
            requirement_id=requirement_id,
            requirement_key=requirement_key,
        )
        task_id = task.id if task else None

        # 3. 校验 Candidate Artifact Schema 合规性
        validated_payload = ArtifactSchemaValidator.validate_artifact(artifact_type, payload)

        # 4. 计算生成的数据项数量
        items = ArtifactSchemaValidator.extract_items(artifact_type, validated_payload)

        item_count = len(items)
        published_count = 0
        record_id = None
        set_revision_id = None
        submission_id = uuid.uuid4()

        # 5. 关联任务时自动初始化生成轮次并自动挂载候选版本
        if task_id and items:
            record, set_revision = ExternalCandidateBridgeService.mount_candidate_set_revision(
                db=db,
                project_id=token_project_id,
                task_id=task_id,
                user_id=user_id,
                artifact_type=artifact_type,
                validated_payload=validated_payload,
                submission_id=submission_id,
            )
            record_id = str(record.id)
            set_revision_id = str(set_revision.id)

        # 6. 如果关联了 task_id 且包含测试点数据，自动同步更新该任务在网页上的 TestCaseMindmap 脑图画布节点
        if task_id and items and artifact_type == "test_point_set@1.0":
            from sqlalchemy import select

            from testweave.db.models import TestCaseMindmap

            stmt = select(TestCaseMindmap).where(
                TestCaseMindmap.project_id == token_project_id,
                TestCaseMindmap.task_id == task_id,
            )
            mindmap = db.scalar(stmt)

            if not mindmap:
                mindmap = TestCaseMindmap(
                    project_id=token_project_id,
                    task_id=task_id,
                    title="新测试点脑图",
                    data={
                        "nodeData": {
                            "id": "root",
                            "topic": "测试用例脑图",
                            "root": True,
                            "children": [],
                        }
                    },
                )
                db.add(mindmap)
                db.flush()

            data = dict(mindmap.data or {})
            node_data = dict(
                data.get("nodeData")
                or {
                    "id": "root",
                    "topic": "测试用例脑图",
                    "root": True,
                    "children": [],
                }
            )
            children = list(node_data.get("children") or [])
            existing_topics = {
                c.get("topic") for c in children if isinstance(c, dict) and c.get("topic")
            }

            for index, item in enumerate(items, start=1):
                topic = item.get("title") or item.get("name") or f"测试点-{index}"
                topic_str = str(topic).strip()
                if topic_str not in existing_topics:
                    child_node: dict[str, Any] = {
                        "id": f"node-ext-{uuid.uuid4().hex[:8]}",
                        "topic": topic_str,
                        "children": [],
                    }
                    if item.get("description"):
                        child_node["children"] = [
                            {
                                "id": f"node-ext-{uuid.uuid4().hex[:8]}",
                                "topic": str(item["description"]).strip(),
                                "children": [],
                            }
                        ]
                    children.append(child_node)
                    existing_topics.add(topic_str)

            node_data["children"] = children
            data["nodeData"] = node_data
            mindmap.data = data
            db.flush()

        status_str = "SUBMITTED"

        result_dto = {
            "submissionId": str(submission_id),
            "status": status_str,
            "capabilityId": str(capability_id),
            "taskId": str(task_id) if task_id else None,
            "recordId": record_id,
            "setRevisionId": set_revision_id,
            "projectId": str(token_project_id),
            "submittedByUserId": str(user_id),
            "artifactType": artifact_type,
            "itemCount": item_count,
            "testPointCount": item_count if artifact_type == "test_point_set@1.0" else 0,
            "publishedCount": published_count,
            "autoPublished": False,
            "summary": summary or f"External Agent submitted {item_count} candidate items",
            "validatedPayload": validated_payload,
        }

        # 将 CandidateSubmission 持久化落盘到 DB
        from testweave.db.models import CandidateSubmission

        db_sub = CandidateSubmission(
            id=submission_id,
            project_id=token_project_id,
            capability_id=capability_id,
            task_id=task_id,
            submitted_by_user_id=user_id,
            artifact_type=artifact_type,
            status=status_str,
            item_count=item_count,
            published_count=published_count,
            auto_published=False,
            summary=result_dto["summary"],
            payload_json=validated_payload,
        )
        db.add(db_sub)
        db.commit()

        cls._SUBMISSIONS[str(submission_id)] = result_dto
        return result_dto

    _SUBMISSIONS: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def get_candidate_submission(
        cls,
        db: Session,
        token_project_id: uuid.UUID,
        effective_scopes: list[str],
        submission_id: uuid.UUID,
    ) -> dict[str, Any]:
        ExternalAgentTokenService.verify_scope(effective_scopes, "revision:candidate")

        # 1. 优先查 DB
        from testweave.db.models import CandidateSubmission

        db_sub = db.get(CandidateSubmission, submission_id)
        if db_sub and db_sub.project_id == token_project_id:
            return {
                "submissionId": str(db_sub.id),
                "status": db_sub.status,
                "capabilityId": str(db_sub.capability_id) if db_sub.capability_id else None,
                "taskId": str(db_sub.task_id) if db_sub.task_id else None,
                "projectId": str(db_sub.project_id),
                "submittedByUserId": str(db_sub.submitted_by_user_id),
                "artifactType": db_sub.artifact_type,
                "itemCount": db_sub.item_count,
                "testPointCount": (
                    db_sub.item_count if db_sub.artifact_type == "test_point_set@1.0" else 0
                ),
                "publishedCount": db_sub.published_count,
                "autoPublished": db_sub.auto_published,
                "summary": db_sub.summary,
                "validatedPayload": db_sub.payload_json,
            }

        # 2. 备用查内存
        submission = cls._SUBMISSIONS.get(str(submission_id))
        if not submission or submission.get("projectId") != str(token_project_id):
            raise AppError(
                code="SUBMISSION_NOT_FOUND",
                message=f"未找到 ID 为 {submission_id} 的 Candidate 提交记录",
                status_code=404,
            )
        return submission

    @classmethod
    def register_candidate_attachment(
        cls,
        db: Session,
        token_project_id: uuid.UUID,
        user_id: uuid.UUID,
        effective_scopes: list[str],
        submission_id: uuid.UUID,
        file_name: str,
        file_size: int,
        mime_type: str,
        checksum: str | None = None,
    ) -> dict[str, Any]:
        # 校验 Scope
        ExternalAgentTokenService.verify_scope(effective_scopes, "revision:candidate")

        attachment_id = uuid.uuid4()
        return {
            "attachmentId": str(attachment_id),
            "submissionId": str(submission_id),
            "projectId": str(token_project_id),
            "fileName": file_name,
            "fileSize": file_size,
            "mimeType": mime_type,
            "checksum": checksum,
            "uploadUrl": f"http://127.0.0.1:8787/external/v1/attachments/upload/{attachment_id}",
        }
