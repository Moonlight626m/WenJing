"""对外错误契约：ErrorEnvelope。

- 对外错误包含 error ID、稳定 code、安全 message、可重试性与安全 details；
  内部 cause 与 stack 只留在服务端日志（spec 决策）。
- code 格式：`<DOMAIN>_<NAME>`，DOMAIN 取 ErrorDomain 值。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field, model_validator

from app.contracts.base import VersionedContract
from app.contracts.enums import ErrorDomain


class ErrorEnvelope(VersionedContract):
    """对外错误 envelope；跨 REST 与 WS 统一使用。"""

    error_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    code: str = Field(min_length=1, description="稳定错误码，如 CONTENT_UNSUPPORTED_GENRE")
    domain: ErrorDomain
    message: str = Field(min_length=1, description="对用户安全、可展示的消息")
    retryable: bool = False
    details: dict[str, Any] | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_code_prefix(self) -> ErrorEnvelope:
        prefix, _, _rest = self.code.partition("_")
        if not _rest or prefix.lower() != self.domain.value:
            raise ValueError(
                f"code must be '<{self.domain.value}>_<NAME>', got {self.code!r}"
            )
        return self


# ===== 稳定对外错误码登记表（issue #2 验收标准 5）=====
# 新增错误在此登记；与 errx 整数码的映射在 #3（诊断基建）接线。

STABLE_CODES: dict[str, tuple[ErrorDomain, bool]] = {
    # input
    "INPUT_EMPTY_MATERIAL": (ErrorDomain.INPUT, False),
    "INPUT_UNSUPPORTED_EXTENSION": (ErrorDomain.INPUT, False),
    "INPUT_INVALID_ENCODING": (ErrorDomain.INPUT, False),
    "INPUT_TOO_LARGE": (ErrorDomain.INPUT, False),
    "INPUT_INVALID": (ErrorDomain.INPUT, False),
    # content
    "CONTENT_UNSUPPORTED_GENRE": (ErrorDomain.CONTENT, False),
    "CONTENT_GENERATION_FAILED": (ErrorDomain.CONTENT, True),
    "CONTENT_VALIDATION_FAILED": (ErrorDomain.CONTENT, True),
    "CONTENT_INSUFFICIENT_SOURCE": (ErrorDomain.CONTENT, False),
    # content / 剧本库（#19）
    "CONTENT_SCRIPT_NOT_FOUND": (ErrorDomain.CONTENT, False),
    "CONTENT_SCRIPT_NOT_EDITABLE": (ErrorDomain.CONTENT, False),
    "CONTENT_MATERIAL_NOT_FOUND": (ErrorDomain.CONTENT, False),
    "CONTENT_SCRIPT_NOT_READY": (ErrorDomain.CONTENT, False),
    # search
    "SEARCH_UNAVAILABLE": (ErrorDomain.SEARCH, True),
    "SEARCH_BLOCKED_TARGET": (ErrorDomain.SEARCH, False),
    "SEARCH_TIMEOUT": (ErrorDomain.SEARCH, True),
    # llm
    "LLM_TIMEOUT": (ErrorDomain.LLM, True),
    "LLM_INVALID_OUTPUT": (ErrorDomain.LLM, True),
    "LLM_CALL_FAILED": (ErrorDomain.LLM, True),
    # game
    "GAME_INVALID_TRANSITION": (ErrorDomain.GAME, False),
    "GAME_COMMAND_NOT_ALLOWED": (ErrorDomain.GAME, False),
    "GAME_ROLLBACK_TARGET_MISSING": (ErrorDomain.GAME, False),
    "GAME_ROLLBACK_OVERFLOW": (ErrorDomain.GAME, False),
    # session
    "SESSION_NOT_FOUND": (ErrorDomain.SESSION, False),
    "SESSION_ENDED": (ErrorDomain.SESSION, False),
    "SESSION_CONFLICT": (ErrorDomain.SESSION, True),
    # auth
    "AUTH_UNAUTHENTICATED": (ErrorDomain.AUTH, False),
    "AUTH_INVALID_CREDENTIALS": (ErrorDomain.AUTH, False),
    "AUTH_FORBIDDEN": (ErrorDomain.AUTH, False),
    "AUTH_CSRF_FAILED": (ErrorDomain.AUTH, False),
    "AUTH_IDENTIFIER_TAKEN": (ErrorDomain.AUTH, False),
    # persistence
    "PERSISTENCE_WRITE_FAILED": (ErrorDomain.PERSISTENCE, True),
    "PERSISTENCE_INCOMPATIBLE_SCHEMA": (ErrorDomain.PERSISTENCE, False),
    "PERSISTENCE_CORRUPT_SNAPSHOT": (ErrorDomain.PERSISTENCE, True),
    # protocol
    "PROTOCOL_MALFORMED_MESSAGE": (ErrorDomain.PROTOCOL, False),
    "PROTOCOL_UNKNOWN_COMMAND": (ErrorDomain.PROTOCOL, False),
    "PROTOCOL_DUPLICATE_COMMAND": (ErrorDomain.PROTOCOL, False),
    # internal
    "INTERNAL_ERROR": (ErrorDomain.INTERNAL, True),
}


def stable_code(code: str) -> tuple[ErrorDomain, bool]:
    """查询稳定错误码的 (domain, retryable)；未登记码按 INTERNAL 处理。"""
    return STABLE_CODES.get(code, (ErrorDomain.INTERNAL, True))
