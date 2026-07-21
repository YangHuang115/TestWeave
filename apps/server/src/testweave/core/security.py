import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# 初始化 Argon2id PasswordHasher
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """使用 Argon2id 哈希密码"""
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """校验密码，返回 True / False，不抛出异常"""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def generate_session_token() -> str:
    """生成高熵的随机会话令牌 (Urlsafe Base64 编码，32字节)"""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """生成令牌哈希值 (SHA256) 用于入库存储"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
