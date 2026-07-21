import pytest

from testweave.db.safety import UnsafeDatabaseTarget, assert_disposable_test_database_url


@pytest.mark.parametrize(
    ("environment", "database_url"),
    [
        (
            "development",
            "postgresql+psycopg://testweave:example@127.0.0.1:5432/testweave_test",
        ),
        (
            "test",
            "postgresql+psycopg://testweave:example@db.internal:5432/testweave_test",
        ),
        (
            "test",
            "postgresql+psycopg://testweave:example@127.0.0.1:5432/testweave",
        ),
        (
            "test",
            "postgresql://testweave:example@127.0.0.1:5432/testweave_test",
        ),
        (
            "test",
            "postgresql+psycopg://testweave:example@127.0.0.1:5432/"
            "testweave_test?host=db.internal&dbname=production",
        ),
    ],
)
def test_destructive_migration_target_rejects_unsafe_database(
    environment: str,
    database_url: str,
) -> None:
    with pytest.raises(UnsafeDatabaseTarget):
        assert_disposable_test_database_url(database_url, environment=environment)


def test_destructive_migration_target_accepts_local_test_database() -> None:
    assert_disposable_test_database_url(
        "postgresql+psycopg://testweave:example@127.0.0.1:55432/testweave_test",
        environment="test",
    )
