import pytest
from testweave.core.errors import AppError
from testweave.shared.crypto import CryptoService


def test_crypto_encrypt_decrypt_success() -> None:
    plain = "my-super-secret-ssh-key-or-token"
    cipher = CryptoService.encrypt(plain)
    assert cipher is not None
    assert cipher != plain

    decrypted = CryptoService.decrypt(cipher)
    assert decrypted == plain


def test_crypto_decrypt_failure() -> None:
    # 错误的密文解密应该抛出 AppError(DECRYPTION_FAILED)
    bad_cipher = "not-a-valid-fernet-token-cipher"
    with pytest.raises(AppError) as exc_info:
        CryptoService.decrypt(bad_cipher)
    assert exc_info.value.code == "DECRYPTION_FAILED"
