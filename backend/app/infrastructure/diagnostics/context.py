"""关联 ID 上下文（contextvars）：跨 REST/WS/生成/LLM/DB 传播。

标准字段：request / session / command / generation / llm_call / correlation id。
logging.Filter 把这些值注入每条日志记录，使任意失败可经关联 ID 串联全链路。
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("wj_request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("wj_session_id", default=None)
_command_id: ContextVar[str | None] = ContextVar("wj_command_id", default=None)
_generation_id: ContextVar[str | None] = ContextVar("wj_generation_id", default=None)
_llm_call_id: ContextVar[str | None] = ContextVar("wj_llm_call_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("wj_correlation_id", default=None)


def _fresh() -> str:
    return str(uuid.uuid4())


def bind_request(value: str | None = None) -> str:
    v = value or _fresh()
    _request_id.set(v)
    return v


def bind_session(value: str) -> str:
    _session_id.set(value)
    return value


def bind_command(value: str) -> str:
    _command_id.set(value)
    return value


def bind_generation(value: str | None = None) -> str:
    v = value or _fresh()
    _generation_id.set(v)
    return v


def bind_llm_call() -> str:
    v = _fresh()
    _llm_call_id.set(v)
    return v


def bind_correlation(value: str | None = None) -> str:
    """开命令时绑定 correlation；沿途 causation 链共用。"""
    v = value or _fresh()
    _correlation_id.set(v)
    return v


def current_ids() -> dict[str, str | None]:
    """当前上下文的全部标准关联字段（打日志/建 envelope 时携带）。"""
    return {
        "request_id": _request_id.get(),
        "session_id": _session_id.get(),
        "command_id": _command_id.get(),
        "generation_id": _generation_id.get(),
        "llm_call_id": _llm_call_id.get(),
        "correlation_id": _correlation_id.get(),
    }


def reset_ids() -> None:
    for var in (_request_id, _session_id, _command_id, _generation_id,
                _llm_call_id, _correlation_id):
        var.set(None)


class CorrelationFilter(logging.Filter):
    """把 contextvars 关联字段注入 LogRecord；duration_ms/error_code/retry_count 直通。"""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, val in current_ids().items():
            setattr(record, key, val)
        return True
