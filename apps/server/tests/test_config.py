import pytest
from pydantic import ValidationError

from testweave.core.config import Settings


def test_database_url_requires_the_installed_psycopg_driver() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings.model_validate(
            {"database_url": "postgresql://testweave:example@localhost/testweave"}
        )


def test_database_url_accepts_explicit_psycopg_driver() -> None:
    settings = Settings.model_validate(
        {"database_url": "postgresql+psycopg://testweave:example@localhost/testweave"}
    )

    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")


def test_invalid_database_url_does_not_leak_credentials_in_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_url = "postgresql://u:s3cr3t@h/d"
    monkeypatch.setenv("TESTWEAVE_DATABASE_URL", invalid_url)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error_text = str(exc_info.value)
    assert "s3cr3t" not in error_text
    assert invalid_url not in error_text
