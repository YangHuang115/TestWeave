from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    requirement_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by: UUID | None
    uploaded_at: datetime
