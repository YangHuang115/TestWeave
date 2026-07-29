from pydantic import BaseModel, Field


class AndroidMcpSettings(BaseModel):
    """Configuration for the separately installed local Android MCP runtime.

    The runtime is deliberately disabled until an operator supplies absolute
    paths. This keeps a missing local installation from affecting the main API.
    """

    enabled: bool = False
    node_path: str | None = None
    entrypoint: str | None = None
    cwd: str | None = None
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_screenshot_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_info_concurrency: int = Field(default=4, ge=1, le=16)
    stream_enabled: bool = False
    stream_interval_ms: int = Field(default=500, ge=100, le=10_000)
    stream_idle_grace_seconds: float = Field(default=3, ge=0, le=60)
    stream_device_recheck_seconds: float = Field(default=5, gt=0, le=300)
    stream_max_backoff_seconds: float = Field(default=5, gt=0, le=60)
