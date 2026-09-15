"""errx 扩展（issue #3）：error_id 生成、对外 envelope 序列化、稳定错误码映射。

- 每个对外信封携带 error_id；同一 error_id 记录进服务端日志（含 cause/stack），
  用户报错时凭 error_id 即可定位。
- 整数码 ↔ 稳定码映射在此登记；未知整数码回落 INTERNAL_ERROR。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.contracts.errors import ErrorDomain, ErrorEnvelope, stable_code
from app.errx import codes

logger = logging.getLogger("wenjing.diagnostics.errors")

# errx 整数码段 → (domain, 稳定码)
_CODE_MAP: dict[int, str] = {
    codes.SESS_NOT_FOUND: "SESSION_NOT_FOUND",
    codes.SESS_ENDED: "SESSION_ENDED",
    codes.SESS_CONFLICT: "SESSION_CONFLICT",
    codes.ENG_INVALID_TRANSITION: "GAME_INVALID_TRANSITION",
    codes.ENG_ROLLBACK_TARGET_MISSING: "GAME_ROLLBACK_TARGET_MISSING",
    codes.ENG_ROLLBACK_OVERFLOW: "GAME_ROLLBACK_OVERFLOW",
    codes.ENG_PLAYER_ACTION_INVALID: "GAME_COMMAND_NOT_ALLOWED",
    codes.ENG_NOT_RUNNING: "GAME_COMMAND_NOT_ALLOWED",
    codes.AGENT_NOT_IN_SESSION: "GAME_COMMAND_NOT_ALLOWED",
    codes.AGENT_PROPOSAL_ALL_REJECTED: "CONTENT_VALIDATION_FAILED",
    codes.LLM_CALL_FAILED: "LLM_CALL_FAILED",
    codes.LLM_OUTPUT_PARSE_FAILED: "LLM_INVALID_OUTPUT",
    codes.LLM_UNKNOWN_MODEL: "LLM_CALL_FAILED",
    codes.CNT_UNSUPPORTED_GENRE: "CONTENT_UNSUPPORTED_GENRE",
    codes.CNT_INSUFFICIENT_SOURCE: "CONTENT_INSUFFICIENT_SOURCE",
    codes.CNT_GENERATION_FAILED: "CONTENT_GENERATION_FAILED",
    codes.INP_EMPTY_MATERIAL: "INPUT_EMPTY_MATERIAL",
    codes.INP_UNSUPPORTED_EXTENSION: "INPUT_UNSUPPORTED_EXTENSION",
    codes.INP_INVALID_ENCODING: "INPUT_INVALID_ENCODING",
    codes.INP_TOO_LARGE: "INPUT_TOO_LARGE",
    codes.SEARCH_UNAVAILABLE: "SEARCH_UNAVAILABLE",
    codes.SEARCH_BLOCKED_TARGET: "SEARCH_BLOCKED_TARGET",
    codes.SEARCH_TIMEOUT: "SEARCH_TIMEOUT",
    codes.PRT_MALFORMED_MESSAGE: "PROTOCOL_MALFORMED_MESSAGE",
    codes.PRT_UNKNOWN_COMMAND: "PROTOCOL_UNKNOWN_COMMAND",
    codes.PER_WRITE_FAILED: "PERSISTENCE_WRITE_FAILED",
    codes.PER_INCOMPATIBLE_SCHEMA: "PERSISTENCE_INCOMPATIBLE_SCHEMA",
    codes.PER_CORRUPT_SNAPSHOT: "PERSISTENCE_CORRUPT_SNAPSHOT",
}

_DOMAIN_BY_SEGMENT: dict[str, ErrorDomain] = {
    "1": ErrorDomain.SESSION,   # SESS
    "2": ErrorDomain.GAME,      # ENG
    "3": ErrorDomain.GAME,      # AGENT 归入 game 域
    "4": ErrorDomain.LLM,       # LLM
    "6": ErrorDomain.CONTENT,   # CNT
    "7": ErrorDomain.INPUT,     # INP
    "8": ErrorDomain.SEARCH,    # SEARCH
    "9": ErrorDomain.PROTOCOL,  # PRT
}


def _map_error(err: Any) -> str:
    """返回稳定码名；未登记回落 INTERNAL_ERROR。"""
    return _CODE_MAP.get(getattr(err, "code", 0), "INTERNAL_ERROR")


def safe_message(err: Any) -> str:
    """为用户生成安全消息：不含内部堆栈/提示词/凭证。"""
    mapped = getattr(err, "code", None)
    base = {
        codes.SESS_NOT_FOUND: "会话不存在或已失效。",
        codes.SESS_ENDED: "会话已结束。",
        codes.SESS_CONFLICT: "操作冲突，请刷新后重试。",
        codes.ENG_INVALID_TRANSITION: "当前阶段不允许该操作。",
        codes.ENG_ROLLBACK_TARGET_MISSING: "回溯目标不存在。",
        codes.ENG_ROLLBACK_OVERFLOW: "回溯步数超出限制。",
        codes.ENG_PLAYER_ACTION_INVALID: "该操作在当前交互下不可用。",
        codes.ENG_NOT_RUNNING: "当前没有等待输入的交互点。",
        codes.LLM_CALL_FAILED: "模型服务暂时不可用，请稍后重试。",
        codes.LLM_OUTPUT_PARSE_FAILED: "模型输出异常，正在重试。",
        codes.LLM_UNKNOWN_MODEL: "模型服务暂时不可用，请稍后重试。",
        codes.CNT_UNSUPPORTED_GENRE: "该课文体裁暂不支持，请导入小说、叙事文、戏剧或人物故事。",
        codes.CNT_INSUFFICIENT_SOURCE: "原文内容不足以生成剧本，请补充更完整的叙事文本。",
        codes.CNT_GENERATION_FAILED: "剧本生成失败，请稍后重试。",
        codes.INP_EMPTY_MATERIAL: "课文内容为空，请粘贴或上传有效文本。",
        codes.INP_UNSUPPORTED_EXTENSION: "仅支持 .txt 或 .md 文件。",
        codes.INP_INVALID_ENCODING: "文件编码无法识别，请使用 UTF-8 或 GBK 编码。",
        codes.INP_TOO_LARGE: "课文内容过长，请缩短后重试。",
        codes.SEARCH_UNAVAILABLE: "网络资料检索暂不可用，将仅基于原文生成。",
        codes.SEARCH_BLOCKED_TARGET: "目标网址不可访问。",
        codes.SEARCH_TIMEOUT: "网络资料获取超时，将仅基于原文生成。",
        codes.PRT_MALFORMED_MESSAGE: "请求格式无法处理。",
        codes.PRT_UNKNOWN_COMMAND: "不支持的命令类型。",
        codes.PER_WRITE_FAILED: "数据保存失败，请稍后重试。",
        codes.PER_INCOMPATIBLE_SCHEMA: "会话数据版本不兼容，无法恢复。",
        codes.PER_CORRUPT_SNAPSHOT: "存档数据损坏，正在尝试重建。",
    }.get(mapped)
    if base:
        return base
    # 未映射：使用固定兜底，绝不透传内部 message
    return "服务内部错误，请稍后重试。"


def log_with_error(err: BaseException, envelope: ErrorEnvelope) -> None:
    """服务端记录完整 cause/stack；日志含 error_id 便于对账。"""
    logger.error(
        "unhandled_error error_id=%s code=%s cause=%s",
        envelope.error_id,
        envelope.code,
        err.__cause__ or err,
        exc_info=(type(err), err, err.__traceback__),
    )


def envelope_for(err: BaseException, *, details: dict | None = None) -> ErrorEnvelope:
    """把内部异常转为对外错误信封（唯一出口；stack 只留在服务端日志）。"""
    stable_name = (
        _map_error(err) if hasattr(err, "code") else "INTERNAL_ERROR"
    )
    _domain, retryable = stable_code(stable_name)
    domain = ErrorDomain(stable_name.split("_", 1)[0].lower())
    extra = getattr(err, "extra", None) or {}
    env = ErrorEnvelope(
        error_id=uuid.uuid4(),
        code=stable_name,
        domain=domain,
        message=safe_message(err),
        retryable=retryable,
        details={**(details or {}), **extra},
    )
    if not isinstance(err, Exception):
        log_with_error(err, env)
    elif err.__traceback__ is not None or getattr(err, "cause", None):
        log_with_error(err, env)
    else:
        logger.info("error_enveloped error_id=%s code=%s", env.error_id, env.code)
    return env
