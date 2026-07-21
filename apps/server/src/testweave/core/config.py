from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from TESTWEAVE_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TESTWEAVE_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "TestWeave API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: SecretStr | None = None
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_pool_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=5_000, ge=1_000, le=60_000)
    migration_statement_timeout_ms: int = Field(
        default=900_000,
        ge=60_000,
        le=3_600_000,
    )
    migration_lock_timeout_ms: int = Field(default=10_000, ge=1_000, le=60_000)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    storage_local_dir: str = Field(default="data/storage")
    secret_key: SecretStr = Field(default="testweave-default-super-secret-key-32bytes!")

    @field_validator("database_url")
    @classmethod
    def require_postgresql_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        url = value.get_secret_value()
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("TESTWEAVE_DATABASE_URL 必须使用 postgresql+psycopg:// 连接串")
        return value

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("启用凭证时不允许使用通配 CORS 来源")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
