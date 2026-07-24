from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T")


class WorkbenchSummary(BaseModel):
    remaining_requirements_count: int
    my_todos_count: int
    in_progress_tasks_count: int
    waiting_human_count: int
    generated_at: datetime


class WorkbenchTodoItem(BaseModel):
    id: str
    type: str
    title: str
    version_id: UUID | None = None
    version_name: str | None = None
    task_id: UUID | None = None
    task_title: str | None = None
    priority: str = Field("MEDIUM", pattern="^(HIGH|MEDIUM|LOW)$")
    due_at: datetime | None = None
    created_at: datetime
    urgency: str = Field("NORMAL", pattern="^(BLOCKED|OVERDUE|NORMAL)$")
    sub_item_count: int = 1
    target_type: str
    target_id: str
    target_route: str


class WorkbenchInProgressTask(BaseModel):
    id: UUID
    task_no: str
    title: str
    version_id: UUID | None = None
    version_name: str | None = None
    role: str = Field(..., pattern="^(OWNER|PARTICIPANT)$")
    status: str
    progress_percent: int | None = None
    is_blocked: bool = False
    updated_at: datetime


class WorkbenchAgentRunItem(BaseModel):
    id: UUID
    capability_id: UUID | None = None
    capability_name: str | None = None
    task_id: UUID | None = None
    task_title: str | None = None
    status: str
    current_stage: str | None = None
    started_at: datetime | None = None
    updated_at: datetime
    error_summary: str | None = None
    executable_actions: list[str] = Field(default_factory=list)


class WorkbenchRemainingRequirement(BaseModel):
    id: UUID
    requirement_no: str
    title: str
    priority: str
    status: str
    version_name: str | None = None
    updated_at: datetime
    target_route: str


class WorkbenchRecentVisit(BaseModel):
    id: UUID
    resource_type: str
    resource_id: str
    title: str
    visited_at: datetime
    target_route: str


class RecordRecentVisitRequest(BaseModel):
    resource_type: str = Field(..., pattern="^(requirement|test_task|version|test_case)$")
    resource_id: str = Field(..., min_length=1)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
