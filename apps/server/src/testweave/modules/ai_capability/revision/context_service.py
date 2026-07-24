import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactSetRevision,
    AIContextSnapshot,
    AICurrentAcceptedRevisionSet,
)
from testweave.modules.ai_capability.revision.canonical_json import calculate_canonical_hash
from testweave.modules.ai_capability.revision.fingerprint import calculate_input_fingerprint
from testweave.modules.ai_capability.revision.set_revision_service import SetRevisionService


class ContextService:
    @staticmethod
    def materialize_context_snapshot(
        db: Session,
        project_id: str,
        run_id: str,
        node_id: str,
        purpose: str,  # STEP_EXECUTION, REGENERATION
        capability_version_id: str,
        package_fingerprint: str,
        execution_snapshot_hash: str,
        node_config: dict[str, Any],
        run_input: dict[str, Any],
        upstream_node_ids: list[str],
        source_step_execution_id: str | None = None,
        source_regeneration_request_id: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> AIContextSnapshot:
        run_uuid = uuid.UUID(str(run_id))
        proj_uuid = uuid.UUID(str(project_id))

        context_items = {}
        upstream_manifest = {}
        upstream_set_hashes = []

        # 获取上游节点的 Current Accepted Set
        for up_node in upstream_node_ids:
            stmt = select(AICurrentAcceptedRevisionSet).where(
                AICurrentAcceptedRevisionSet.run_id == run_uuid,
                AICurrentAcceptedRevisionSet.node_id == up_node,
            )
            acc_set = db.scalar(stmt)
            if not acc_set:
                raise AppError(
                    code="CONTEXT_UPSTREAM_NOT_READY",
                    message=f"上游节点 {up_node} 的当前黄金集合未就绪",
                    status_code=400,
                )

            if acc_set.freshness_status != "CURRENT":
                raise AppError(
                    code="CONTEXT_SOURCE_STALE",
                    message=f"上游节点 {up_node} 的黄金集合已被标记为 STALE",
                    status_code=400,
                )

            if acc_set.validation_status != "VALID":
                raise AppError(
                    code="CONTEXT_SOURCE_INVALID",
                    message=f"上游节点 {up_node} 的黄金集合处于 INVALID 状态",
                    status_code=400,
                )

            set_rev = db.get(AIArtifactSetRevision, acc_set.current_set_revision_id)
            if not set_rev:
                raise AppError(
                    code="REVISION_SET_NOT_FOUND",
                    message=f"SetRevision {acc_set.current_set_revision_id} 不存在",
                    status_code=404,
                )

            members = SetRevisionService.get_set_revision_members(db, str(set_rev.id))
            item_contents = [rev.content for _, _, rev in members]

            context_items[up_node] = item_contents
            upstream_manifest[up_node] = {
                "set_revision_id": str(set_rev.id),
                "set_hash": set_rev.set_hash,
                "item_count": set_rev.item_count,
            }
            upstream_set_hashes.append(
                {
                    "node_id": up_node,
                    "set_hash": set_rev.set_hash,
                }
            )

        context_payload = {
            "node_id": node_id,
            "run_input": run_input,
            "upstream_data": context_items,
        }

        content_hash = calculate_canonical_hash(context_payload)

        input_fp = calculate_input_fingerprint(
            capability_version_id=capability_version_id,
            package_fingerprint=package_fingerprint,
            execution_snapshot_hash=execution_snapshot_hash,
            node_id=node_id,
            node_config=node_config,
            run_input=run_input,
            upstream_set_hashes=upstream_set_hashes,
            provider_name=provider_name,
            model_name=model_name,
        )

        snapshot = AIContextSnapshot(
            project_id=proj_uuid,
            run_id=run_uuid,
            node_id=node_id,
            purpose=purpose,
            source_step_execution_id=uuid.UUID(str(source_step_execution_id))
            if source_step_execution_id
            else None,
            source_regeneration_request_id=uuid.UUID(str(source_regeneration_request_id))
            if source_regeneration_request_id
            else None,
            content=context_payload,
            content_hash=content_hash,
            input_fingerprint=input_fp,
            fingerprint_algorithm="m09-input-fingerprint-v1",
            upstream_manifest=upstream_manifest,
        )
        db.add(snapshot)
        db.flush()
        return snapshot
