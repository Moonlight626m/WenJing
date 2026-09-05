"""结构化日志（issue #3）：部署输出 JSON、开发可读；默认脱敏。

脱敏原则（spec 决策）：默认日志不含 API key、完整课文、完整 prompt、
完整玩家自由输入 —— 命中敏感键的值截断为 `<redacted:N>`。
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.diagnostics.context import CorrelationFilter

LOGGER_NAME = "wenjing"

# 键名命中即视为敏感（大小写不敏感子串匹配）
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "prompt",
    "raw_text",
    "normalized_text",
    "player_input",
    "free_input",
)

MAX_SAFE_VALUE_LEN = 80


def _is_sensitive(key: str) -> bool:
    low = key.lower()
    return any(part in low for part in SENSITIVE_KEY_PARTS)


def sanitize_value(value: Any) -> str:
    text = str(value)
    if len(text) > MAX_SAFE_VALUE_LEN:
        return f"<redacted:len={len(text)}>"
    return text


def sanitize_extra(extra: dict[str, Any]) -> dict[str, str]:
    """extra 落日志前的统一处理：敏感键替换为占位，其余截断限长。"""
    out: dict[str, str] = {}
    for key, value in extra.items():
        if _is_sensitive(key):
            out[key] = "<redacted>"
        else:
            out[key] = sanitize_value(value)
    return out


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
            from app.config import get_settings

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


__all__ = ["configure_logging", "get_logger", "LOGGER_NAME", "sanitize_extra"]
