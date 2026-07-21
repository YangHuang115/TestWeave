from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


class ReadinessFailure(RuntimeError):
    """Internal readiness failure whose message must never enter an HTTP response."""


class ReadinessProbe(Protocol):
    def check(self) -> Mapping[str, str]: ...


class NotConfiguredReadinessProbe:
    def check(self) -> Mapping[str, str]:
        raise ReadinessFailure("database is not configured")


class SqlAlchemyReadinessProbe:
    def __init__(self, engine: Engine, migrations_path: Path) -> None:
        self._engine = engine
        self._migrations_path = migrations_path

    def check(self) -> Mapping[str, str]:
        try:
            expected_revision = ScriptDirectory(str(self._migrations_path)).get_current_head()

            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                current_revision = MigrationContext.configure(connection).get_current_revision()
        except (CommandError, OSError, RuntimeError, SQLAlchemyError) as exc:
            raise ReadinessFailure("database readiness check failed") from exc

        if expected_revision is None or current_revision != expected_revision:
            raise ReadinessFailure("database migration is not current")

        return {"database": "ok", "migrations": "ok"}
