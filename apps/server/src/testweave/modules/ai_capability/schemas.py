import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileMapping(BaseModel):
    """能力包文件条目。"""

    path: str = Field(..., description="相对路径，如 workflow/workflow.yaml")
    content: str = Field(..., description="文件 UTF-8 文本内容")


class CapabilityPackagePayload(BaseModel):
    """能力包传输体。"""

    files: list[FileMapping] = Field(..., description="文件映射体数组")


class AgentRegisterRequest(BaseModel):
    """外部 Agent 注册请求体。"""

    connectionName: str = Field(..., description="活动连接名称")
    clientName: str = Field(..., description="客户端名称")
    clientVersion: str = Field(..., description="客户端版本")
    platform: str = Field(..., description="系统平台")
    protocolVersion: str = Field(..., description="协议版本")


class AgentResponse(BaseModel):
    """外部 Agent 响应体。"""

    id: uuid.UUID
    project_id: uuid.UUID
    connection_name: str
    client_name: str
    client_version: str
    platform: str
    protocol_version: str
    last_active_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenCreateRequest(BaseModel):
    """创建访问 Token 请求体。"""

    description: str | None = Field(None, description="Token 的用途描述")
    is_official_scope: bool = Field(False, description="是否申请官方系统管理员 scope")


class TokenCreateResponse(BaseModel):
    """访问 Token 创建成功的响应体，仅在此处暴露一次明文密码。"""

    id: uuid.UUID
    project_id: uuid.UUID
    token_prefix: str
    token_plaintext: str
    namespace_scope: str
    description: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    """只读 Token 响应体。"""

    id: uuid.UUID
    project_id: uuid.UUID
    token_prefix: str
    namespace_scope: str
    description: str | None
    is_revoked: bool
    created_at: datetime
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class CompatibilityReportResponse(BaseModel):
    """能力包校验报告。"""

    valid: bool
    syncable: bool
    packageFingerprint: str | None
    compatibilityLevel: str | None
    issues: list[str]
