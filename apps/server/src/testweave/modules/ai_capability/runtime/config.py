from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIRuntimeSettings(BaseSettings):
    """M09 AI 能力中心 P2 运行配置"""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = Field(default=False, alias="TESTWEAVE_AI_RUNTIME__ENABLED")
    poll_interval_ms: int = Field(default=500, alias="TESTWEAVE_AI_RUNTIME__POLL_INTERVAL_MS")
    step_timeout_seconds: int = Field(
        default=120, alias="TESTWEAVE_AI_RUNTIME__STEP_TIMEOUT_SECONDS"
    )
    claim_ttl_seconds: int = Field(default=180, alias="TESTWEAVE_AI_RUNTIME__CLAIM_TTL_SECONDS")
    max_attempts: int = Field(default=3, alias="TESTWEAVE_AI_RUNTIME__MAX_ATTEMPTS")
    retry_base_seconds: int = Field(default=2, alias="TESTWEAVE_AI_RUNTIME__RETRY_BASE_SECONDS")
    run_max_parallel_steps: int = Field(
        default=1, alias="TESTWEAVE_AI_RUNTIME__RUN_MAX_PARALLEL_STEPS"
    )
    project_max_active_runs: int = Field(
        default=4, alias="TESTWEAVE_AI_RUNTIME__PROJECT_MAX_ACTIVE_RUNS"
    )
    max_input_bytes: int = Field(
        default=1048576, alias="TESTWEAVE_AI_RUNTIME__MAX_INPUT_BYTES"
    )  # 1MB
    max_output_bytes: int = Field(
        default=2097152, alias="TESTWEAVE_AI_RUNTIME__MAX_OUTPUT_BYTES"
    )  # 2MB

    @model_validator(mode="after")
    def validate_ttl_and_timeout(self) -> "AIRuntimeSettings":
        if self.claim_ttl_seconds <= self.step_timeout_seconds:
            raise ValueError(
                "TESTWEAVE_AI_RUNTIME__CLAIM_TTL_SECONDS 必须大于 STEP_TIMEOUT_SECONDS"
            )
        return self


class AIProviderSettings(BaseSettings):
    """M09 AI 模型 Provider 全局运维配置"""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    provider_type: Literal["openai_compatible", "fake"] = Field(
        default="openai_compatible", alias="TESTWEAVE_AI_PROVIDER__TYPE"
    )
    base_url: str = Field(default="", alias="TESTWEAVE_AI_PROVIDER__BASE_URL")
    api_key: SecretStr = Field(default=SecretStr(""), alias="TESTWEAVE_AI_PROVIDER__API_KEY")
    quality_model: str = Field(default="", alias="TESTWEAVE_AI_PROVIDER__QUALITY_MODEL")
    timeout_seconds: int = Field(default=120, alias="TESTWEAVE_AI_PROVIDER__TIMEOUT_SECONDS")

    def is_configured(self) -> bool:
        """检查 Provider 配置是否完整"""
        if self.provider_type == "fake":
            return True
        key_val = self.api_key.get_secret_value() if self.api_key else ""
        return bool(self.base_url.strip() and key_val.strip() and self.quality_model.strip())

    def validate_for_production(self, is_production: bool = False) -> None:
        """运行开启时强强校验"""
        if not self.is_configured():
            raise ValueError("AI Provider 未完整配置 BASE_URL, API_KEY 或 QUALITY_MODEL")
        if is_production and self.provider_type == "fake":
            raise ValueError("生产环境禁止使用 Fake AI Provider")
        if is_production and self.provider_type == "openai_compatible":
            url_lower = self.base_url.lower()
            if not url_lower.startswith("https://"):
                raise ValueError("生产环境下 AI Provider BASE_URL 必须使用 HTTPS 协议")
