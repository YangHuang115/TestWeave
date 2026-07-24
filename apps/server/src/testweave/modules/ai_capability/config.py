from functools import lru_cache
from ipaddress import ip_address

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalAgentFeatureConfig(BaseSettings):
    """External Agent 外部智能体配置，支持嵌套环境变量 TESTWEAVE_EXTERNAL_AGENT__*。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TESTWEAVE_EXTERNAL_AGENT__",
        extra="ignore",
    )

    enabled: bool = False
    bind_host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    token_prefix: str = "tw_ext_"
    default_token_ttl_days: int = Field(default=30, ge=1, le=365)

    @field_validator("bind_host")
    @classmethod
    def validate_bind_host_loopback(cls, value: str) -> str:
        host = value.strip().lower()
        if host == "localhost":
            return value

        try:
            ip = ip_address(host)
        except ValueError as exc:
            raise ValueError(f"不合法的 bind_host IP 地址: {value}") from exc

        if not ip.is_loopback:
            raise ValueError(
                "External Agent bind_host 只允许配置 loopback 回环地址 (例如 127.0.0.1 或 ::1)"
            )

        return value


@lru_cache
def get_external_agent_config() -> ExternalAgentFeatureConfig:
    return ExternalAgentFeatureConfig()
