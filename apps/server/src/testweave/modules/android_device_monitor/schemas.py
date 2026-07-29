from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AndroidDeviceItem(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    device_ref: str = Field(serialization_alias="deviceRef")
    display_name: str = Field(serialization_alias="displayName")
    state: str
    model: str | None = None
    info_available: bool = Field(serialization_alias="infoAvailable")
    info_error: str | None = Field(default=None, serialization_alias="infoError")


class AndroidDeviceListResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    items: list[AndroidDeviceItem]
    total: int


class AndroidScreenshot:
    def __init__(self, content: bytes, captured_at: datetime) -> None:
        self.content = content
        self.captured_at = captured_at
        self.media_type = "image/png"


@dataclass(frozen=True, slots=True)
class AndroidStreamFrame:
    content: bytes
    captured_at: datetime
    sequence: int
    effective_fps: float | None


@dataclass(frozen=True, slots=True)
class AndroidStreamError:
    code: str
    message: str
    retryable: bool
    terminal: bool


AndroidStreamMessage = AndroidStreamFrame | AndroidStreamError
