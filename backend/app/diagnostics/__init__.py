"""统一诊断基础设施（issue #3）：关联 ID 上下文、结构化日志、错误信封、指标。"""

from app.diagnostics.context import (
    bind_command,
    bind_correlation,
    bind_generation,
    bind_request,
    bind_session,
    current_ids,
)
from app.diagnostics.errors import envelope_for

__all__ = [
    "bind_command",
    "bind_correlation",
    "bind_generation",
    "bind_request",
    "bind_session",
    "current_ids",
    "envelope_for",
]
