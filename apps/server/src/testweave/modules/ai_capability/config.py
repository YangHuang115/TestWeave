from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalAgentFeatureConfig(BaseSettings):
    """External Agent 外部智能体配置，支持嵌套环境变量 TESTWEAVE_EXTERNAL_AGENT__*。

    Gateway 路由挂载在主 FastAPI 应用同进程同端口，不单独 bind socket，
    因此不存在 bind_host / port 配置。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TESTWEAVE_EXTERNAL_AGENT__",
        extra="ignore",
    )

    enabled: bool = False
    token_prefix: str = "tw_ext_"
    default_token_ttl_days: int = Field(default=30, ge=1, le=365)


@lru_cache
def get_external_agent_config() -> ExternalAgentFeatureConfig:
    return ExternalAgentFeatureConfig()
