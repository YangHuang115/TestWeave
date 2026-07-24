from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkbenchStatus = Literal["READY", "NEEDS_SELECTION", "BLOCKED", "NOT_FOUND"]
WorkbenchStage = Literal[
    "requirement-analysis",
    "test-points",
    "test-cases",
    "case-review",
]
WorkbenchArtifactType = Literal[
    "requirement_analysis@1.0",
    "test_point_set@1.0",
    "test_case_set@1.0",
    "test_case_review_report@1.0",
]


class ResolveWorkbenchRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class WorkbenchIntent(BaseModel):
    message: str
    stage: WorkbenchStage
    artifactType: WorkbenchArtifactType


class WorkbenchProject(BaseModel):
    id: str
    key: str
    name: str


class WorkbenchVersion(BaseModel):
    id: str
    key: str
    name: str
    status: str


class WorkbenchTask(BaseModel):
    id: str
    key: str
    title: str
    status: str
    taskType: str
    priority: str
    updatedAt: str


class WorkbenchRequirement(BaseModel):
    id: str
    key: str
    title: str
    status: str
    priority: str


class WorkbenchAIDesign(BaseModel):
    recordId: str
    recordNo: int
    title: str
    lastOpenedStage: str
    runId: str
    runStatus: str | None
    updatedAt: str


class WorkbenchSnapshot(BaseModel):
    version: WorkbenchVersion | None = None
    task: WorkbenchTask | None = None
    requirement: WorkbenchRequirement | None = None
    requirements: list[WorkbenchRequirement] = Field(default_factory=list)
    aiDesign: WorkbenchAIDesign | None = None


class WorkbenchEntryPoint(BaseModel):
    action: Literal["LOAD_TASK_CONTEXT"]
    method: Literal["GET"]
    path: str
    taskId: str
    taskKey: str
    stage: WorkbenchStage
    artifactType: WorkbenchArtifactType


class WorkbenchCandidate(BaseModel):
    type: Literal["TASK", "REQUIREMENT"]
    id: str
    key: str
    title: str
    status: str


class WorkbenchBlocker(BaseModel):
    code: str
    message: str


class ResolveWorkbenchResponse(BaseModel):
    status: WorkbenchStatus
    readOnly: Literal[True]
    intent: WorkbenchIntent
    project: WorkbenchProject
    workbench: WorkbenchSnapshot | None
    entryPoint: WorkbenchEntryPoint | None
    candidates: list[WorkbenchCandidate]
    blockers: list[WorkbenchBlocker]
