import hashlib
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import anyio
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.config import get_settings
from testweave.core.errors import AppError
from testweave.db.models import RequirementAttachment
from testweave.infrastructure.storage import DocxSafetyFilter, LocalStorageProvider
from testweave.modules.audit.service import AuditService
from testweave.modules.requirements.service import RequirementService

settings = get_settings()
storage_provider = LocalStorageProvider(settings.storage_local_dir)


class AttachmentService:
    @staticmethod
    async def upload_attachment(
        db: Session,
        project_id: str,
        requirement_id: str,
        file: UploadFile,
        actor_id: str,
        request_id: str,
    ) -> RequirementAttachment:
        filename = file.filename or ""
        if not filename.lower().endswith(".docx"):
            raise AppError(
                code="INVALID_FILE_TYPE",
                message="仅允许上传 Word (.docx) 格式的附件",
                status_code=400,
            )

        # 验证隔离性
        RequirementService.get_requirement_by_id(db, project_id, requirement_id)

        # 写入临时文件，同时限制大小并计算 hash
        temp_fd, temp_path = tempfile.mkstemp(suffix=".docx")
        os.close(temp_fd)

        max_bytes = 20 * 1024 * 1024  # 20MB
        sha256_hash = hashlib.sha256()
        written_bytes = 0

        try:
            async with await anyio.open_file(temp_path, "wb") as f:
                while True:
                    chunk = await file.read(64 * 1024)
                    if not chunk:
                        break
                    written_bytes += len(chunk)
                    if written_bytes > max_bytes:
                        raise AppError(
                            code="FILE_SIZE_LIMIT_EXCEEDED",
                            message="文件大小超过 20MB 限制",
                            status_code=400,
                        )
                    sha256_hash.update(chunk)
                    await f.write(chunk)

            # DOCX 安全过滤
            DocxSafetyFilter.validate(temp_path)

            # 存入正式存储
            attachment_id = uuid.uuid4()
            storage_key = f"{project_id}/{requirement_id}/{attachment_id}.docx"

            async def file_reader() -> AsyncIterator[bytes]:
                async with await anyio.open_file(temp_path, "rb") as tf:
                    while True:
                        c = await tf.read(64 * 1024)
                        if not c:
                            break
                        yield c

            await storage_provider.save(storage_key, file_reader())
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 保存元数据到数据库
        db_attachment = RequirementAttachment(
            id=attachment_id,
            project_id=uuid.UUID(project_id),
            requirement_id=uuid.UUID(requirement_id),
            original_filename=filename,
            content_type=file.content_type
            or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=written_bytes,
            sha256=sha256_hash.hexdigest(),
            storage_key=storage_key,
            status="ACTIVE",
            uploaded_by=uuid.UUID(actor_id),
        )
        db.add(db_attachment)
        db.flush()

        # 审计日志
        AuditService.log_event(
            db,
            action="requirement.attachment_uploaded",
            object_type="Requirement",
            object_id=requirement_id,
            summary=f"上传了附件 '{filename}'",
            request_id=request_id,
            project_id=uuid.UUID(project_id),
            actor_id=uuid.UUID(actor_id),
        )

        return db_attachment

    @staticmethod
    async def get_attachment_stream(
        db: Session,
        project_id: str,
        requirement_id: str,
        attachment_id: str,
        actor_id: str,
        request_id: str,
    ) -> tuple[AsyncIterator[bytes], str, str]:
        # 查找
        attachment = db.get(RequirementAttachment, uuid.UUID(attachment_id))
        if (
            not attachment
            or str(attachment.project_id) != project_id
            or str(attachment.requirement_id) != requirement_id
        ):
            raise AppError(
                code="ATTACHMENT_NOT_FOUND", message="附件不存在或无权访问", status_code=404
            )

        if attachment.status != "ACTIVE":
            raise AppError(
                code="ATTACHMENT_ARCHIVED",
                message="该附件已被归档删除，不允许下载",
                status_code=400,
            )

        # 审计日志
        AuditService.log_event(
            db,
            action="requirement.attachment_downloaded",
            object_type="Requirement",
            object_id=requirement_id,
            summary=f"下载了附件 '{attachment.original_filename}'",
            request_id=request_id,
            project_id=uuid.UUID(project_id),
            actor_id=uuid.UUID(actor_id),
        )

        stream = await storage_provider.get(attachment.storage_key)
        return stream, attachment.original_filename, attachment.content_type

    @staticmethod
    def archive_attachment(
        db: Session,
        project_id: str,
        requirement_id: str,
        attachment_id: str,
        actor_id: str,
        request_id: str,
    ) -> None:
        # 查找
        attachment = db.get(RequirementAttachment, uuid.UUID(attachment_id))
        if (
            not attachment
            or str(attachment.project_id) != project_id
            or str(attachment.requirement_id) != requirement_id
        ):
            raise AppError(
                code="ATTACHMENT_NOT_FOUND", message="附件不存在或无权访问", status_code=404
            )

        if attachment.status == "ARCHIVED":
            return

        attachment.status = "ARCHIVED"
        attachment.archived_at = datetime.now(UTC)
        attachment.archived_by = uuid.UUID(actor_id)
        db.flush()

        # 审计日志
        AuditService.log_event(
            db,
            action="requirement.attachment_archived",
            object_type="Requirement",
            object_id=requirement_id,
            summary=f"归档删除了附件 '{attachment.original_filename}'",
            request_id=request_id,
            project_id=uuid.UUID(project_id),
            actor_id=uuid.UUID(actor_id),
        )

    @staticmethod
    def list_attachments(
        db: Session,
        project_id: str,
        requirement_id: str,
    ) -> list[RequirementAttachment]:
        stmt = (
            select(RequirementAttachment)
            .where(
                RequirementAttachment.project_id == uuid.UUID(str(project_id)),
                RequirementAttachment.requirement_id == uuid.UUID(str(requirement_id)),
                RequirementAttachment.status == "ACTIVE",
            )
            .order_by(RequirementAttachment.uploaded_at.desc())
        )
        return list(db.scalars(stmt).all())
