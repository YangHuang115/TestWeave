"""M06 执行证据服务。证据必须绑定明确的 execution_record_id。"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import ExecutionEvidence, ExecutionRecord
from testweave.modules.audit.service import AuditService

# 文件类证据允许的类型
ALLOWED_FILE_EVIDENCE_TYPES = {"IMAGE", "TEXT_LOG", "ARCHIVE_LOG"}
# 外部链接仅允许 https
MAX_EVIDENCE_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _assert_record_in_task(
    db: Session, project_id: str, task_id: str, record_id: str
) -> ExecutionRecord:
    rec = db.get(ExecutionRecord, uuid.UUID(str(record_id)))
    if (
        rec is None
        or rec.project_id != uuid.UUID(str(project_id))
        or rec.execution_task_id != uuid.UUID(str(task_id))
    ):
        raise AppError(
            code="EXECUTION_RECORD_NOT_FOUND",
            message="执行记录不存在或无权限访问",
            status_code=404,
        )
    return rec


def validate_external_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AppError(
            code="EXECUTION_EVIDENCE_INVALID",
            message="外部链接证据必须使用 https 协议",
            status_code=400,
        )


def create_external_link_evidence(
    db: Session,
    project_id: str,
    task_id: str,
    record_id: str,
    url: str,
    actor_id: str,
    request_id: str,
) -> ExecutionEvidence:
    rec = _assert_record_in_task(db, project_id, task_id, record_id)
    validate_external_url(url)
    ev = ExecutionEvidence(
        project_id=uuid.UUID(str(project_id)),
        execution_record_id=rec.id,
        evidence_type="EXTERNAL_LINK",
        external_url=url,
        created_by=uuid.UUID(str(actor_id)),
    )
    db.add(ev)
    db.flush()
    AuditService.log_event(
        db,
        action="test_execution.evidence_attached",
        object_type="ExecutionRecord",
        object_id=str(rec.id),
        summary="附加外部链接证据",
        request_id=request_id,
        project_id=uuid.UUID(str(project_id)),
        actor_id=uuid.UUID(str(actor_id)),
    )
    return ev


def create_file_evidence(
    db: Session,
    project_id: str,
    task_id: str,
    record_id: str,
    evidence_type: str,
    object_key: str,
    file_name: str | None,
    mime_type: str | None,
    file_size: int | None,
    checksum: str | None,
    actor_id: str,
    request_id: str,
) -> ExecutionEvidence:
    rec = _assert_record_in_task(db, project_id, task_id, record_id)
    if evidence_type not in ALLOWED_FILE_EVIDENCE_TYPES:
        raise AppError(
            code="EXECUTION_EVIDENCE_INVALID",
            message=f"不支持的证据类型: {evidence_type}",
            status_code=400,
        )
    if file_size is not None and file_size > MAX_EVIDENCE_FILE_SIZE:
        raise AppError(
            code="EXECUTION_EVIDENCE_INVALID",
            message="证据文件大小超出限制（最大 50MB）",
            status_code=400,
        )
    ev = ExecutionEvidence(
        project_id=uuid.UUID(str(project_id)),
        execution_record_id=rec.id,
        evidence_type=evidence_type,
        object_key=object_key,
        file_name=file_name,
        mime_type=mime_type,
        file_size=file_size,
        checksum=checksum,
        created_by=uuid.UUID(str(actor_id)),
    )
    db.add(ev)
    db.flush()
    AuditService.log_event(
        db,
        action="test_execution.evidence_attached",
        object_type="ExecutionRecord",
        object_id=str(rec.id),
        summary=f"附加文件证据: {file_name or object_key}",
        request_id=request_id,
        project_id=uuid.UUID(str(project_id)),
        actor_id=uuid.UUID(str(actor_id)),
    )
    return ev


def list_evidences(
    db: Session, project_id: str, task_id: str, record_id: str
) -> list[ExecutionEvidence]:
    _assert_record_in_task(db, project_id, task_id, record_id)
    stmt = (
        select(ExecutionEvidence)
        .where(ExecutionEvidence.execution_record_id == uuid.UUID(str(record_id)))
        .order_by(ExecutionEvidence.created_at.asc())
    )
    return list(db.scalars(stmt).all())
