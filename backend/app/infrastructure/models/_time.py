"""模型层时间默认值（issue #17）。

统一 UTC now 取值，避免每个模型各写一份 `_utcnow` / `lambda: datetime.now(UTC)`。
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """返回当前 UTC 时间（带时区）。"""
    return datetime.now(UTC)


__all__ = ["utcnow"]
