import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from fastapi import APIRouter, Depends, Request, Path, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, func, or_
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import User, TestTask, TestTaskStatusHistory, TestTaskBlockage, ProjectMember, TestTaskParticipant, TestTaskRequirement
from testweave.modules.test_tasks.service import TestTaskService
from testweave.shared.permissions import TASK_READ, TASK_MANAGE

router = APIRouter(prefix="/projects/{projectId}/test-tasks", tags=["test-tasks"])


# ==============================================================================
# Pydantic Schemas
# ==============================================================================
class TestTaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    versionId: uuid.UUID = Field(..., alias="versionId")
    taskType: str = Field(..., alias="taskType", pattern="^(CASE_DESIGN|TEST_EXECUTION)$")
    ownerId: uuid.UUID = Field(..., alias="ownerId")
    plannedStartAt: datetime | None = Field(None, alias="plannedStartAt")
    plannedEndAt: datetime = Field(..., alias="plannedEndAt")
    priority: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH|URGENT)$")
    description: str | None = None
    testGoal: str | None = Field(None, alias="testGoal")
    excludedScope: str | None = Field(None, alias="excludedScope")
    tagsJson: list[str] | None = Field(None, alias="tagsJson")
    requirementId: uuid.UUID | None = Field(None, alias="requirementId")

    model_config = {
        "populate_by_name": True
    }


class TestTaskUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    priority: str = Field(..., pattern="^(LOW|MEDIUM|HIGH|URGENT)$")
    ownerId: uuid.UUID = Field(..., alias="ownerId")
    plannedStartAt: datetime = Field(..., alias="plannedStartAt")
    plannedEndAt: datetime = Field(..., alias="plannedEndAt")
    description: str | None = None
    testGoal: str | None = Field(None, alias="testGoal")
    excludedScope: str | None = Field(None, alias="excludedScope")
    tagsJson: list[str] | None = Field(None, alias="tagsJson")
    rowVersion: int = Field(..., alias="rowVersion")

    model_config = {
        "populate_by_name": True
    }


class TestTaskRequirementsRequest(BaseModel):
    requirementId: uuid.UUID | None = Field(None, alias="requirementId")

    model_config = {
        "populate_by_name": True
    }


class TestTaskParticipantsRequest(BaseModel):
    userIds: list[uuid.UUID] = Field(..., alias="userIds")

    model_config = {
        "populate_by_name": True
    }


class TestTaskTransitionRequest(BaseModel):
    targetStatus: str = Field(..., alias="targetStatus")
    reasonCode: str | None = Field(None, alias="reasonCode")
    reasonText: str | None = Field(None, alias="reasonText")
    rowVersion: int = Field(..., alias="rowVersion")

    model_config = {
        "populate_by_name": True
    }


class TestTaskResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID = Field(..., alias="projectId")
    version_id: uuid.UUID = Field(..., alias="versionId")
    task_no: str = Field(..., alias="taskNo")
    task_type: str = Field(..., alias="taskType")
    status: str
    title: str
    description: str | None
    priority: str
    owner_id: uuid.UUID = Field(..., alias="ownerId")
    planned_start_at: datetime = Field(..., alias="plannedStartAt")
    planned_end_at: datetime = Field(..., alias="plannedEndAt")
    actual_started_at: datetime | None = Field(None, alias="actualStartedAt")
    current_completed_at: datetime | None = Field(None, alias="currentCompletedAt")
    completion_count: int = Field(..., alias="completionCount")
    completion_note: str | None = Field(None, alias="completionNote")
    test_goal: str | None = Field(None, alias="testGoal")
    excluded_scope: str | None = Field(None, alias="excludedScope")
    tags_json: list[str] | None = Field(None, alias="tagsJson")
    previous_status: str | None = Field(None, alias="previousStatus")
    row_version: int = Field(..., alias="rowVersion")
    created_by: uuid.UUID | None = Field(None, alias="createdBy")
    created_at: datetime = Field(..., alias="createdAt")
    updated_by: uuid.UUID | None = Field(None, alias="updatedBy")
    updated_at: datetime = Field(..., alias="updatedAt")
    archived_at: datetime | None = Field(None, alias="archivedAt")
    
    # 额外附加字段供前端展示，在API端点中组装
    ownerName: str | None = None
    isBlocked: bool = False
    isOverdue: bool = False
    activeBlockageReason: str | None = None
    requirementId: uuid.UUID | None = None
    requirementNo: str | None = None
    requirementTitle: str | None = None

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class TestTaskListResponse(BaseModel):
    items: list[TestTaskResponse]
    total: int


class TestTaskRequirementsResponse(BaseModel):
    warnings: list[dict]
    task: TestTaskResponse



class TestTaskActivityResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID = Field(..., alias="projectId")
    task_id: uuid.UUID = Field(..., alias="taskId")
    from_status: str = Field(..., alias="fromStatus")
    to_status: str = Field(..., alias="toStatus")
    reason_code: str | None = Field(None, alias="reasonCode")
    reason_text: str | None = Field(None, alias="reasonText")
    actor_id: uuid.UUID | None = Field(None, alias="actorId")
    actorName: str | None = None
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class TestTaskSummaryResponse(BaseModel):
    myDraftAndReadyCount: int
    myInProgressCount: int
    myParticipantCount: int
    blockedCount: int
    overdueCount: int
    dueSoonCount: int
    recentTasks: list[TestTaskResponse]


# ==============================================================================
# Helper functions
# ==============================================================================
def populate_task_display_fields(db: Session, task: TestTask) -> TestTaskResponse:
    res = TestTaskResponse.model_validate(task)
    
    # owner name
    owner = db.get(User, task.owner_id)
    if owner:
        res.ownerName = owner.display_name
        
    # overdue
    now_time = datetime.now(UTC)
    res.isOverdue = (
        task.planned_end_at.replace(tzinfo=None) < now_time.replace(tzinfo=None) and
        task.status not in ["COMPLETED", "CANCELLED", "ARCHIVED"]
    )
    
    # blocked blockage reason
    res.isBlocked = (task.status == "BLOCKED")
    if res.isBlocked:
        blockage_stmt = select(TestTaskBlockage).where(
            TestTaskBlockage.task_id == task.id,
            TestTaskBlockage.resolved_at.is_(None)
        ).order_by(TestTaskBlockage.blocked_at.desc())
        block = db.scalar(blockage_stmt)
        if block:
            res.activeBlockageReason = block.description

    # requirement details
    req_link_stmt = select(TestTaskRequirement).where(TestTaskRequirement.task_id == task.id)
    link = db.scalar(req_link_stmt)
    if link:
        res.requirementId = link.requirement_id
        from testweave.db.models import Requirement
        req = db.get(Requirement, link.requirement_id)
        if req:
            res.requirementNo = req.requirement_no
            res.requirementTitle = req.title
            
    return res


# ==============================================================================
# API Endpoints
# ==============================================================================

@router.get("/my-summary", response_model=TestTaskSummaryResponse)
def get_my_summary(
    projectId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_READ)),
):
    """当前用户在当前项目下的测试任务工作台摘要数据"""
    now_time = datetime.now(UTC)
    now_naive = now_time.replace(tzinfo=None)

    # 我负责的待开始/进行中
    my_draft_ready = db.query(func.count(TestTask.id)).where(
        TestTask.project_id == projectId,
        TestTask.owner_id == current_user.id,
        TestTask.status.in_(["DRAFT", "READY"])
    ).scalar() or 0

    my_in_progress = db.query(func.count(TestTask.id)).where(
        TestTask.project_id == projectId,
        TestTask.owner_id == current_user.id,
        TestTask.status == "IN_PROGRESS"
    ).scalar() or 0

    # 我参与的任务
    my_participant = db.query(func.count(TestTask.id)).join(
        TestTaskParticipant, TestTaskParticipant.task_id == TestTask.id
    ).where(
        TestTask.project_id == projectId,
        TestTaskParticipant.user_id == current_user.id
    ).scalar() or 0

    # 项目内已阻塞数
    blocked = db.query(func.count(TestTask.id)).where(
        TestTask.project_id == projectId,
        TestTask.status == "BLOCKED"
    ).scalar() or 0

    # 项目内已超期
    overdue = db.query(func.count(TestTask.id)).where(
        TestTask.project_id == projectId,
        TestTask.planned_end_at < now_time,
        TestTask.status.not_in(["COMPLETED", "CANCELLED", "ARCHIVED"])
    ).scalar() or 0

    # 即将到期数（3天内到期，未完成）
    due_soon_limit = now_time + timedelta(days=3)
    due_soon = db.query(func.count(TestTask.id)).where(
        TestTask.project_id == projectId,
        TestTask.planned_end_at >= now_time,
        TestTask.planned_end_at <= due_soon_limit,
        TestTask.status.not_in(["COMPLETED", "CANCELLED", "ARCHIVED"])
    ).scalar() or 0

    # 最近更新的任务 (最多5个)
    stmt = select(TestTask).where(
        TestTask.project_id == projectId
    ).order_by(TestTask.updated_at.desc()).limit(5)
    recent = db.scalars(stmt).all()

    return {
        "myDraftAndReadyCount": my_draft_ready,
        "myInProgressCount": my_in_progress,
        "myParticipantCount": my_participant,
        "blockedCount": blocked,
        "overdueCount": overdue,
        "dueSoonCount": due_soon,
        "recentTasks": [populate_task_display_fields(db, t) for t in recent]
    }


@router.get("", response_model=TestTaskListResponse)
def list_tasks(
    projectId: uuid.UUID = Path(...),
    q: str | None = Query(None),
    versionId: uuid.UUID | None = Query(None),
    taskType: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    ownerId: uuid.UUID | None = Query(None),
    participantId: uuid.UUID | None = Query(None),
    isBlocked: bool | None = Query(None),
    isOverdue: bool | None = Query(None),
    sortBy: str = Query("updated_at"),
    sortOrder: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_READ)),
):
    """查询项目测试任务列表"""
    now_time = datetime.now(UTC)
    stmt = select(TestTask).where(TestTask.project_id == projectId)

    if q and q.strip():
        search_pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                TestTask.task_no.ilike(search_pattern),
                TestTask.title.ilike(search_pattern)
            )
        )
    if versionId:
        stmt = stmt.where(TestTask.version_id == versionId)
    if taskType:
        stmt = stmt.where(TestTask.task_type == taskType)
    if status:
        stmt = stmt.where(TestTask.status == status)
    if priority:
        stmt = stmt.where(TestTask.priority == priority)
    if ownerId:
        stmt = stmt.where(TestTask.owner_id == ownerId)
    if participantId:
        stmt = stmt.join(TestTaskParticipant, TestTaskParticipant.task_id == TestTask.id).where(
            TestTaskParticipant.user_id == participantId
        )
    if isBlocked is not None:
        if isBlocked:
            stmt = stmt.where(TestTask.status == "BLOCKED")
        else:
            stmt = stmt.where(TestTask.status != "BLOCKED")
    if isOverdue is not None:
        if isOverdue:
            stmt = stmt.where(
                TestTask.planned_end_at < now_time,
                TestTask.status.not_in(["COMPLETED", "CANCELLED", "ARCHIVED"])
            )
        else:
            stmt = stmt.where(
                ~and_(
                    TestTask.planned_end_at < now_time,
                    TestTask.status.not_in(["COMPLETED", "CANCELLED", "ARCHIVED"])
                )
            )

    # Total Count
    total = db.query(func.count()).select_from(stmt.subquery()).scalar() or 0

    # Sorting
    sort_col = TestTask.updated_at
    if sortBy == "planned_end_at":
        sort_col = TestTask.planned_end_at
    elif sortBy == "priority":
        sort_col = TestTask.priority

    if sortOrder == "asc":
        stmt = stmt.order_by(sort_col.asc())
    else:
        stmt = stmt.order_by(sort_col.desc())

    # Limit and Offset
    stmt = stmt.offset(offset).limit(limit)
    tasks = db.scalars(stmt).all()

    return {
        "items": [populate_task_display_fields(db, t) for t in tasks],
        "total": total
    }


@router.post("", response_model=TestTaskResponse, status_code=201)
def create_task(
    projectId: uuid.UUID = Path(...),
    payload: TestTaskCreateRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_MANAGE)),
):
    """创建测试任务"""
    task = TestTaskService.create_task(
        db,
        project_id=str(projectId),
        version_id=str(payload.versionId),
        task_type=payload.taskType,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        owner_id=str(payload.ownerId),
        planned_start_at=payload.plannedStartAt,
        planned_end_at=payload.plannedEndAt,
        test_goal=payload.testGoal,
        excluded_scope=payload.excludedScope,
        tags_json=payload.tagsJson,
        actor_id=str(current_user.id),
        request_id=request_id,
        requirement_id=str(payload.requirementId) if payload.requirementId else None,
    )
    db.commit()
    return populate_task_display_fields(db, task)


@router.get("/{taskId}", response_model=TestTaskResponse)
def get_task(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_READ)),
):
    """获取任务详情"""
    task = TestTaskService.get_task_by_id(db, str(projectId), str(taskId))
    return populate_task_display_fields(db, task)


@router.patch("/{taskId}", response_model=TestTaskResponse)
def update_task(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    payload: TestTaskUpdateRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_MANAGE)),
):
    """更新任务基本信息"""
    task = TestTaskService.update_task(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        owner_id=str(payload.ownerId),
        planned_start_at=payload.plannedStartAt,
        planned_end_at=payload.plannedEndAt,
        test_goal=payload.testGoal,
        excluded_scope=payload.excludedScope,
        tags_json=payload.tagsJson,
        expected_row_version=payload.rowVersion,
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
    return populate_task_display_fields(db, task)


@router.put("/{taskId}/requirements", response_model=TestTaskRequirementsResponse)
def update_requirements(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    payload: TestTaskRequirementsRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_MANAGE)),
):
    """更新关联的需求，返回非阻断的重复覆盖警告"""
    warnings = TestTaskService.update_requirements(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        requirement_id=str(payload.requirementId) if payload.requirementId else None,
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
    
    # 重新读取以获取乐观锁更新后的最新数据
    task = TestTaskService.get_task_by_id(db, str(projectId), str(taskId))
    return {
        "warnings": warnings,
        "task": populate_task_display_fields(db, task)
    }


@router.put("/{taskId}/participants", response_model=TestTaskResponse)
def update_participants(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    payload: TestTaskParticipantsRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_MANAGE)),
):
    """更新参与人列表"""
    TestTaskService.update_participants(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        user_ids=[str(uid) for uid in payload.userIds],
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()
    task = TestTaskService.get_task_by_id(db, str(projectId), str(taskId))
    return populate_task_display_fields(db, task)


@router.post("/{taskId}/transitions", response_model=TestTaskResponse)
def transition_status(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    payload: TestTaskTransitionRequest = Body(...),
    request_id: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_MANAGE)),
):
    """执行状态机迁移"""
    # 校验用户在该项目下的角色是否为 admin 或者是 lead
    member_stmt = select(ProjectMember).where(
        ProjectMember.project_id == projectId,
        ProjectMember.user_id == current_user.id
    )
    member = db.scalar(member_stmt)
    is_admin_or_lead = False
    if current_user.is_system_admin:
        is_admin_or_lead = True
    elif member and member.role_id in ["project_admin", "test_lead"]:
        is_admin_or_lead = True

    task = TestTaskService.transition_status(
        db,
        project_id=str(projectId),
        task_id=str(taskId),
        target_status=payload.targetStatus,
        reason_code=payload.reasonCode,
        reason_text=payload.reasonText,
        expected_row_version=payload.rowVersion,
        actor_id=str(current_user.id),
        request_id=request_id,
        is_admin_or_lead=is_admin_or_lead,
    )
    db.commit()
    return populate_task_display_fields(db, task)


@router.get("/{taskId}/activities", response_model=list[TestTaskActivityResponse])
def list_activities(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_READ)),
):
    """查询任务的历史流转和活动时间线"""
    # 获取任务以校验项目隔离
    TestTaskService.get_task_by_id(db, str(projectId), str(taskId))

    stmt = select(TestTaskStatusHistory).where(
        TestTaskStatusHistory.task_id == taskId
    ).order_by(TestTaskStatusHistory.created_at.desc()).offset(offset).limit(limit)
    histories = db.scalars(stmt).all()

    results = []
    for h in histories:
        resp = TestTaskActivityResponse.model_validate(h)
        if h.actor_id:
            actor = db.get(User, h.actor_id)
            if actor:
                resp.actorName = actor.display_name
        results.append(resp)

    return results


@router.get("/{taskId}/requirements", response_model=list[Any])
def get_task_requirements(
    projectId: uuid.UUID = Path(...),
    taskId: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _project: Any = Depends(require_project_permission(TASK_READ)),
):
    """查询任务当前关联的全部需求"""
    # 校验项目隔离
    TestTaskService.get_task_by_id(db, str(projectId), str(taskId))

    stmt = (
        select(Requirement)
        .join(TestTaskRequirement, TestTaskRequirement.requirement_id == Requirement.id)
        .where(TestTaskRequirement.task_id == taskId)
    )
    reqs = db.scalars(stmt).all()
    
    # 动态转化为符合 RequirementResponse 驼峰输出要求的 dict 列表
    # 我们也可以直接 import RequirementResponse
    from testweave.api.v1.requirements import RequirementResponse
    return [RequirementResponse.model_validate(r) for r in reqs]
