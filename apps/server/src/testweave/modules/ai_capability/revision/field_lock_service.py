import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIFieldLock,
)
from testweave.modules.ai_capability.revision.canonical_json import calculate_canonical_hash
from testweave.modules.ai_capability.revision.projection import get_value_by_json_pointer


class FieldLockService:
    @staticmethod
    def create_field_lock(
        db: Session,
        project_id: str,
        run_id: str,
        node_id: str,
        artifact_item_id: str,
        anchor_revision_id: str,
        json_pointer: str,
        user_id: str | None = None,
    ) -> AIFieldLock:
        item_uuid = uuid.UUID(str(artifact_item_id))
        anchor_uuid = uuid.UUID(str(anchor_revision_id))
        run_uuid = uuid.UUID(str(run_id))
        proj_uuid = uuid.UUID(str(project_id))

        # 读取 anchor revision
        rev = db.get(AIArtifactRevision, anchor_uuid)
        if not rev:
            raise AppError(
                code="ARTIFACT_REVISION_NOT_FOUND",
                message=f"Revision {anchor_revision_id} 不存在",
                status_code=404,
            )

        # 获取 pointer 值并计算 value_hash
        try:
            target_val = get_value_by_json_pointer(rev.content, json_pointer)
        except AppError as exc:
            raise AppError(
                code="LOCK_POINTER_INVALID",
                message=f"锁定 Pointer 无效: {exc.message}",
                status_code=400,
            ) from exc

        value_hash = calculate_canonical_hash(target_val)

        # 检查活动锁是否存在及是否产生父子重叠锁
        active_locks_stmt = select(AIFieldLock).where(
            AIFieldLock.artifact_item_id == item_uuid,
            AIFieldLock.status == "ACTIVE",
        )
        active_locks = db.scalars(active_locks_stmt).all()

        for lock in active_locks:
            if lock.json_pointer == json_pointer:
                raise AppError(
                    code="LOCK_OVERLAP",
                    message=f"Pointer {json_pointer} 已存在活动锁",
                    status_code=400,
                )
            # 校验父子重叠，如 /foo 与 /foo/bar
            if json_pointer.startswith(lock.json_pointer + "/") or lock.json_pointer.startswith(
                json_pointer + "/"
            ):
                raise AppError(
                    code="LOCK_OVERLAP",
                    message=f"Pointer {json_pointer} 与已有锁 {lock.json_pointer} 存在父子重叠",
                    status_code=400,
                )

        lock = AIFieldLock(
            project_id=proj_uuid,
            run_id=run_uuid,
            node_id=node_id,
            artifact_item_id=item_uuid,
            anchor_revision_id=anchor_uuid,
            json_pointer=json_pointer,
            value_hash=value_hash,
            last_verified_revision_id=anchor_uuid,
            status="ACTIVE",
            created_by=uuid.UUID(str(user_id)) if user_id else None,
        )
        db.add(lock)
        db.flush()
        return lock

    @staticmethod
    def verify_field_locks_for_items(
        db: Session,
        items_and_revisions: list[tuple[AIArtifactItem, AIArtifactRevision]],
    ) -> None:
        """校验活动 FieldLock 是否在候选成员中被破坏，若值或路径发生冲突则抛出 LOCK_CONFLICT。"""
        for item, rev in items_and_revisions:
            active_locks_stmt = select(AIFieldLock).where(
                AIFieldLock.artifact_item_id == item.id,
                AIFieldLock.status == "ACTIVE",
            )
            locks = db.scalars(active_locks_stmt).all()

            for lock in locks:
                try:
                    val = get_value_by_json_pointer(rev.content, lock.json_pointer)
                    curr_hash = calculate_canonical_hash(val)
                    if curr_hash != lock.value_hash:
                        raise AppError(
                            code="LOCK_CONFLICT",
                            message=(
                                f"锁定字段 {lock.json_pointer} 在新 Revision 中值被改变 "
                                f"(expected hash: {lock.value_hash[:8]}, got: {curr_hash[:8]})"
                            ),
                            status_code=409,
                        )
                except Exception as exc:
                    if isinstance(exc, AppError) and exc.code == "LOCK_CONFLICT":
                        raise
                    raise AppError(
                        code="LOCK_CONFLICT",
                        message=f"锁定字段 {lock.json_pointer} 在新 Revision 中不存在或路径失效",
                        status_code=409,
                    ) from exc

    @staticmethod
    def release_field_lock(
        db: Session, field_lock_id: str, released_by: str | None = None
    ) -> AIFieldLock:
        lock_uuid = uuid.UUID(str(field_lock_id))
        lock = db.get(AIFieldLock, lock_uuid)
        if not lock:
            raise AppError(
                code="LOCK_POINTER_INVALID",
                message=f"锁记录 {field_lock_id} 不存在",
                status_code=404,
            )

        if lock.status == "RELEASED":
            raise AppError(
                code="LOCK_ALREADY_RELEASED",
                message="该字段锁已被释放",
                status_code=400,
            )

        lock.status = "RELEASED"
        lock.released_by = uuid.UUID(str(released_by)) if released_by else None
        db.flush()
        return lock
