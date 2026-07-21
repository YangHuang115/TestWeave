import pytest
from pydantic import ValidationError

from testweave.core.config import Settings

LEGACY_DEFAULT_SECRET = "testweave-default-super-secret-key-32bytes!"
LOCAL_EXAMPLE_SECRET = "local-development-only-secret-key-change-me"
STRONG_PRODUCTION_SECRET = "Y6zvH8qP2nB5sT9wK4mR7xC1dF3jL0aQ"


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


def test_development_has_no_static_secret_key_default() -> None:
    settings = Settings(environment="development", _env_file=None)

    assert settings.secret_key is None


def test_production_requires_secret_key() -> None:
    with pytest.raises(ValidationError, match="TESTWEAVE_SECRET_KEY"):
        Settings(environment="production", _env_file=None)


@pytest.mark.parametrize(
    "secret_key",
    [
        "too-short",
        "a" * 32,
        " " * 32,
        LEGACY_DEFAULT_SECRET,
        LOCAL_EXAMPLE_SECRET,
    ],
)
def test_production_rejects_weak_or_known_secret_keys(secret_key: str) -> None:
    with pytest.raises(ValidationError, match="TESTWEAVE_SECRET_KEY"):
        Settings(environment="production", secret_key=secret_key, _env_file=None)


def test_production_accepts_strong_secret_key() -> None:
    settings = Settings(
        environment="production",
        secret_key=STRONG_PRODUCTION_SECRET,
        _env_file=None,
    )

    assert settings.secret_key is not None
    assert settings.secret_key.get_secret_value() == STRONG_PRODUCTION_SECRET
