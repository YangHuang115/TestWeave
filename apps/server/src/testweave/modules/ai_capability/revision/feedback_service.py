import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactRevisionParent,
    AIFeedback,
    AIStepExecution,
)
from testweave.modules.ai_capability.revision.projection import get_value_by_json_pointer


def _changed_paths(before: object, after: object, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            paths.extend(
                _changed_paths(
                    before.get(key),
                    after.get(key),
                    f"{prefix}/{escaped}",
                )
            )
            if len(paths) >= 200:
                return paths[:200]
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = []
        for index in range(max(len(before), len(after))):
            old_value = before[index] if index < len(before) else None
            new_value = after[index] if index < len(after) else None
            paths.extend(_changed_paths(old_value, new_value, f"{prefix}/{index}"))
            if len(paths) >= 200:
                return paths[:200]
        return paths
    return [prefix or "/"]


class FeedbackService:
    @staticmethod
    def build_change_snapshot(db: Session, feedback: AIFeedback) -> dict | None:
        """从不可变 Revision DAG 派生用户修改差异，供重生成快照使用。"""
        if feedback.target_revision_id is None:
            return None
        target = db.get(AIArtifactRevision, feedback.target_revision_id)
        parent_edge = db.scalar(
            select(AIArtifactRevisionParent)
            .where(AIArtifactRevisionParent.child_revision_id == feedback.target_revision_id)
            .order_by(AIArtifactRevisionParent.parent_order.asc())
            .limit(1)
        )
        if target is None or parent_edge is None:
            return None
        parent = db.get(AIArtifactRevision, parent_edge.parent_revision_id)
        if parent is None:
            return None
        snapshot: dict = {
            "parentRevisionId": str(parent.id),
            "targetRevisionId": str(target.id),
            "beforeContentHash": parent.content_hash,
            "afterContentHash": target.content_hash,
            "changedPaths": _changed_paths(parent.content, target.content),
        }
        if feedback.target_type == "FIELD" and feedback.json_pointer:
            try:
                snapshot["fieldChange"] = {
                    "jsonPointer": feedback.json_pointer,
                    "before": get_value_by_json_pointer(parent.content, feedback.json_pointer),
                    "after": get_value_by_json_pointer(target.content, feedback.json_pointer),
                }
            except AppError:
                snapshot["fieldChange"] = {
                    "jsonPointer": feedback.json_pointer,
                    "unavailable": True,
                }
        return snapshot

    @staticmethod
    def create_feedback(
        db: Session,
        project_id: str,
        run_id: str,
        target_type: str,  # FIELD, ARTIFACT, STEP
        category: str,
        comment: str | None = None,
        target_item_id: str | None = None,
        target_revision_id: str | None = None,
        target_step_execution_id: str | None = None,
        json_pointer: str | None = None,
        user_id: str | None = None,
    ) -> AIFeedback:
        run_uuid = uuid.UUID(str(run_id))
        proj_uuid = uuid.UUID(str(project_id))

        if target_type == "CAPABILITY":
            raise AppError(
                code="FEEDBACK_TARGET_INVALID",
                message="P3 拒绝 CAPABILITY 级别的 Feedback 目标",
                status_code=400,
            )

        if comment and len(comment) > 5000:
            raise AppError(
                code="FEEDBACK_CONTENT_TOO_LARGE",
                message="Feedback 内容超过 5000 字符限制",
                status_code=400,
            )

        item_uuid = uuid.UUID(str(target_item_id)) if target_item_id else None
        rev_uuid = uuid.UUID(str(target_revision_id)) if target_revision_id else None
        step_uuid = uuid.UUID(str(target_step_execution_id)) if target_step_execution_id else None

        if target_type == "FIELD":
            if not item_uuid or not rev_uuid or not json_pointer:
                raise AppError(
                    code="FEEDBACK_TARGET_INVALID",
                    message=(
                        "FIELD 类型 Feedback 必须提供 target_item_id, "
                        "target_revision_id 与 json_pointer"
                    ),
                    status_code=400,
                )
            item = db.get(AIArtifactItem, item_uuid)
            revision = db.get(AIArtifactRevision, rev_uuid)
            if (
                item is None
                or revision is None
                or item.project_id != proj_uuid
                or item.run_id != run_uuid
                or revision.artifact_item_id != item.id
            ):
                raise AppError(
                    code="FEEDBACK_TARGET_INVALID",
                    message="FIELD Feedback 的 Item 或 Revision 不属于当前运行",
                    status_code=400,
                )
            get_value_by_json_pointer(revision.content, json_pointer)
        elif target_type == "ARTIFACT":
            if not item_uuid or not rev_uuid:
                raise AppError(
                    code="FEEDBACK_TARGET_INVALID",
                    message="ARTIFACT 类型 Feedback 必须提供 target_item_id 与 target_revision_id",
                    status_code=400,
                )
            item = db.get(AIArtifactItem, item_uuid)
            revision = db.get(AIArtifactRevision, rev_uuid)
            if (
                item is None
                or revision is None
                or item.project_id != proj_uuid
                or item.run_id != run_uuid
                or revision.artifact_item_id != item.id
            ):
                raise AppError(
                    code="FEEDBACK_TARGET_INVALID",
                    message="ARTIFACT Feedback 的 Item 或 Revision 不属于当前运行",
                    status_code=400,
                )
            json_pointer = None
        elif target_type == "STEP":
            if not step_uuid:
                raise AppError(
                    code="FEEDBACK_TARGET_INVALID",
                    message="STEP 类型 Feedback 必须提供 target_step_execution_id",
                    status_code=400,
                )
            step = db.get(AIStepExecution, step_uuid)
            if step is None or step.run_id != run_uuid:
                raise AppError(
                    code="FEEDBACK_TARGET_INVALID",
                    message="STEP Feedback 的执行步骤不属于当前运行",
                    status_code=400,
                )
            item_uuid = None
            rev_uuid = None
            json_pointer = None
        else:
            raise AppError(
                code="FEEDBACK_TARGET_INVALID",
                message=f"不支持的 Feedback 类型: {target_type}",
                status_code=400,
            )

        feedback = AIFeedback(
            project_id=proj_uuid,
            run_id=run_uuid,
            target_type=target_type,
            target_item_id=item_uuid,
            target_revision_id=rev_uuid,
            target_step_execution_id=step_uuid,
            json_pointer=json_pointer,
            category=category,
            comment=comment,
            status="ACTIVE",
            created_by=uuid.UUID(str(user_id)) if user_id else None,
        )
        db.add(feedback)
        db.flush()
        return feedback

    @staticmethod
    def list_active_feedback_for_run(db: Session, run_id: str) -> list[AIFeedback]:
        run_uuid = uuid.UUID(str(run_id))
        stmt = (
            select(AIFeedback)
            .where(
                AIFeedback.run_id == run_uuid,
                AIFeedback.status == "ACTIVE",
            )
            .order_by(AIFeedback.created_at.asc())
        )
        return list(db.scalars(stmt).all())
