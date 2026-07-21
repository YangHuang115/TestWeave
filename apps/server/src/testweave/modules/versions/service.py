import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, desc, select, func
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import Version, Project
from testweave.modules.audit.service import AuditService


class VersionService:
    @staticmethod
    def list_versions(
        db: Session,
        *,
        project_id: uuid.UUID,
        name_or_key: str | None = None,
        status: str | None = None,
        owner_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Version], int]:
        """获取版本列表，支持条件筛选、分页与排序"""
        stmt = select(Version).where(Version.project_id == project_id)

        if name_or_key:
            name_or_key_like = f"%{name_or_key}%"
            stmt = stmt.where(
                (Version.name.ilike(name_or_key_like)) | (Version.key.ilike(name_or_key_like))
            )

        if status:
            stmt = stmt.where(Version.status == status)

        if owner_id:
            stmt = stmt.where(Version.owner_id == owner_id)

        # 排序：按更新时间降序
        stmt = stmt.order_by(desc(Version.updated_at))
        
        # 统计总数
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(count_stmt) or 0

        # 分页
        stmt = stmt.offset(offset).limit(limit)
        versions = list(db.scalars(stmt).all())

        return versions, total

    @staticmethod
    def get_version(db: Session, project_id: uuid.UUID, version_id: uuid.UUID) -> Version | None:
        """获取项目下的特定版本，带项目归属校验"""
        version = db.get(Version, version_id)
        if version and version.project_id == project_id:
            return version
        return None

    @staticmethod
    def create_version(
        db: Session,
        *,
        project_id: uuid.UUID,
        key: str,
        name: str,
        description: str | None = None,
        owner_id: uuid.UUID,
        planned_start_at: datetime | None = None,
        planned_end_at: datetime | None = None,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> Version:
        """创建新版本"""
        # 校验项目是否存在
        project = db.get(Project, project_id)
        if not project:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)

        if planned_start_at and planned_end_at and planned_end_at < planned_start_at:
            raise AppError(
                code="VERSION_TIME_INVALID",
                message="计划结束时间不能早于计划开始时间",
                status_code=422,
            )

        # 唯一性校验
        key_stripped = key.strip()
        key_normalized = key_stripped.lower()  # trim + casefold

        stmt = select(Version).where(
            and_(Version.project_id == project_id, Version.key_normalized == key_normalized)
        )
        if db.scalar(stmt):
            raise AppError(
                code="VERSION_KEY_CONFLICT",
                message="版本标识在该项目下已存在",
                status_code=409,
            )

        version = Version(
            project_id=project_id,
            key=key_stripped,
            key_normalized=key_normalized,
            name=name,
            description=description,
            status="PLANNING",
            owner_id=owner_id,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
            row_version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(version)
        db.flush()

        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="version.created",
            object_type="version",
            object_id=str(version.id),
            summary=f"创建版本 '{name}' (标识: {key_stripped})",
            request_id=request_id,
        )
        return version

    @staticmethod
    def update_version(
        db: Session,
        *,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        name: str,
        description: str | None,
        owner_id: uuid.UUID,
        status: str,
        planned_start_at: datetime | None,
        planned_end_at: datetime | None,
        actor_id: uuid.UUID,
        request_id: str,
        expected_row_version: int,
    ) -> Version:
        """更新版本（含乐观锁校验与状态流转控制）"""
        version = VersionService.get_version(db, project_id, version_id)
        if not version:
            raise AppError(code="VERSION_NOT_FOUND", message="版本不存在或不属于当前项目", status_code=404)

        if version.status == "ARCHIVED":
            raise AppError(code="VERSION_ARCHIVED", message="已归档版本处于只读状态，无法修改", status_code=403)

        # 乐观锁校验
        if version.row_version != expected_row_version:
            raise AppError(
                code="OPTIMISTIC_LOCK_CONFLICT",
                message="版本已被其他用户修改，请刷新页面后重试",
                status_code=409,
            )

        if planned_start_at and planned_end_at and planned_end_at < planned_start_at:
            raise AppError(
                code="VERSION_TIME_INVALID",
                message="计划结束时间不能早于计划开始时间",
                status_code=422,
            )

        # 状态流转校验
        # 状态流转：PLANNING -> ACTIVE -> TESTING -> RELEASED
        valid_transitions = {
            "PLANNING": {"PLANNING", "ACTIVE", "ARCHIVED"},
            "ACTIVE": {"ACTIVE", "TESTING", "ARCHIVED"},
            "TESTING": {"ACTIVE", "TESTING", "RELEASED", "ARCHIVED"},
            "RELEASED": {"RELEASED", "ARCHIVED"},
        }
        
        if status not in valid_transitions.get(version.status, set()):
            raise AppError(
                code="VERSION_STATUS_TRANSITION_INVALID",
                message=f"不允许从状态 '{version.status}' 变更为 '{status}'",
                status_code=422,
            )

        version.name = name
        version.description = description
        version.owner_id = owner_id
        version.status = status
        version.planned_start_at = planned_start_at
        version.planned_end_at = planned_end_at
        version.row_version += 1
        version.updated_by = actor_id
        version.updated_at = datetime.now(UTC)

        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="version.updated",
            object_type="version",
            object_id=str(version.id),
            summary=f"修改版本 '{name}' (状态: {status})",
            request_id=request_id,
        )
        return version

    @staticmethod
    def archive_version(
        db: Session,
        *,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> Version:
        """归档版本"""
        version = VersionService.get_version(db, project_id, version_id)
        if not version:
            raise AppError(code="VERSION_NOT_FOUND", message="版本不存在或不属于当前项目", status_code=404)

        if version.status == "ARCHIVED":
            return version

        version.previous_status = version.status
        version.status = "ARCHIVED"
        version.row_version += 1
        version.updated_by = actor_id
        version.updated_at = datetime.now(UTC)

        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="version.archived",
            object_type="version",
            object_id=str(version.id),
            summary=f"归档版本 '{version.name}'",
            request_id=request_id,
        )
        return version

    @staticmethod
    def restore_version(
        db: Session,
        *,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> Version:
        """从归档状态中恢复版本"""
        version = VersionService.get_version(db, project_id, version_id)
        if not version:
            raise AppError(code="VERSION_NOT_FOUND", message="版本不存在或不属于当前项目", status_code=404)

        if version.status != "ARCHIVED":
            raise AppError(code="VERSION_NOT_ARCHIVED", message="版本未处于归档状态，无法恢复", status_code=422)

        restore_status = version.previous_status or "PLANNING"
        version.status = restore_status
        version.previous_status = None
        version.row_version += 1
        version.updated_by = actor_id
        version.updated_at = datetime.now(UTC)

        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="version.restored",
            object_type="version",
            object_id=str(version.id),
            summary=f"恢复版本 '{version.name}' 至 '{restore_status}' 状态",
            request_id=request_id,
        )
        return version
