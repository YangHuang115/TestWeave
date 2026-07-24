import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactSetRevision,
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
    AIFieldLock,
    AIRegenerationRequest,
    AIRegenerationRequestFeedback,
    AIRegenerationRequestItem,
)
from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    ArtifactSchemaValidator,
)
from testweave.modules.ai_capability.revision.artifact_service import ArtifactService
from testweave.modules.ai_capability.revision.canonical_json import calculate_canonical_hash
from testweave.modules.ai_capability.revision.feedback_service import FeedbackService
from testweave.modules.ai_capability.revision.field_lock_service import FieldLockService
from testweave.modules.ai_capability.revision.fingerprint import calculate_input_fingerprint
from testweave.modules.ai_capability.revision.set_revision_service import SetRevisionService


class RegenerationService:
    @staticmethod
    def create_regeneration_request(
        db: Session,
        project_id: str,
        run_id: str,
        node_id: str,
        target_item_stable_keys: list[str],
        base_set_revision_id: str | None = None,
        feedback_ids: list[str] | None = None,
        idempotency_key: str | None = None,
        requested_by: str | None = None,
    ) -> AIRegenerationRequest:
        run_uuid = uuid.UUID(str(run_id))
        proj_uuid = uuid.UUID(str(project_id))

        run = db.get(AICapabilityRun, run_uuid)
        if not run:
            raise AppError(
                code="REVISION_RUN_READ_ONLY",
                message="Run 不存在",
                status_code=404,
            )

        if run.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            raise AppError(
                code="REVISION_RUN_READ_ONLY",
                message="终态 Run 禁止发起局部重生成",
                status_code=400,
            )

        # 如果没有传 base_set_revision_id，默认读取当前的 Accepted Set
        if not base_set_revision_id:
            stmt_curr = select(AICurrentAcceptedRevisionSet).where(
                AICurrentAcceptedRevisionSet.run_id == run_uuid,
                AICurrentAcceptedRevisionSet.node_id == node_id,
            )
            acc = db.scalar(stmt_curr)
            if not acc:
                raise AppError(
                    code="REGENERATION_BASE_CHANGED",
                    message="未找到当前已接受的 Base SetRevision",
                    status_code=400,
                )
            base_set_revision_id = str(acc.current_set_revision_id)

        base_set = db.get(AIArtifactSetRevision, uuid.UUID(base_set_revision_id))
        if not base_set:
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message=f"Base SetRevision {base_set_revision_id} 不存在",
                status_code=404,
            )

        # 读取 Base Set 成员
        base_members = SetRevisionService.get_set_revision_members(db, str(base_set.id))
        base_member_map = {item.stable_key: (item, rev) for _, item, rev in base_members}

        if not target_item_stable_keys:
            raise AppError(
                code="REGENERATION_TARGET_INVALID",
                message="必须至少指定一条重生成的目标 Item",
                status_code=400,
            )

        # 校验目标 Item 全部属于 Base Set
        target_pairs = []
        for key in target_item_stable_keys:
            if key not in base_member_map:
                raise AppError(
                    code="REGENERATION_TARGET_INVALID",
                    message=f"目标 Item {key} 不属于 Base Set {base_set.id}",
                    status_code=400,
                )
            target_pairs.append(base_member_map[key])

        # 校验是否有活动 FieldLock 拦截重生成目标
        for target_item, _ in target_pairs:
            locks_stmt = select(AIFieldLock).where(
                AIFieldLock.artifact_item_id == target_item.id,
                AIFieldLock.status == "ACTIVE",
            )
            if db.scalar(locks_stmt):
                raise AppError(
                    code="REGENERATION_BLOCKED_BY_LOCK",
                    message=f"Item {target_item.stable_key} 存在活动 FieldLock，禁止局部重生成",
                    status_code=400,
                )

        # 关联 Active Feedback
        active_feedbacks = FeedbackService.list_active_feedback_for_run(db, run_id)
        selected_feedbacks = []
        if feedback_ids:
            fb_uuids = {uuid.UUID(str(fid)) for fid in feedback_ids}
            selected_feedbacks = [fb for fb in active_feedbacks if fb.id in fb_uuids]
        else:
            selected_feedbacks = active_feedbacks

        # 冻结请求快照并生成 request_fingerprint
        request_snapshot = {
            "node_id": node_id,
            "base_set_revision_id": str(base_set.id),
            "target_item_stable_keys": target_item_stable_keys,
            "feedback_snapshots": [
                {
                    "id": str(fb.id),
                    "target_type": fb.target_type,
                    "category": fb.category,
                    "comment": fb.comment,
                    "json_pointer": fb.json_pointer,
                    "change_snapshot": FeedbackService.build_change_snapshot(db, fb),
                }
                for fb in selected_feedbacks
            ],
        }

        req_fingerprint = calculate_canonical_hash(request_snapshot)

        if idempotency_key:
            existing = db.scalar(
                select(AIRegenerationRequest).where(
                    AIRegenerationRequest.run_id == run_uuid,
                    AIRegenerationRequest.idempotency_key == idempotency_key,
                )
            )
            if existing:
                if existing.request_fingerprint != req_fingerprint:
                    raise AppError(
                        code="REGENERATION_IDEMPOTENCY_CONFLICT",
                        message="相同 Idempotency-Key 携带了不同的局部重生成请求",
                        status_code=409,
                    )
                return existing

        regen_req = AIRegenerationRequest(
            project_id=proj_uuid,
            run_id=run_uuid,
            node_id=node_id,
            base_set_revision_id=base_set.id,
            status="PENDING",
            request_snapshot=request_snapshot,
            request_fingerprint=req_fingerprint,
            idempotency_key=idempotency_key,
            requested_by=uuid.UUID(str(requested_by)) if requested_by else None,
        )
        try:
            with db.begin_nested():
                db.add(regen_req)
                db.flush()
        except IntegrityError:
            existing = db.scalar(
                select(AIRegenerationRequest).where(
                    AIRegenerationRequest.run_id == run_uuid,
                    AIRegenerationRequest.idempotency_key == idempotency_key,
                )
            )
            if existing and existing.request_fingerprint == req_fingerprint:
                return existing
            raise AppError(
                code="REGENERATION_IDEMPOTENCY_CONFLICT",
                message="局部重生成幂等键发生并发冲突",
                status_code=409,
            ) from None

        # 写入目标 Item 关联
        for item, rev in target_pairs:
            target_ref = f"target-{item.stable_key}"
            item_link = AIRegenerationRequestItem(
                regeneration_request_id=regen_req.id,
                artifact_item_id=item.id,
                base_revision_id=rev.id,
                target_ref=target_ref,
            )
            db.add(item_link)

        # 写入反馈关联
        for fb in selected_feedbacks:
            fb_link = AIRegenerationRequestFeedback(
                regeneration_request_id=regen_req.id,
                feedback_id=fb.id,
            )
            db.add(fb_link)

        db.flush()
        return regen_req

    @staticmethod
    def process_regeneration_response(
        db: Session,
        regeneration_request_id: str,
        replacements: list[dict[str, Any]],  # Provider 返回的 7 条 replacement 项
        capability_version_id: str,
        package_fingerprint: str,
        execution_snapshot_hash: str,
        node_config: dict[str, Any],
        run_input: dict[str, Any],
        input_fingerprint: str | None = None,
    ) -> AIArtifactSetRevision:
        """服务端完整集合重构算法：
        把 Provider 返回的 7 条 replacement 与 Base Set 中未修的 3 条成员合并，
        构造全新完整 10 条 Candidate SetRevision。
        """
        req_uuid = uuid.UUID(str(regeneration_request_id))
        regen_req = db.get(AIRegenerationRequest, req_uuid, with_for_update=True)
        if not regen_req:
            raise AppError(
                code="REGENERATION_TARGET_INVALID",
                message=f"RegenerationRequest {regeneration_request_id} 不存在",
                status_code=404,
            )
        if regen_req.status not in {"PENDING", "RUNNING"}:
            raise AppError(
                code="REGENERATION_TARGET_INVALID",
                message=f"RegenerationRequest 当前状态不可写入: {regen_req.status}",
                status_code=409,
            )
        if regen_req.started_at is None:
            regen_req.started_at = datetime.now(UTC)

        base_set = db.get(AIArtifactSetRevision, regen_req.base_set_revision_id)
        if not base_set:
            raise AppError(
                code="REVISION_SET_NOT_FOUND",
                message="Base SetRevision 不存在",
                status_code=404,
            )

        # 读取 Base Set 成员
        base_members = SetRevisionService.get_set_revision_members(db, str(base_set.id))

        # 读取请求中绑定的目标 Item 映射 (targetRef -> Item)
        stmt_items = (
            select(AIRegenerationRequestItem, AIArtifactItem)
            .join(AIArtifactItem, AIRegenerationRequestItem.artifact_item_id == AIArtifactItem.id)
            .where(AIRegenerationRequestItem.regeneration_request_id == req_uuid)
        )
        req_items = db.execute(stmt_items).all()

        target_ref_to_item = {req_item.target_ref: item for req_item, item in req_items}
        target_key_set = {item.stable_key for _, item in req_items}

        # 校验 replacements 的数量与 targetRef 覆盖情况
        replacement_map: dict[str, dict[str, Any]] = {}
        for rep in replacements:
            ref = rep.get("targetRef") or rep.get("target_ref")
            # 若缺失 targetRef，退而尝试通过 id / stable_key 匹配
            if not ref:
                for k in ("stable_key", "id", "item_id"):
                    if k in rep and f"target-{rep[k]}" in target_ref_to_item:
                        ref = f"target-{rep[k]}"
                        break
            if not ref or ref not in target_ref_to_item:
                raise AppError(
                    code="REGENERATION_RESPONSE_INCOMPLETE",
                    message=f"Provider 响应中包含无法映射的 targetRef: {ref}",
                    status_code=400,
                )
            matched_item = target_ref_to_item[ref]
            if matched_item.stable_key in replacement_map:
                raise AppError(
                    code="REGENERATION_RESPONSE_INCOMPLETE",
                    message=f"Provider 响应中包含重复的 targetRef 项: {ref}",
                    status_code=400,
                )
            content = rep.get("content")
            if not isinstance(content, dict):
                # 兼容 P3 早期调用方：映射字段与 Artifact 内容处于同一对象。
                content = {
                    key: value
                    for key, value in rep.items()
                    if key not in {"targetRef", "target_ref"}
                }
            artifact_type = matched_item.artifact_type
            if artifact_type in ArtifactSchemaValidator.get_supported_types():
                if artifact_type == "test_point_set@1.0":
                    validation_payload = {"schemaVersion": "1.0", "points": [content]}
                elif artifact_type == "test_case_set@1.0":
                    validation_payload = {"schemaVersion": "1.0", "cases": [content]}
                else:
                    validation_payload = content
                ArtifactSchemaValidator.validate_artifact(
                    artifact_type,
                    validation_payload,
                )
            replacement_map[matched_item.stable_key] = content

        if set(replacement_map.keys()) != target_key_set:
            raise AppError(
                code="REGENERATION_RESPONSE_INCOMPLETE",
                message="Provider 局部重生成响应未恰好覆盖请求的目标项集合",
                status_code=400,
            )

        # 构建新的完整 10 条集合列表
        reconstructed_list: list[tuple[AIArtifactItem, AIArtifactRevision]] = []

        for _pos, item, old_rev in base_members:
            if item.stable_key in target_key_set:
                # 生成新 Revision (7条之一)
                new_content = replacement_map[item.stable_key]
                new_rev = ArtifactService.create_artifact_revision(
                    db=db,
                    project_id=str(base_set.project_id),
                    artifact_item_id=str(item.id),
                    content=new_content,
                    source="REGENERATION",
                    source_regeneration_request_id=str(regen_req.id),
                    parent_revision_ids=[str(old_rev.id)],
                )
                reconstructed_list.append((item, new_rev))
            else:
                # 复用原 Revision (3条之一)
                reconstructed_list.append((item, old_rev))

        # 强校验全部 FieldLock
        FieldLockService.verify_field_locks_for_items(db, reconstructed_list)

        # 计算新的 InputFingerprint
        input_fp = input_fingerprint or calculate_input_fingerprint(
            capability_version_id=capability_version_id,
            package_fingerprint=package_fingerprint,
            execution_snapshot_hash=execution_snapshot_hash,
            node_id=regen_req.node_id,
            node_config=node_config,
            run_input=run_input,
            upstream_set_hashes=[],
        )

        # 构造完整 Candidate SetRevision
        new_set_rev = SetRevisionService.construct_artifact_set_revision(
            db=db,
            project_id=str(base_set.project_id),
            run_id=str(base_set.run_id),
            producer_node_id=base_set.producer_node_id,
            input_fingerprint=input_fp,
            items_and_revisions=reconstructed_list,
            base_set_revision_id=str(base_set.id),
            source_regeneration_request_id=str(regen_req.id),
            review_status="CANDIDATE",
            validation_status="VALID",
        )

        if base_set.review_status == "CANDIDATE":
            base_set.review_status = "SUPERSEDED"
        regen_req.status = "COMPLETED"
        regen_req.result_set_revision_id = new_set_rev.id
        regen_req.completed_at = datetime.now(UTC)
        db.flush()

        return new_set_rev
