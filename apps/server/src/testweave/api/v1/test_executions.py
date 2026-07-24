"""M06 测试执行 API。统一前缀 /api/projects/{projectId}/test-executions。"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Path, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.config import get_settings
from testweave.core.errors import AppError
from testweave.db.models import (
    ExecutionCase,
    ExecutionEvidence,
    ExecutionRecord,
    ExecutionTaskProfile,
    ProjectMember,
    Requirement,
    TestTask,
    User,
)
from testweave.infrastructure.storage import LocalStorageProvider
from testweave.modules.audit.service import AuditService
from testweave.modules.executions import evidence as evidence_service
from testweave.modules.executions.service import (
    ExecutionRecordService,
    ExecutionTaskService,
)
from testweave.modules.executions.xlsx_export import build_xlsx
from testweave.shared.permissions import (
    EXECUTION_EVIDENCE_UPLOAD,
    EXECUTION_MANAGE,
    EXECUTION_READ,
    EXECUTION_RESULT_CREATE,
)

settings = get_settings()

router = APIRouter(prefix="/projects/{projectId}/test-executions", tags=["test-executions"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------
class ExecutionCreateRequest(BaseModel):
    sourceDesignTaskId: uuid.UUID = Field(..., alias="sourceDesignTaskId")
    title: str = Field(..., min_length=1, max_length=200)
    ownerId: uuid.UUID = Field(..., alias="ownerId")
    participantIds: list[uuid.UUID] | None = Field(None, alias="participantIds")
    plannedStartAt: datetime | None = Field(None, alias="plannedStartAt")
    plannedEndAt: datetime = Field(..., alias="plannedEndAt")
    priority: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH|URGENT)$")
    description: str | None = None
    testEnvironment: dict[str, Any] | None = Field(None, alias="testEnvironment")
    buildVersion: str | None = Field(None, alias="buildVersion")
    testGoal: str | None = Field(None, alias="testGoal")
    tagsJson: list[str] | None = Field(None, alias="tagsJson")
    idempotencyKey: str = Field(..., min_length=1, max_length=128, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


class RecordCreateRequest(BaseModel):
    result: str
    actualResult: str | None = Field(None, alias="actualResult")
    note: str | None = None
    reasonCode: str | None = Field(None, alias="reasonCode")
    reasonText: str | None = Field(None, alias="reasonText")
    evidences: list[dict[str, Any]] | None = None
    idempotencyKey: str = Field(..., min_length=1, max_length=128, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


class CorrectionRequest(BaseModel):
    result: str
    actualResult: str | None = Field(None, alias="actualResult")
    note: str | None = None
    reasonCode: str | None = Field(None, alias="reasonCode")
    reasonText: str | None = Field(None, alias="reasonText")
    correctionOfRecordId: uuid.UUID = Field(..., alias="correctionOfRecordId")
    correctionNote: str = Field(..., min_length=1, alias="correctionNote")
    idempotencyKey: str = Field(..., min_length=1, max_length=128, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


class BatchPassRequest(BaseModel):
    executionCaseIds: list[uuid.UUID] = Field(..., alias="executionCaseIds")
    idempotencyKey: str = Field(..., min_length=1, max_length=128, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


class ReopenRequest(BaseModel):
    reasonText: str = Field(..., min_length=1, alias="reasonText")

    model_config = {"populate_by_name": True}


class EvidenceLinkRequest(BaseModel):
    url: str

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_admin_or_lead(db: Session, project_id: uuid.UUID, user: User) -> bool:
    if user.is_system_admin:
        return True
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    return bool(member and member.role_id in ("project_admin", "test_lead"))


def _task_summary(db: Session, task: TestTask) -> dict[str, Any]:
    profile = db.get(ExecutionTaskProfile, task.id)
    source = db.get(TestTask, profile.source_design_task_id) if profile else None
    requirement = db.get(Requirement, profile.source_requirement_id) if profile else None
    return {
        "id": str(task.id),
        "projectId": str(task.project_id),
        "taskNo": task.task_no,
        "title": task.title,
        "status": task.status,
        "rowVersion": task.row_version,
        "ownerId": str(task.owner_id),
        "plannedEndAt": task.planned_end_at,
        "sourceDesignTaskId": str(profile.source_design_task_id) if profile else None,
        "sourceDesignTaskNo": source.task_no if source else None,
        "sourceRequirementId": str(profile.source_requirement_id) if profile else None,
        "sourceRequirementTitle": requirement.title if requirement else None,
        "testEnvironment": profile.test_environment if profile else None,
        "buildVersion": profile.build_version if profile else None,
        "totalCount": profile.total_count if profile else 0,
        "notRunCount": profile.not_run_count if profile else 0,
        "passedCount": profile.passed_count if profile else 0,
        "failedCount": profile.failed_count if profile else 0,
        "blockedCount": profile.blocked_count if profile else 0,
        "skippedCount": profile.skipped_count if profile else 0,
        "executionRecordCount": profile.execution_record_count if profile else 0,
    }


# 延迟导入避免循环：requirements 模型
def _case_summary(case: ExecutionCase) -> dict[str, Any]:
    snap = case.case_snapshot or {}
    latest_by = None
    if case.latest_executed_by:
        latest_by = str(case.latest_executed_by)
    return {
        "id": str(case.id),
        "testCaseId": str(case.test_case_id),
        "testCaseRevisionId": str(case.test_case_revision_id),
        "caseNo": snap.get("caseNo"),
        "title": snap.get("title"),
        "modulePaths": snap.get("modulePaths"),
        "precondition": snap.get("precondition"),
        "priority": snap.get("priority"),
        "caseType": snap.get("caseType"),
        "steps": snap.get("steps", []),
        "currentResult": case.current_result,
        "latestActualResult": case.latest_actual_result,
        "latestNote": case.latest_note,
        "latestExecutedBy": latest_by,
        "latestExecutedAt": case.latest_executed_at,
        "executionCount": case.execution_count,
        "revisionNo": snap.get("revisionNo"),
    }


def _record_summary(rec: ExecutionRecord) -> dict[str, Any]:
    return {
        "id": str(rec.id),
        "executionCaseId": str(rec.execution_case_id),
        "recordNo": rec.record_no,
        "result": rec.result,
        "actualResult": rec.actual_result,
        "note": rec.note,
        "reasonCode": rec.reason_code,
        "reasonText": rec.reason_text,
        "executedBy": str(rec.executed_by),
        "executedAt": rec.executed_at,
        "recordSource": rec.record_source,
        "correctionOfRecordId": (
            str(rec.correction_of_record_id) if rec.correction_of_record_id else None
        ),
        "correctionNote": rec.correction_note,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def create_execution_task(
    projectId: uuid.UUID = Path(...),
    payload: ExecutionCreateRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_MANAGE)),
) -> dict[str, Any]:
    task = ExecutionTaskService.create_execution_task(
        db,
        project_id=str(projectId),
        source_design_task_id=str(payload.sourceDesignTaskId),
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        owner_id=str(payload.ownerId),
        participant_ids=(
            [str(u) for u in payload.participantIds] if payload.participantIds else None
        ),
        planned_start_at=payload.plannedStartAt,
        planned_end_at=payload.plannedEndAt,
        test_environment=payload.testEnvironment,
        build_version=payload.buildVersion,
        test_goal=payload.testGoal,
        tags_json=payload.tagsJson,
        idempotency_key=payload.idempotencyKey,
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
    return _task_summary(db, task)


@router.get("")
def list_execution_tasks(
    projectId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
    limit: int = Query(50),
    offset: int = Query(0),
) -> dict[str, Any]:
    total = (
        db.query(func.count(TestTask.id))
        .where(TestTask.project_id == projectId, TestTask.task_type == "TEST_EXECUTION")
        .scalar()
        or 0
    )
    stmt = (
        select(TestTask)
        .where(TestTask.project_id == projectId, TestTask.task_type == "TEST_EXECUTION")
        .order_by(TestTask.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    tasks = db.scalars(stmt).all()
    return {"items": [_task_summary(db, t) for t in tasks], "total": int(total)}


@router.get("/{taskId}")
def get_execution_task(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
) -> dict[str, Any]:
    task = ExecutionTaskService.get_execution_task(db, str(projectId), str(taskId))
    return _task_summary(db, task)


@router.get("/{taskId}/cases")
def list_cases(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
    limit: int = Query(200),
    offset: int = Query(0),
) -> dict[str, Any]:
    rows, total = ExecutionTaskService.list_execution_cases(
        db, str(projectId), str(taskId), limit, offset
    )
    return {"items": [_case_summary(c) for c in rows], "total": total}


@router.get("/{taskId}/completion-preview")
def completion_preview(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
) -> dict[str, Any]:
    return ExecutionRecordService.completion_preview(db, str(projectId), str(taskId))


@router.post("/{taskId}/complete")
def complete_task(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_MANAGE)),
) -> dict[str, Any]:
    task = ExecutionRecordService.complete(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        actor_id=str(current_user.id),
        request_id=request_id,
        is_admin_or_lead=_is_admin_or_lead(db, projectId, current_user),
    )
    db.commit()
    return _task_summary(db, task)


@router.post("/{taskId}/reopen")
def reopen_task(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    payload: ReopenRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_MANAGE)),
) -> dict[str, Any]:
    task = ExecutionRecordService.reopen(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        reason_text=payload.reasonText,
        actor_id=str(current_user.id),
        request_id=request_id,
        is_admin_or_lead=_is_admin_or_lead(db, projectId, current_user),
    )
    db.commit()
    return _task_summary(db, task)


@router.post("/{taskId}/batch-pass")
def batch_pass(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    payload: BatchPassRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_RESULT_CREATE)),
) -> dict[str, Any]:
    result = ExecutionRecordService.batch_pass(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        execution_case_ids=[str(u) for u in payload.executionCaseIds],
        idempotency_key=payload.idempotencyKey,
        actor_id=str(current_user.id),
        request_id=request_id,
        is_admin_or_lead=_is_admin_or_lead(db, projectId, current_user),
    )
    db.commit()
    return result


@router.post("/{taskId}/cases/{executionCaseId}/records")
def create_record(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    executionCaseId: uuid.UUID = Path(...),
    payload: RecordCreateRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_RESULT_CREATE)),
) -> dict[str, Any]:
    rec = ExecutionRecordService.create_record(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        execution_case_id=str(executionCaseId),
        result=payload.result,
        actual_result=payload.actualResult,
        note=payload.note,
        reason_code=payload.reasonCode,
        reason_text=payload.reasonText,
        evidences=payload.evidences,
        idempotency_key=payload.idempotencyKey,
        actor_id=str(current_user.id),
        request_id=request_id,
        is_admin_or_lead=_is_admin_or_lead(db, projectId, current_user),
    )
    db.commit()
    return _record_summary(rec)


@router.post("/{taskId}/cases/{executionCaseId}/corrections")
def create_correction(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    executionCaseId: uuid.UUID = Path(...),
    payload: CorrectionRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_RESULT_CREATE)),
) -> dict[str, Any]:
    rec = ExecutionRecordService.create_record(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        execution_case_id=str(executionCaseId),
        result=payload.result,
        actual_result=payload.actualResult,
        note=payload.note,
        reason_code=payload.reasonCode,
        reason_text=payload.reasonText,
        evidences=None,
        idempotency_key=payload.idempotencyKey,
        actor_id=str(current_user.id),
        request_id=request_id,
        is_admin_or_lead=_is_admin_or_lead(db, projectId, current_user),
        record_source="CORRECTION",
        correction_of_record_id=str(payload.correctionOfRecordId),
        correction_note=payload.correctionNote,
    )
    db.commit()
    return _record_summary(rec)


@router.get("/{taskId}/cases/{executionCaseId}/records")
def list_records(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    executionCaseId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
    limit: int = Query(100),
    offset: int = Query(0),
) -> dict[str, Any]:
    rows, total = ExecutionRecordService.list_records(
        db, str(projectId), str(taskId), str(executionCaseId), limit, offset
    )
    return {"items": [_record_summary(r) for r in rows], "total": total}


@router.post("/{taskId}/records/{recordId}/evidences/external-link")
def add_external_link_evidence(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    recordId: uuid.UUID = Path(...),
    payload: EvidenceLinkRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_EVIDENCE_UPLOAD)),
) -> dict[str, Any]:
    ev = evidence_service.create_external_link_evidence(
        db,
        str(projectId),
        str(taskId),
        str(recordId),
        payload.url,
        str(current_user.id),
        request_id,
    )
    db.commit()
    return {"id": str(ev.id), "evidenceType": ev.evidence_type, "externalUrl": ev.external_url}


@router.post("/{taskId}/evidences/uploads")
async def upload_evidence(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    request_id: str = Query(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_EVIDENCE_UPLOAD)),
) -> dict[str, Any]:
    # 校验任务属于当前项目
    ExecutionTaskService.get_execution_task(db, str(projectId), str(taskId))

    # 完整读入内存（证据文件 50MB 上限内可接受），计算 sha256 与大小
    content = await file.read()
    total = len(content)
    if total > evidence_service.MAX_EVIDENCE_FILE_SIZE:
        raise AppError(
            code="EXECUTION_EVIDENCE_INVALID",
            message="证据文件大小超出限制（最大 50MB）",
            status_code=400,
        )
    checksum = hashlib.sha256(content).hexdigest()

    storage = LocalStorageProvider(settings.storage_local_dir)
    object_key = f"{projectId}/executions/{uuid.uuid4()}/{file.filename or 'upload'}"

    async def reader() -> AsyncIterator[bytes]:
        yield content

    await storage.save(object_key, reader())
    return {
        "objectKey": object_key,
        "fileName": file.filename,
        "mimeType": file.content_type,
        "fileSize": total,
        "checksum": checksum,
    }


@router.get("/{taskId}/records/{recordId}/evidences")
def list_evidences(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    recordId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
) -> dict[str, Any]:
    rows = evidence_service.list_evidences(db, str(projectId), str(taskId), str(recordId))
    return {
        "items": [
            {
                "id": str(e.id),
                "evidenceType": e.evidence_type,
                "externalUrl": e.external_url,
                "objectKey": e.object_key,
                "fileName": e.file_name,
                "mimeType": e.mime_type,
                "fileSize": e.file_size,
                "createdAt": e.created_at,
            }
            for e in rows
        ]
    }


@router.post("/{taskId}/exports")
async def create_export(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(EXECUTION_READ)),
) -> dict[str, Any]:
    """导出当前执行任务全部用例为 Excel（首版同步生成；固化筛选快照为全部）。"""
    task = ExecutionTaskService.get_execution_task(db, str(projectId), str(taskId))
    profile = ExecutionTaskService.get_profile(db, str(taskId))

    cases = db.scalars(
        select(ExecutionCase)
        .where(ExecutionCase.execution_task_id == task.id)
        .order_by(ExecutionCase.scope_created_at.asc(), ExecutionCase.id.asc())
    ).all()

    header = [
        "用例编号",
        "所属模块",
        "用例标题",
        "前置条件",
        "执行步骤",
        "预期结果",
        "最新结果",
        "实际结果/备注",
        "最近执行人",
        "最近执行时间",
        "执行次数",
        "缺陷数量",
        "证据数量",
        "用例修订",
        "构建版本",
        "测试环境",
    ]
    rows: list[list[Any]] = [header]
    for c in cases:
        snap = c.case_snapshot or {}
        steps = snap.get("steps", [])
        step_text = "\n".join(f"{i + 1}. {s.get('action', '')}" for i, s in enumerate(steps))
        expected_text = "\n".join(
            f"{i + 1}. {s.get('expectedResult', '')}" for i, s in enumerate(steps)
        )
        modules = " / ".join(snap.get("modulePaths", []) or [])
        # 缺陷数量：M07 未接入，固定 0
        defect_count = 0
        evidence_count = (
            db.query(func.count(ExecutionEvidence.id))
            .where(
                ExecutionEvidence.execution_record_id.in_(
                    select(ExecutionRecord.id).where(ExecutionRecord.execution_case_id == c.id)
                )
            )
            .scalar()
            or 0
        )
        rows.append(
            [
                snap.get("caseNo", ""),
                modules,
                snap.get("title", ""),
                snap.get("precondition", ""),
                step_text,
                expected_text,
                c.current_result or "NOT_RUN",
                (c.latest_actual_result or "") + ((" | " + c.latest_note) if c.latest_note else ""),
                str(c.latest_executed_by) if c.latest_executed_by else "",
                c.latest_executed_at.isoformat() if c.latest_executed_at else "",
                c.execution_count,
                defect_count,
                int(evidence_count),
                str(c.test_case_revision_id),
                profile.build_version or "",
                (
                    (profile.test_environment or {}).get("name", "")
                    if isinstance(profile.test_environment, dict)
                    else ""
                ),
            ]
        )

    xlsx_bytes = build_xlsx([{"name": "执行结果", "rows": rows}])
    storage = LocalStorageProvider(settings.storage_local_dir)
    object_key = f"{projectId}/executions/{task.id}/export_{uuid.uuid4()}.xlsx"

    async def xlsx_reader() -> AsyncIterator[bytes]:
        step = 1024 * 1024
        for i in range(0, len(xlsx_bytes), step):
            yield xlsx_bytes[i : i + step]

    await storage.save(object_key, xlsx_reader())

    from testweave.db.models import ExportJob

    job = ExportJob(
        project_id=task.project_id,
        resource_type="EXECUTION_TASK",
        resource_id=task.id,
        status="COMPLETED",
        scope_snapshot={"scope": "ALL", "total": len(cases)},
        file_object_key=object_key,
        file_name=f"{task.task_no}_执行结果.xlsx",
        file_size=len(xlsx_bytes),
        created_by=current_user.id,
    )
    db.add(job)
    db.flush()
    AuditService.log_event(
        db,
        action="test_execution.export_completed",
        object_type="TestTask",
        object_id=str(task.id),
        summary="导出执行结果 Excel",
        request_id=request_id,
        project_id=task.project_id,
        actor_id=current_user.id,
    )
    db.commit()
    return {
        "exportId": str(job.id),
        "status": job.status,
        "fileObjectKey": object_key,
        "fileName": job.file_name,
        "fileSize": job.file_size,
    }
