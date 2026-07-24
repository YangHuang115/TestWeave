from alembic.script import ScriptDirectory

from testweave.db.migrations import MIGRATIONS_PATH


def test_packaged_migration_directory_has_the_expected_single_head() -> None:
    assert MIGRATIONS_PATH.is_dir()
    assert ScriptDirectory(str(MIGRATIONS_PATH)).get_current_head() == "a16f10016abc"
