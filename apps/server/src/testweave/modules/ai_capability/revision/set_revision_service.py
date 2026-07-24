import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactSetRevision,
    AIArtifactSetRevisionMember,
)
from testweave.modules.ai_capability.revision.canonical_json import calculate_canonical_hash


class SetRevisionService:
    @staticmethod
    def calculate_set_hash(members: list[dict[str, Any]]) -> str:
        """计算 Set Hash。
        members: [{"stable_key": "...", "content_hash": "...", "position": 0}, ...]
        按 position 升序排序。
        """
        sorted_members = sorted(members, key=lambda x: x.get("position", 0))
        formatted = [
            {
                "position": m["position"],
                "stable_key": m["stable_key"],
                "content_hash": m["content_hash"],
            }
            for m in sorted_members
        ]
        return calculate_canonical_hash(formatted)

    @staticmethod
    def construct_artifact_set_revision(
        db: Session,
        project_id: str,
        run_id: str,
        producer_node_id: str,
        input_fingerprint: str,
        items_and_revisions: list[tuple[AIArtifactItem, AIArtifactRevision]],
        base_set_revision_id: str | None = None,
        source_step_execution_id: str | None = None,
        source_regeneration_request_id: str | None = None,
        input_context_snapshot_id: str | None = None,
        review_status: str = "CANDIDATE",
        validation_status: str = "VALID",
        validation_snapshot: dict[str, Any] | None = None,
    ) -> AIArtifactSetRevision:
        run_uuid = uuid.UUID(str(run_id))
        proj_uuid = uuid.UUID(str(project_id))

        if not items_and_revisions:
            raise AppError(
                code="REVISION_SET_INCOMPLETE",
                message="不能创建空成员的 ArtifactSetRevision",
                status_code=400,
            )

        # 校验 stable_key 唯一与 position 连续性
        seen_items = set()
        member_hash_inputs = []
        for idx, (item, rev) in enumerate(items_and_revisions):
            if item.id in seen_items:
                raise AppError(
                    code="REVISION_SET_INVALID",
                    message=f"SetRevision 包含重复 Item: {item.stable_key}",
                    status_code=400,
                )
            seen_items.add(item.id)

            if rev.artifact_item_id != item.id:
                raise AppError(
                    code="REVISION_SET_INVALID",
                    message=f"Revision {rev.id} 不属于 Item {item.id}",
                    status_code=400,
                )

            member_hash_inputs.append(
                {
                    "position": idx,
                    "stable_key": item.stable_key,
                    "content_hash": rev.content_hash,
                }
            )

        set_hash = SetRevisionService.calculate_set_hash(member_hash_inputs)

        # 计算下一个 set_revision_no
        stmt_max = (
            select(AIArtifactSetRevision.set_revision_no)
            .where(
                AIArtifactSetRevision.run_id == run_uuid,
                AIArtifactSetRevision.producer_node_id == producer_node_id,
            )
            .order_by(AIArtifactSetRevision.set_revision_no.desc())
            .limit(1)
        )
        max_no = db.scalar(stmt_max) or 0
        next_no = max_no + 1

        set_rev = AIArtifactSetRevision(
            project_id=proj_uuid,
            run_id=run_uuid,
            producer_node_id=producer_node_id,
            set_revision_no=next_no,
            base_set_revision_id=uuid.UUID(str(base_set_revision_id))
            if base_set_revision_id
            else None,
            source_step_execution_id=uuid.UUID(str(source_step_execution_id))
            if source_step_execution_id
            else None,
            source_regeneration_request_id=uuid.UUID(str(source_regeneration_request_id))
            if source_regeneration_request_id
            else None,
            input_context_snapshot_id=uuid.UUID(str(input_context_snapshot_id))
            if input_context_snapshot_id
            else None,
            input_fingerprint=input_fingerprint,
            set_hash=set_hash,
            item_count=len(items_and_revisions),
            review_status=review_status,
            validation_status=validation_status,
            validation_snapshot=validation_snapshot,
        )
        db.add(set_rev)
        db.flush()

        # 插入成员
        for idx, (item, rev) in enumerate(items_and_revisions):
            member = AIArtifactSetRevisionMember(
                set_revision_id=set_rev.id,
                artifact_item_id=item.id,
                artifact_revision_id=rev.id,
                position=idx,
            )
            db.add(member)

        db.flush()
        return set_rev

    @staticmethod
    def get_set_revision_members(
        db: Session, set_revision_id: str
    ) -> list[tuple[AIArtifactSetRevisionMember, AIArtifactItem, AIArtifactRevision]]:
        set_uuid = uuid.UUID(str(set_revision_id))
        stmt = (
            select(AIArtifactSetRevisionMember, AIArtifactItem, AIArtifactRevision)
            .join(AIArtifactItem, AIArtifactSetRevisionMember.artifact_item_id == AIArtifactItem.id)
            .join(
                AIArtifactRevision,
                AIArtifactSetRevisionMember.artifact_revision_id == AIArtifactRevision.id,
            )
            .where(AIArtifactSetRevisionMember.set_revision_id == set_uuid)
            .order_by(AIArtifactSetRevisionMember.position.asc())
        )
        results = db.execute(stmt).all()
        return [(r[0], r[1], r[2]) for r in results]
