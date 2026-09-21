"""结构化日志（issue #3）：部署输出 JSON、开发可读。

内容脱敏策略（放宽，排障优先）：业务内容（prompt、课文、玩家输入）全量落日志；
仅凭据类键（api_key / password / authorization / secret）仍替换为 `<redacted>`，
日志中永不出现密钥、口令、凭证。
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.infrastructure.diagnostics.context import CorrelationFilter

LOGGER_NAME = "wenjing"

# 凭据类键名命中即替换（大小写不敏感子串匹配）；业务内容不再脱敏
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)


def _is_sensitive(key: str) -> bool:
    low = key.lower()
    if low.endswith("tokens"):
        # 用量计量字段（prompt_tokens/completion_tokens）不是凭据
        return False
    return any(part in low for part in SENSITIVE_KEY_PARTS)


def sanitize_extra(extra: dict[str, Any]) -> dict[str, str]:
    """extra 落日志前的统一处理：凭据键替换为占位，业务内容原样保留。"""
    out: dict[str, str] = {}
    for key, value in extra.items():
        if _is_sensitive(key):
            out[key] = "<redacted>"
        else:
            out[key] = str(value)
    return out


def redact_credentials(obj: Any) -> Any:
    """递归擦除凭据键（供 body 级全量打印使用）：命中敏感键的值替换为占位。

    只处理 dict/list 结构；其他类型原样返回。JSON 解析失败的 body 由调用方决定去留。
    """
    if isinstance(obj, dict):
        return {
            key: "<redacted>" if _is_sensitive(key) else redact_credentials(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact_credentials(item) for item in obj]
    return obj


_CORRELATION_FIELDS = (
    "request_id",
    "session_id",
    "command_id",
    "generation_id",
    "llm_call_id",
    "correlation_id",
    "duration_ms",
    "error_code",
    "retry_count",
)


class HumanFormatter(logging.Formatter):
    """开发模式：可读单行 + 关联字段后缀。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        tail = []
        for key in _CORRELATION_FIELDS:
            val = record.__dict__.get(key)
            if val is not None:
                tail.append(f"{key}={val}")
        extra_raw = record.__dict__.get("wj_extra")
        if extra_raw:
            tail.append(f"extra={sanitize_extra(extra_raw)}")
        return " ".join([base, *tail])


class JsonFormatter(logging.Formatter):
    """部署模式：一行 JSON 事件。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _CORRELATION_FIELDS:
            val = record.__dict__.get(key)
            if val is not None:
                payload[key] = val
        extra_raw = record.__dict__.get("wj_extra")
        if extra_raw:
            payload["extra"] = sanitize_extra(extra_raw)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else ""
            # stack 仅服务端可见，不进对外信封；但保留在部署日志里以定位错误
            payload["stack"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    *,
    level: int = logging.INFO,
    debug: bool = False,
    json_mode: bool | None = None,
) -> None:
    """初始化 logger。json_mode=None 时按 debug 取反（生产 JSON/开发可读）。"""
    if json_mode is None:
        try:
            from app.infrastructure.config import get_settings

            json_mode = not get_settings().debug
        except Exception:
            json_mode = True

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if debug else level)
    # 可重复调用：重置 handler 以应用新格式（测试需要）
    for h in list(logger.handlers):
        logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    fmt = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    handler.setFormatter(JsonFormatter() if json_mode else HumanFormatter(fmt))
    handler.addFilter(CorrelationFilter())
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """获取带统一前缀的 logger。

    结构化字段经标准 extra= 关键字传递；
    需要脱敏的结构化负载放 `extra={"wj_extra": {...}}`。
    """
    full = f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME
    return logging.getLogger(full)


def log_event(record: logging.LogRecord) -> None:
    """供 EventStore 使用：以专用 logger 输出事件溯源日志。"""
    logging.getLogger(LOGGER_NAME).handle(record)


def exc_reason(exc: BaseException) -> str:
    """统一 fallback 日志的原因格式：`类型: 消息`。"""
    return f"{type(exc).__name__}: {exc}"


__all__ = [
    "configure_logging",
    "exc_reason",
    "get_logger",
    "LOGGER_NAME",
    "redact_credentials",
    "sanitize_extra",
]
