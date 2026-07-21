import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from testweave.core.config import get_settings
from testweave.core.errors import AppError


def _get_fernet() -> Fernet:
    secret_key = get_settings().secret_key
    raw_secret = secret_key.get_secret_value() if secret_key is not None else ""
    if not raw_secret.strip():
        raise AppError(
            code="ENCRYPTION_SECRET_NOT_CONFIGURED",
            message="服务端未配置凭证加密主密钥，无法处理凭证",
            status_code=500,
        )

    raw_key = raw_secret.encode("utf-8")
    fernet_key = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
    return Fernet(fernet_key)


class CryptoService:
    @staticmethod
    def encrypt(plain_text: str | None) -> str | None:
        if plain_text is None:
            return None
        return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")

    @staticmethod
    def decrypt(cipher_text: str | None) -> str | None:
        if cipher_text is None:
            return None
        fernet = _get_fernet()
        try:
            return fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            raise AppError(
                code="DECRYPTION_FAILED",
                message="凭证解密失败，可能密钥已变更或数据损坏",
                status_code=500,
            ) from None
