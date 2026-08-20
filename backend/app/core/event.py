"""事件溯源存储（内存实现）。

MVP 阶段使用 design_03 的内存版 `EventStore`，事件只追加（append-only）。
每条 `GameEvent` 同时以 structured 日志输出（「事件即日志」），使纯内存运行
也能从日志还原整场剧情，便于调试与回溯。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.errx import codes, new

logger = logging.getLogger("wenjing.core.event")

# 事件类型（对齐 design_03 §4.1）
EVENT_STAGE_TRANSITION = "stage_transition"
EVENT_PLOT_ADVANCEMENT = "plot_advancement"
EVENT_DIRECTION = "direction"
EVENT_PROPOSAL = "proposal"
EVENT_VERIFICATION = "verification"
EVENT_PLAYER_ACTION = "player_action"
EVENT_CHARACTER_SPEECH = "character_speech"
EVENT_SYSTEM = "system"
EVENT_ROLLBACK = "rollback"


@dataclass
class GameEvent:
    """单条游戏事件。"""

    event_id: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    parent_id: int | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
        }


class EventStore:
    """内存事件流。MVP 全程常驻内存；PostgreSQL 落库作为后续收尾里程碑。"""

    def __init__(self) -> None:
        self._events: list[GameEvent] = []
        self._counter = 0

    @property
    def events(self) -> list[GameEvent]:
        return self._events

    def __len__(self) -> int:
        return len(self._events)

    @property
    def latest_event_id(self) -> int:
        return self._events[-1].event_id if self._events else 0

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        parent_id: int | None = None,
        *,
        session_id: str = "",
    ) -> GameEvent:
        self._counter += 1
        event = GameEvent(
            event_id=self._counter,
            event_type=event_type,
            payload=payload,
            parent_id=parent_id,
        )
        self._events.append(event)
        # 事件即日志：以结构化形式输出，便于纯内存运行还原剧情
        logger.info(
            "event",
            extra={
                "event_id": event.event_id,
                "event_type": event.event_type,
                "payload": payload,
                "session_id": session_id or None,
            },
        )
        return event

    def rollback_to(self, target_event_id: int, *, session_id: str = "") -> list[GameEvent]:
        """回退到指定事件（保留目标事件），返回被截断的事件列表。"""
        idx = next(
            (i for i, e in enumerate(self._events) if e.event_id == target_event_id),
            -1,
        )
        if idx == -1:
            raise new(
                codes.ENG_ROLLBACK_TARGET_MISSING, extra={"event_id": target_event_id}
            )
        truncated = self._events[idx + 1 :]
        self._events = self._events[: idx + 1]
        logger.info(
            "rollback_to",
            extra={
                "target_event_id": target_event_id,
                "truncated": len(truncated),
                "session_id": session_id or None,
            },
        )
        return truncated
