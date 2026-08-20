"""统一日志配置。

使用标准库 `logging`。约定：
- 每个模块 `logger = logging.getLogger(__name__)`
- 事件溯源（EventStore 的每条 GameEvent）以 structured 形式落一条 `logevent` 日志，
  便于纯内存运行也能从日志还原剧情
- 引擎/phase/Agent 调度/玩家/回溯/LLM 六类关键节点均有对应日志级别
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "wenjing"


class _Formatter(logging.Formatter):
    """结构化 formatter：时间 / 级别 / logger / session / 消息。"""

    def format(self, record: logging.LogRecord) -> str:
        session = record.__dict__.get("session_id", "")
        extra = getattr(record, "extra", None)
        base = super().format(record)
        parts = [base]
        if session:
            parts.append(f"[session={session}]")
        if extra:
            parts.append(f"[extra={extra}]")
        return " ".join(parts)


def configure_logging(
    *,
    level: int = logging.INFO,
    debug: bool = False,
) -> None:
    """初始化根 logger 的处理器与格式。可重复调用；已配置则跳过。"""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if debug else level)

    if logger.handlers:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _Formatter("%(asctime)s %(levelname)-8s %(name)s - %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str, *, session_id: str | None = None) -> logging.Logger:
    """获取带统一前缀的 logger。"""
    full = f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME
    return logging.getLogger(full)


def log_event(record: logging.LogRecord) -> None:
    """供 EventStore 使用：以专用 logger 输出事件溯源日志。"""
    logging.getLogger(LOGGER_NAME).handle(record)


__all__ = ["configure_logging", "get_logger", "LOGGER_NAME"]
