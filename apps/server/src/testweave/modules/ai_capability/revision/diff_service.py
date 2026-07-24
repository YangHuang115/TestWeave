import uuid
from typing import Any

from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactSetRevision,
)
from testweave.modules.ai_capability.revision.set_revision_service import SetRevisionService


class DiffService:
    @staticmethod
    def compare_set_revisions(
        db: Session, base_set_revision_id: str, target_set_revision_id: str
    ) -> dict[str, Any]:
        base_set = db.get(AIArtifactSetRevision, uuid.UUID(str(base_set_revision_id)))
        target_set = db.get(AIArtifactSetRevision, uuid.UUID(str(target_set_revision_id)))

        if not base_set or not target_set:
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message="对比的 SetRevision 不存在",
                status_code=404,
            )

        base_members = SetRevisionService.get_set_revision_members(db, base_set_revision_id)
        target_members = SetRevisionService.get_set_revision_members(db, target_set_revision_id)

        base_map: dict[str, tuple[AIArtifactItem, AIArtifactRevision]] = {
            item.stable_key: (item, rev) for _, item, rev in base_members
        }
        target_map: dict[str, tuple[AIArtifactItem, AIArtifactRevision]] = {
            item.stable_key: (item, rev) for _, item, rev in target_members
        }

        unchanged_count = 0
        modified_count = 0
        added_count = 0
        removed_count = 0

        diff_items = []

        # 校验基准中所有 key
        all_keys = list(
            dict.fromkeys(
                [item.stable_key for _, item, _ in base_members]
                + [item.stable_key for _, item, _ in target_members]
            )
        )

        for key in all_keys:
            in_base = key in base_map
            in_target = key in target_map

            if in_base and in_target:
                _base_item, base_rev = base_map[key]
                _target_item, target_rev = target_map[key]
                if base_rev.content_hash == target_rev.content_hash:
                    status = "UNCHANGED"
                    unchanged_count += 1
                else:
                    status = "MODIFIED"
                    modified_count += 1

                diff_items.append(
                    {
                        "stable_key": key,
                        "status": status,
                        "base_revision_no": base_rev.revision_no,
                        "target_revision_no": target_rev.revision_no,
                        "base_content_hash": base_rev.content_hash,
                        "target_content_hash": target_rev.content_hash,
                        "base_content": base_rev.content if status == "MODIFIED" else None,
                        "target_content": target_rev.content if status == "MODIFIED" else None,
                    }
                )
            elif in_target:
                _target_item, target_rev = target_map[key]
                added_count += 1
                diff_items.append(
                    {
                        "stable_key": key,
                        "status": "ADDED",
                        "base_revision_no": None,
                        "target_revision_no": target_rev.revision_no,
                        "base_content_hash": None,
                        "target_content_hash": target_rev.content_hash,
                        "base_content": None,
                        "target_content": target_rev.content,
                    }
                )
            else:
                _base_item, base_rev = base_map[key]
                removed_count += 1
                diff_items.append(
                    {
                        "stable_key": key,
                        "status": "REMOVED",
                        "base_revision_no": base_rev.revision_no,
                        "target_revision_no": None,
                        "base_content_hash": base_rev.content_hash,
                        "target_content_hash": None,
                        "base_content": base_rev.content,
                        "target_content": None,
                    }
                )

        return {
            "base_set_revision_id": str(base_set.id),
            "target_set_revision_id": str(target_set.id),
            "summary": {
                "total_items": len(all_keys),
                "unchanged_count": unchanged_count,
                "modified_count": modified_count,
                "added_count": added_count,
                "removed_count": removed_count,
            },
            "items": diff_items,
        }
