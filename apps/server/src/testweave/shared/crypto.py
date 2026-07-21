import base64
import hashlib
from cryptography.fernet import Fernet

from testweave.core.config import get_settings
from testweave.core.errors import AppError

settings = get_settings()
raw_key = settings.secret_key.get_secret_value().encode("utf-8")
fernet_key = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
fernet = Fernet(fernet_key)


class CryptoService:
    @staticmethod
    def encrypt(plain_text: str | None) -> str | None:
        if plain_text is None:
            return None
        return fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    @staticmethod
    def decrypt(cipher_text: str | None) -> str | None:
        if cipher_text is None:
            return None
        try:
            return fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
        except Exception:
            raise AppError(
                code="DECRYPTION_FAILED",
                message="凭证解密失败，可能密钥已变更或数据损坏",
                status_code=500,
            )
