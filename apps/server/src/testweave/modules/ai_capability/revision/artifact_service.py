import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactRevisionParent,
)
from testweave.modules.ai_capability.revision.canonical_json import calculate_canonical_hash


class ArtifactService:
    @staticmethod
    def get_or_create_artifact_item(
        db: Session,
        project_id: str,
        run_id: str,
        producer_node_id: str,
        artifact_type: str,
        stable_key: str,
        created_by: str | None = None,
    ) -> AIArtifactItem:
        stmt = select(AIArtifactItem).where(
            AIArtifactItem.run_id == uuid.UUID(str(run_id)),
            AIArtifactItem.producer_node_id == producer_node_id,
            AIArtifactItem.stable_key == stable_key,
        )
        item = db.scalar(stmt)
        if item:
            return item

        item = AIArtifactItem(
            project_id=uuid.UUID(str(project_id)),
            run_id=uuid.UUID(str(run_id)),
            producer_node_id=producer_node_id,
            artifact_type=artifact_type,
            stable_key=stable_key,
            created_by=uuid.UUID(str(created_by)) if created_by else None,
        )
        db.add(item)
        db.flush()
        return item

    @staticmethod
    def create_artifact_revision(
        db: Session,
        project_id: str,
        artifact_item_id: str,
        content: dict[str, Any],
        source: str,  # INITIAL_GENERATION, USER_EDIT, REGENERATION, SYSTEM_RECONSTRUCTION
        source_step_execution_id: str | None = None,
        source_regeneration_request_id: str | None = None,
        parent_revision_ids: list[str] | None = None,
        schema_snapshot: dict[str, Any] | None = None,
        validation_snapshot: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> AIArtifactRevision:
        item_uuid = uuid.UUID(str(artifact_item_id))

        # 验证来源只能是 StepExecution 或 RegenerationRequest 之一，不能兼有
        if source_step_execution_id and source_regeneration_request_id:
            raise AppError(
                code="REVISION_SCHEMA_INVALID",
                message="Revision 来源不能同时包含 step_execution 和 regeneration_request",
                status_code=400,
            )

        # 计算最新 revision_no
        stmt_max = (
            select(AIArtifactRevision.revision_no)
            .where(AIArtifactRevision.artifact_item_id == item_uuid)
            .order_by(AIArtifactRevision.revision_no.desc())
            .limit(1)
        )
        max_no = db.scalar(stmt_max) or 0
        next_no = max_no + 1

        content_hash = calculate_canonical_hash(content)

        revision = AIArtifactRevision(
            project_id=uuid.UUID(str(project_id)),
            artifact_item_id=item_uuid,
            revision_no=next_no,
            content=content,
            content_hash=content_hash,
            source=source,
            source_step_execution_id=uuid.UUID(str(source_step_execution_id))
            if source_step_execution_id
            else None,
            source_regeneration_request_id=uuid.UUID(str(source_regeneration_request_id))
            if source_regeneration_request_id
            else None,
            schema_snapshot=schema_snapshot,
            validation_snapshot=validation_snapshot,
            created_by=uuid.UUID(str(created_by)) if created_by else None,
        )
        db.add(revision)
        db.flush()

        # 处理父级 DAG
        if parent_revision_ids:
            for idx, parent_id in enumerate(parent_revision_ids):
                parent_uuid = uuid.UUID(str(parent_id))
                if parent_uuid == revision.id:
                    raise AppError(
                        code="REVISION_SCHEMA_INVALID",
                        message="Revision 不能建立自引用 DAG 边",
                        status_code=400,
                    )
                # 检测与建立父子关系
                parent_edge = AIArtifactRevisionParent(
                    child_revision_id=revision.id,
                    parent_revision_id=parent_uuid,
                    relation_type="DERIVED_FROM",
                    parent_order=idx,
                )
                db.add(parent_edge)
            db.flush()

        return revision
