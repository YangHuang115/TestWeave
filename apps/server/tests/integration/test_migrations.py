import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from testweave.core.config import Settings, get_settings
from testweave.core.readiness import ReadinessFailure, SqlAlchemyReadinessProbe
from testweave.db.migrations import MIGRATIONS_PATH
from testweave.db.safety import assert_disposable_test_database_url
from testweave.db.session import create_database_engine

pytestmark = pytest.mark.integration

SERVER_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = SERVER_ROOT / "alembic.ini"


def test_empty_database_upgrades_to_head_and_becomes_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("TESTWEAVE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("需要通过 TESTWEAVE_TEST_DATABASE_URL 指定一次性 PostgreSQL 测试库")

    assert_disposable_test_database_url(
        database_url,
        environment=os.getenv("TESTWEAVE_ENVIRONMENT", ""),
    )
    monkeypatch.setenv("TESTWEAVE_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ALEMBIC_CONFIG_PATH))
    engine = create_database_engine(
        Settings.model_validate({"environment": "test", "database_url": database_url})
    )
    assert engine is not None

    try:
        command.downgrade(config, "base")
        probe = SqlAlchemyReadinessProbe(engine, MIGRATIONS_PATH)
        with pytest.raises(ReadinessFailure):
            probe.check()

        command.upgrade(config, "head")
        with engine.connect() as connection:
            current_revision = MigrationContext.configure(connection).get_current_revision()

        assert current_revision == "65482bc04697"
        assert probe.check() == {"database": "ok", "migrations": "ok"}

    finally:
        command.upgrade(config, "head")
        engine.dispose()
        get_settings.cache_clear()
