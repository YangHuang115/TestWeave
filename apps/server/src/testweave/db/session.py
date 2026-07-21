from sqlalchemy import Engine, create_engine

from testweave.core.config import Settings


def application_connect_args(settings: Settings) -> dict[str, int | str]:
    return {
        "connect_timeout": settings.database_connect_timeout_seconds,
        "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
    }


def migration_connect_args(settings: Settings) -> dict[str, int | str]:
    return {
        "connect_timeout": settings.database_connect_timeout_seconds,
        "options": (
            f"-c statement_timeout={settings.migration_statement_timeout_ms} "
            f"-c lock_timeout={settings.migration_lock_timeout_ms}"
        ),
    }


def create_database_engine(settings: Settings) -> Engine | None:
    if settings.database_url is None:
        return None
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=settings.database_pool_timeout_seconds,
        connect_args=application_connect_args(settings),
    )
