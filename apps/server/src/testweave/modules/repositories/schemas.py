from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class RepositoryVerifyRequest(BaseModel):
    remote_url: str
    auth_type: str = "NONE"
    credential_content: str | None = None
    main_branch: str = "main"


class RepositoryCreateOrUpdateRequest(BaseModel):
    name: str
    remote_url: str
    auth_type: str = "NONE"
    credential_content: str | None = None
    main_branch: str = "main"
    enabled: bool = True
    row_version: int | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    repository_type: str
    provider_type: str
    name: str
    remote_url: str
    auth_type: str
    main_branch: str
    enabled: bool
    sync_status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_synced_head_sha: str | None
    last_error_code: str | None
    last_error_message: str | None
    row_version: int
    has_credential: bool = False
