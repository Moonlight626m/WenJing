"""统一错误契约：域、稳定错误码与对外错误 envelope。

核心 MVP 的对外错误统一为 `ErrorEnvelope`（error_id/code/message/retryable/details）；
cause 与 stack 只进服务端日志，不返回客户端（设计文档 §12.2）。

- `ErrorDomains`：九个错误域
  （INPUT/CONTENT/SEARCH/LLM/GAME/SESSION/PERSISTENCE/PROTOCOL/INTERNAL）。
- `ErrorCode`：稳定字符串错误码，每个码以对应域为前缀；新增码在此登记，
  属非破坏性扩展。
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ERRORS_SCHEMA_VERSION = 1


class ErrorDomains(StrEnum):
    INPUT = "INPUT"
    CONTENT = "CONTENT"
    SEARCH = "SEARCH"
    LLM = "LLM"
    GAME = "GAME"
    SESSION = "SESSION"
    PERSISTENCE = "PERSISTENCE"
    PROTOCOL = "PROTOCOL"
    INTERNAL = "INTERNAL"


class ErrorCode(StrEnum):
    # INPUT
    INPUT_INVALID = "INPUT_INVALID"
    INPUT_EMPTY = "INPUT_EMPTY"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    INPUT_UNSUPPORTED_ENCODING = "INPUT_UNSUPPORTED_ENCODING"
    INPUT_UNSUPPORTED_EXTENSION = "INPUT_UNSUPPORTED_EXTENSION"
    # CONTENT
    CONTENT_UNSUPPORTED_GENRE = "CONTENT_UNSUPPORTED_GENRE"
    CONTENT_ANALYSIS_FAILED = "CONTENT_ANALYSIS_FAILED"
    # SEARCH
    SEARCH_FAILED = "SEARCH_FAILED"
    SEARCH_FETCH_FAILED = "SEARCH_FETCH_FAILED"
    # LLM
    LLM_CALL_FAILED = "LLM_CALL_FAILED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    # GAME
    GAME_INVALID_COMMAND = "GAME_INVALID_COMMAND"
    GAME_INVALID_STAGE = "GAME_INVALID_STAGE"
    GAME_ALREADY_ENDED = "GAME_ALREADY_ENDED"
    # SESSION
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_CONFLICT = "SESSION_CONFLICT"
    # PERSISTENCE
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"
    # PROTOCOL
    PROTOCOL_INVALID_MESSAGE = "PROTOCOL_INVALID_MESSAGE"
    # INTERNAL
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INTERNAL_UNHANDLED = "INTERNAL_UNHANDLED"


class ErrorEnvelope(BaseModel):
    """对外错误结构：稳定、可阅读、不含内部细节。"""

    model_config = ConfigDict(extra="forbid")

    error_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = ERRORS_SCHEMA_VERSION
