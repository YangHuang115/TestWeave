from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from testweave.modules.ai_capability.enums import (
    AIRunEventType,
    AIRunMode,
    CapabilityRunStatus,
    HumanAction,
    StepExecutionStatus,
)


class AIRunCreateRequest(BaseModel):
    """创建 Run 请求"""

    runMode: AIRunMode = Field(default=AIRunMode.NORMAL)
    capabilityVersionId: UUID | None = Field(default=None)
    input: dict[str, Any] = Field(default_factory=dict)


class AIRunResponse(BaseModel):
    """Run 简要响应 (202 Created / Query)"""

    id: UUID
    capabilityId: UUID
    capabilityVersionId: UUID
    projectId: UUID
    initiatorId: UUID | None
    traceId: str
    runMode: AIRunMode
    status: CapabilityRunStatus
    cancelRequested: bool = False
    allowedActions: list[str] = Field(default_factory=list)
    errorCode: str | None = None
    errorSummary: str | None = None
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    createdAt: datetime


class AIStepExecutionResponse(BaseModel):
    """Step 步骤详情响应"""

    id: UUID
    runId: UUID
    nodeId: str
    nodeType: str
    nodeName: str | None
    attempt: int
    status: StepExecutionStatus
    inputSummary: dict[str, Any] | None = None
    outputSnapshot: dict[str, Any] | None = None
    validatorResults: dict[str, Any] | None = None
    retryable: bool = True
    errorCode: str | None = None
    errorSummary: str | None = None
    providerName: str | None = None
    modelName: str | None = None
    durationMs: int | None = None
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    createdAt: datetime


class AIRunDetailResponse(AIRunResponse):
    """Run 完整详情响应 (包含步骤时间线与汇总)"""

    inputSnapshot: dict[str, Any] = Field(default_factory=dict)
    executionSnapshotHash: str | None = None
    finalOutputSnapshot: dict[str, Any] | None = None
    steps: list[AIStepExecutionResponse] = Field(default_factory=list)


class AIRunEventItem(BaseModel):
    """Run 单条事件轮询响应"""

    eventId: UUID
    runId: UUID
    stepExecutionId: UUID | None = None
    sequence: int
    eventType: AIRunEventType
    traceId: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurredAt: datetime


class AIRunEventsPollResponse(BaseModel):
    """游标轮询事件流响应"""

    items: list[AIRunEventItem]
    nextSequence: int
    hasMore: bool
    runStatus: CapabilityRunStatus
    cancelRequested: bool = False


class HumanDecisionSubmitRequest(BaseModel):
    """Human Gate 决策提交请求"""

    action: HumanAction
    decision: dict[str, Any] = Field(default_factory=dict)
