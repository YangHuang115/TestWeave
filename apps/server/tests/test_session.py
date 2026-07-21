from unittest.mock import Mock

import pytest
from sqlalchemy import Engine

import testweave.db.session as session_module
from testweave.core.config import Settings


def test_database_engine_uses_bounded_connection_query_and_pool_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    expected_engine = Mock(spec=Engine)

    def fake_create_engine(database_url: str, **options: object) -> Engine:
        captured["database_url"] = database_url
        captured.update(options)
        return expected_engine

    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://testweave:example@localhost/testweave",
            "database_connect_timeout_seconds": 7,
            "database_pool_timeout_seconds": 8,
            "database_statement_timeout_ms": 9_000,
        }
    )

    engine = session_module.create_database_engine(settings)

    assert engine is expected_engine
    assert captured["pool_timeout"] == 8
    assert captured["connect_args"] == {
        "connect_timeout": 7,
        "options": "-c statement_timeout=9000",
    }


def test_migrations_use_separate_statement_and_lock_timeouts() -> None:
    settings = Settings.model_validate(
        {
            "database_statement_timeout_ms": 5_000,
            "migration_statement_timeout_ms": 900_000,
            "migration_lock_timeout_ms": 12_000,
        }
    )

    assert session_module.migration_connect_args(settings) == {
        "connect_timeout": 5,
        "options": "-c statement_timeout=900000 -c lock_timeout=12000",
    }
