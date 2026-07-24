from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunEventEnvelope(BaseModel):
    """不可变 Run Event 事件包契约。"""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    event_id: UUID
    event_type: str = Field(min_length=1)
    run_id: UUID
    step_execution_id: UUID | None = None
    sequence: int = Field(gt=0, description="递增正整数序号")
    occurred_at: datetime
    trace_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def validate_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("occurred_at 时间必须为带时区的时间戳 (timezone-aware datetime)")
        return value
