"""使用 Argon2id 安全处理用户密码。"""

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from argon2.low_level import Type

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# 用户不存在时仍执行一次真实密码验证，降低用户名枚举的时序差异。
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("lifepilot-dummy-password-never-used")


def hash_password(password: str) -> str:
    """校验密码长度并生成 Argon2id 哈希。"""
    if len(password) < 12:
        raise ValueError("密码至少需要12个字符。")

    if len(password) > 1024:
        raise ValueError("密码长度不能超过1024个字符。")

    return PASSWORD_HASHER.hash(password)


def verify_password(
    password_hash: str,
    password: str,
) -> bool:
    """验证密码，并隐藏哈希解析错误。"""
    try:
        return PASSWORD_HASHER.verify(
            password_hash,
            password,
        )
    except (
        VerifyMismatchError,
        VerificationError,
        InvalidHashError,
    ):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """判断密码哈希参数是否需要升级。"""
    try:
        return PASSWORD_HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
