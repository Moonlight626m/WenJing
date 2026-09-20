"""密码哈希（issue #17 / ADR-0002 §2）：argon2-cffi。

只暴露哈希与校验；原始密码绝不落库、绝不入日志。
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """生成 argon2 哈希（自带随机 salt）。"""
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """校验密码；哈希损坏/不匹配一律返回 False，不抛异常。"""
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """哈希参数是否已过时（供未来参数升级时透明重哈希）。"""
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


__all__ = ["hash_password", "verify_password", "needs_rehash"]
