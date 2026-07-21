from collections.abc import Callable, Generator

import pytest

from testweave.core.config import get_settings
from testweave.core.errors import AppError
from testweave.shared.crypto import CryptoService


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None, None, None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def configured_secret(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("TESTWEAVE_SECRET_KEY", "Y6zvH8qP2nB5sT9wK4mR7xC1dF3jL0aQ")
    yield


def test_crypto_encrypt_decrypt_success(configured_secret: None) -> None:
    plain = "my-super-secret-ssh-key-or-token"
    cipher = CryptoService.encrypt(plain)
    assert cipher is not None
    assert cipher != plain

    decrypted = CryptoService.decrypt(cipher)
    assert decrypted == plain


def test_crypto_decrypt_failure(configured_secret: None) -> None:
    # 错误的密文解密应该抛出 AppError(DECRYPTION_FAILED)
    bad_cipher = "not-a-valid-fernet-token-cipher"
    with pytest.raises(AppError) as exc_info:
        CryptoService.decrypt(bad_cipher)
    assert exc_info.value.code == "DECRYPTION_FAILED"


@pytest.mark.parametrize("environment", ["development", "test"])
@pytest.mark.parametrize(
    ("operation", "value"),
    [
        (CryptoService.encrypt, "credential"),
        (CryptoService.decrypt, "encrypted-credential"),
    ],
)
def test_crypto_without_secret_fails_explicitly_when_used(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    operation: Callable[[str | None], str | None],
    value: str,
) -> None:
    monkeypatch.setenv("TESTWEAVE_ENVIRONMENT", environment)
    monkeypatch.delenv("TESTWEAVE_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(AppError) as exc_info:
        operation(value)

    assert exc_info.value.code == "ENCRYPTION_SECRET_NOT_CONFIGURED"


def test_crypto_with_blank_secret_fails_explicitly_when_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_ENVIRONMENT", "development")
    monkeypatch.setenv("TESTWEAVE_SECRET_KEY", "   ")

    with pytest.raises(AppError) as exc_info:
        CryptoService.encrypt("credential")

    assert exc_info.value.code == "ENCRYPTION_SECRET_NOT_CONFIGURED"
