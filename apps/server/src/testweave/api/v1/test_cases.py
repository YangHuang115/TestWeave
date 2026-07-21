import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import (
    TestCase,
    TestCaseModuleRelation,
    TestCaseRevision,
    TestCaseStep,
    User,
)
from testweave.modules.cases.service import CaseMindmapService, TestCaseService
from testweave.shared.permissions import VERSION_MANAGE, VERSION_READ

router = APIRouter(prefix="/projects/{projectId}")


# ==============================================================================
# Pydantic Schemas
# ==============================================================================
class TestCaseStepRequest(BaseModel):
    action: str = Field(..., min_length=1)
    expectedResult: str = Field(..., alias="expectedResult")
    note: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class TestCaseCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    precondition: str | None = None
    priority: str = Field("MEDIUM", pattern="^(HIGH|MEDIUM|LOW|URGENT)$")
    caseType: str = Field("FUNCTIONAL", alias="caseType")
    tagsJson: list[str] = Field(default_factory=list, alias="tagsJson")
    testDataNote: str | None = Field(None, alias="testDataNote")
    note: str | None = None
    steps: list[TestCaseStepRequest] = Field(default_factory=list)
    sourceTaskId: UUID | None = Field(None, alias="sourceTaskId")
    moduleIds: list[UUID] | None = Field(None, alias="moduleIds")

    model_config = ConfigDict(populate_by_name=True)


class TestCaseStepResponse(BaseModel):
    id: UUID
    step_order: int = Field(..., serialization_alias="stepOrder")
    action: str
    expected_result: str = Field(..., serialization_alias="expectedResult")
    note: str | None

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TestCaseResponse(BaseModel):
    id: UUID
    project_id: UUID = Field(..., serialization_alias="projectId")
    case_no: str = Field(..., serialization_alias="caseNo")
    title: str
    precondition: str | None
    priority: str
    case_type: str = Field(..., serialization_alias="caseType")
    tags_json: list[str] = Field(..., serialization_alias="tagsJson")
    test_data_note: str | None = Field(None, serialization_alias="testDataNote")
    note: str | None
    source_task_id: UUID | None = Field(None, serialization_alias="sourceTaskId")
    current_revision_id: UUID | None = Field(None, serialization_alias="currentRevisionId")
    row_version: int = Field(..., serialization_alias="rowVersion")
    created_by: UUID = Field(..., serialization_alias="createdBy")
    updated_by: UUID = Field(..., serialization_alias="updatedBy")
    created_at: datetime = Field(..., serialization_alias="createdAt")
    updated_at: datetime = Field(..., serialization_alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TestCaseDetailResponse(TestCaseResponse):
    steps: list[TestCaseStepResponse] = Field(default_factory=list)
    module_ids: list[UUID] = Field(default_factory=list, serialization_alias="moduleIds")


class TestCaseEditSessionResponse(BaseModel):
    id: UUID
    case_id: UUID = Field(..., serialization_alias="caseId")
    actor_id: UUID = Field(..., serialization_alias="actorId")
    base_revision_id: UUID | None = Field(None, serialization_alias="baseRevisionId")
    base_row_version: int = Field(..., serialization_alias="baseRowVersion")
    status: str
    dirty_fields: dict[str, Any] = Field(..., serialization_alias="dirtyFields")
    started_at: datetime = Field(..., serialization_alias="startedAt")
    last_activity_at: datetime = Field(..., serialization_alias="lastActivityAt")
    finalized_at: datetime | None = Field(None, serialization_alias="finalizedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TestCaseDraftUpdateRequest(BaseModel):
    dirtyFields: dict[str, Any] = Field(..., alias="dirtyFields")

    model_config = ConfigDict(populate_by_name=True)


class TestCaseFinalizeRequest(BaseModel):
    changeSummary: dict[str, Any] = Field(default_factory=dict, alias="changeSummary")

    model_config = ConfigDict(populate_by_name=True)


class TestCaseRevisionResponse(BaseModel):
    id: UUID
    case_id: UUID = Field(..., serialization_alias="caseId")
    revision_no: int = Field(..., serialization_alias="revisionNo")
    snapshot: dict[str, Any]
    snapshot_hash: str = Field(..., serialization_alias="snapshotHash")
    change_summary: dict[str, Any] = Field(..., serialization_alias="changeSummary")
    edit_session_id: UUID | None = Field(None, serialization_alias="editSessionId")
    created_by: UUID = Field(..., serialization_alias="createdBy")
    created_at: datetime = Field(..., serialization_alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TestCaseMindmapResponse(BaseModel):
    id: UUID
    project_id: UUID = Field(..., serialization_alias="projectId")
    task_id: UUID = Field(..., serialization_alias="taskId")
    title: str
    data: dict[str, Any]
    created_at: datetime = Field(..., serialization_alias="createdAt")
    updated_at: datetime = Field(..., serialization_alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TestCaseMindmapSaveRequest(BaseModel):
    title: str
    data: dict[str, Any]


# ==============================================================================

# API Endpoints
# ==============================================================================
@router.post("/test-cases", response_model=TestCaseResponse)
def create_case(
    projectId: UUID,
    payload: TestCaseCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> TestCaseResponse:
    """创建测试用例"""
    req_id = x_request_id or f"req-case-{uuid.uuid4().hex[:8]}"
    steps_payload = [
        {"action": s.action, "expected_result": s.expectedResult, "note": s.note}
        for s in payload.steps
    ]
    module_ids_str = [str(m) for m in payload.moduleIds] if payload.moduleIds else None

    case = TestCaseService.create_case(
        db,
        project_id=str(projectId),
        title=payload.title,
        precondition=payload.precondition,
        priority=payload.priority,
        case_type=payload.caseType,
        tags_json=payload.tagsJson,
        test_data_note=payload.testDataNote,
        note=payload.note,
        steps=steps_payload,
        source_task_id=str(payload.sourceTaskId) if payload.sourceTaskId else None,
        actor_id=str(user.id),
        request_id=req_id,
        module_ids=module_ids_str,
    )
    db.commit()
    return TestCaseResponse.model_validate(case)


@router.get("/test-cases", response_model=list[TestCaseResponse])
def list_cases(
    projectId: UUID,
    moduleId: UUID | None = Query(None, alias="moduleId"),
    keyword: str | None = Query(None),
    priority: str | None = Query(None),
    caseType: str | None = Query(None, alias="caseType"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_READ)),
) -> list[TestCaseResponse]:
    """查询项目下的测试用例列表"""
    stmt = select(TestCase).where(TestCase.project_id == projectId, TestCase.deleted_at.is_(None))

    if moduleId:
        stmt = stmt.join(
            TestCaseModuleRelation, TestCase.id == TestCaseModuleRelation.case_id
        ).where(TestCaseModuleRelation.module_id == moduleId)

    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where((TestCase.title.ilike(kw)) | (TestCase.case_no.ilike(kw)))

    if priority:
        stmt = stmt.where(TestCase.priority == priority)

    if caseType:
        stmt = stmt.where(TestCase.case_type == caseType)

    stmt = stmt.order_by(TestCase.created_at.desc())
    cases = db.scalars(stmt).all()
    return [TestCaseResponse.model_validate(c) for c in cases]


@router.get("/test-cases/{caseId}", response_model=TestCaseDetailResponse)
def get_case_detail(
    projectId: UUID,
    caseId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_READ)),
) -> TestCaseDetailResponse:
    """获取用例详情"""
    case = db.get(TestCase, caseId)
    if not case or case.project_id != projectId or case.deleted_at is not None:
        raise AppError(code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404)

    steps_stmt = (
        select(TestCaseStep)
        .where(TestCaseStep.case_id == caseId)
        .order_by(TestCaseStep.step_order)
    )
    steps = db.scalars(steps_stmt).all()

    mod_stmt = select(TestCaseModuleRelation.module_id).where(
        TestCaseModuleRelation.case_id == caseId
    )
    module_ids = db.scalars(mod_stmt).all()

    res = TestCaseDetailResponse.model_validate(case)
    res.steps = [TestCaseStepResponse.model_validate(s) for s in steps]
    res.module_ids = list(module_ids)
    return res


@router.post("/test-cases/{caseId}/edit-sessions", response_model=TestCaseEditSessionResponse)
def start_edit_session(
    projectId: UUID,
    caseId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> TestCaseEditSessionResponse:
    """开启或进入用例编辑会话"""
    session = TestCaseService.start_edit_session(db, case_id=str(caseId), actor_id=str(user.id))
    db.commit()
    return TestCaseEditSessionResponse.model_validate(session)


@router.put(
    "/test-cases/{caseId}/edit-sessions/{sessionId}/draft",
    response_model=TestCaseEditSessionResponse,
)
def update_session_draft(
    projectId: UUID,
    caseId: UUID,
    sessionId: UUID,
    payload: TestCaseDraftUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> TestCaseEditSessionResponse:
    """更新草稿与暂存编辑状态"""
    session = TestCaseService.update_session_draft(
        db,
        session_id=str(sessionId),
        dirty_fields=payload.dirtyFields,
        actor_id=str(user.id),
    )
    db.commit()
    return TestCaseEditSessionResponse.model_validate(session)


@router.post(
    "/test-cases/{caseId}/edit-sessions/{sessionId}/finalize",
    response_model=TestCaseRevisionResponse,
)
def finalize_edit_session(
    projectId: UUID,
    caseId: UUID,
    sessionId: UUID,
    payload: TestCaseFinalizeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> TestCaseRevisionResponse:
    """提交会话发布，生成新修订快照"""
    revision = TestCaseService.finalize_edit_session(
        db,
        session_id=str(sessionId),
        actor_id=str(user.id),
        change_summary=payload.changeSummary,
    )
    db.commit()
    return TestCaseRevisionResponse.model_validate(revision)


@router.post(
    "/test-cases/{caseId}/edit-sessions/{sessionId}/abandon",
    response_model=TestCaseEditSessionResponse,
)
def abandon_edit_session(
    projectId: UUID,
    caseId: UUID,
    sessionId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> TestCaseEditSessionResponse:
    """放弃编辑会话"""
    session = TestCaseService.abandon_edit_session(
        db,
        session_id=str(sessionId),
        actor_id=str(user.id),
    )
    db.commit()
    return TestCaseEditSessionResponse.model_validate(session)


@router.get("/test-cases/{caseId}/revisions", response_model=list[TestCaseRevisionResponse])
def get_case_revisions(
    projectId: UUID,
    caseId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_READ)),
) -> list[TestCaseRevisionResponse]:
    """查询用例的版本修订历史列表"""
    stmt = (
        select(TestCaseRevision)
        .where(TestCaseRevision.case_id == caseId)
        .order_by(TestCaseRevision.revision_no.desc())
    )
    revisions = db.scalars(stmt).all()
    return [TestCaseRevisionResponse.model_validate(r) for r in revisions]


@router.get("/test-tasks/{taskId}/mindmap", response_model=TestCaseMindmapResponse)
def get_or_create_mindmap(
    projectId: UUID,
    taskId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_READ)),
) -> TestCaseMindmapResponse:
    """获取或初始化关联任务的脑图"""
    mindmap = CaseMindmapService.get_or_create_mindmap(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
    )
    return TestCaseMindmapResponse.model_validate(mindmap)


@router.put("/test-tasks/{taskId}/mindmap", response_model=TestCaseMindmapResponse)
def save_mindmap(
    projectId: UUID,
    taskId: UUID,
    payload: TestCaseMindmapSaveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
) -> TestCaseMindmapResponse:
    """保存关联任务的脑图数据"""
    mindmap = CaseMindmapService.save_mindmap(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        title=payload.title,
        data=payload.data,
    )
    db.commit()
    return TestCaseMindmapResponse.model_validate(mindmap)


@router.post("/test-tasks/{taskId}/mindmap/sync")
def sync_mindmap_to_cases(
    projectId: UUID,
    taskId: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(VERSION_MANAGE)),
    request_id: str = Header("", alias="X-Request-Id"),
) -> dict[str, Any]:
    """将脑图分支一键同步为当前任务上下文的测试用例列表"""
    count = CaseMindmapService.sync_mindmap_to_cases(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        actor_id=str(user.id),
        request_id=request_id,
    )
    db.commit()
    return {"status": "SUCCESS", "syncedCount": count}

