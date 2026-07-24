from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.db.models import User
from testweave.modules.workbench.schemas import (
    PaginatedResponse,
    RecordRecentVisitRequest,
    WorkbenchAgentRunItem,
    WorkbenchInProgressTask,
    WorkbenchRecentVisit,
    WorkbenchRemainingRequirement,
    WorkbenchSummary,
    WorkbenchTodoItem,
)
from testweave.modules.workbench.service import WorkbenchService
from testweave.shared.permissions import PROJECT_READ

router = APIRouter(prefix="/projects/{projectId}/workbench")


@router.get(
    "/summary",
    response_model=WorkbenchSummary,
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def get_workbench_summary(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return WorkbenchService.get_summary(db, str(projectId), str(current_user.id))


@router.get(
    "/todos",
    response_model=PaginatedResponse[WorkbenchTodoItem],
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def get_workbench_todos(
    projectId: UUID = Path(...),
    type: str | None = Query(None),
    priority: str | None = Query(None),
    is_overdue: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = WorkbenchService.get_todos(
        db,
        project_id=str(projectId),
        user_id=str(current_user.id),
        type_filter=type,
        priority_filter=priority,
        is_overdue_only=is_overdue,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/in-progress-tasks",
    response_model=PaginatedResponse[WorkbenchInProgressTask],
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def get_workbench_in_progress_tasks(
    projectId: UUID = Path(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = WorkbenchService.get_in_progress_tasks(
        db,
        project_id=str(projectId),
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/agent-runs",
    response_model=PaginatedResponse[WorkbenchAgentRunItem],
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def get_workbench_agent_runs(
    projectId: UUID = Path(...),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = WorkbenchService.get_agent_runs(
        db,
        project_id=str(projectId),
        user_id=str(current_user.id),
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/remaining-requirements",
    response_model=PaginatedResponse[WorkbenchRemainingRequirement],
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def get_workbench_remaining_requirements(
    projectId: UUID = Path(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = WorkbenchService.get_remaining_requirements(
        db,
        project_id=str(projectId),
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/recent-visits",
    response_model=PaginatedResponse[WorkbenchRecentVisit],
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def get_workbench_recent_visits(
    projectId: UUID = Path(...),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = WorkbenchService.get_recent_visits(
        db,
        project_id=str(projectId),
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/recent-visits",
    response_model=WorkbenchRecentVisit,
    status_code=201,
    dependencies=[Depends(require_project_permission(PROJECT_READ))],
)
def record_workbench_recent_visit(
    projectId: UUID = Path(...),
    payload: RecordRecentVisitRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visit = WorkbenchService.record_recent_visit(
        db,
        project_id=str(projectId),
        user_id=str(current_user.id),
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
    )
    db.commit()

    # 读取包含具体标题和路由的完整对象
    visits, _ = WorkbenchService.get_recent_visits(
        db, str(projectId), str(current_user.id), limit=50, offset=0
    )
    for item in visits:
        if item.id == visit.id:
            return item

    # 兜底
    return WorkbenchRecentVisit(
        id=visit.id,
        resource_type=visit.resource_type,
        resource_id=visit.resource_id,
        title=f"{visit.resource_type}:{visit.resource_id}",
        visited_at=visit.visited_at,
        target_route=f"/projects/{projectId}",
    )
