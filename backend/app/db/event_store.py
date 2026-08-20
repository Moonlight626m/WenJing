"""PostgreSQL 持久化事件存储（design_04 §2.3 落库衔接）。

`PersistentEventStore` 在内存 `EventStore` 之上追加持久化：`append` 仍同步维护
内存列表（供引擎无改动地使用），写库由调用方在合适的断点显式 `flush` 完成；
`restore` 从 `events` 表重建内存事件流（会话恢复）；`truncate_after` 用于回溯截断。

设计要点：
- 事件 append-only，内存与 DB 均为只追加。
- `flush` 批量将 `_pending` 写入 `events` 表；本地事件 id 记录在 payload 以保持
  与内存顺序一致，DB 自增 id 作为权威 id 供 `restore` 使用。
- 未接 DB 时退化为纯内存，行为与 `EventStore` 一致（`make test` 无需 DB）。
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event import EventStore, GameEvent
from app.models.event import GameEventRecord

logger = logging.getLogger("wenjing.db.event_store")

_SESSION_KEY = "session_id"
_EVENT_KEY = "event_id"
_TIMESTAMP_KEY = "timestamp"


class PersistentEventStore(EventStore):
    """带可选 PostgreSQL 落库的内存事件流。"""

    def __init__(self) -> None:
        super().__init__()
        self._pending: list[GameEvent] = []

    def append(
        self,
        event_type: str,
        payload: dict,
        parent_id: int | None = None,
        *,
        session_id: str = "",
    ) -> GameEvent:
        event = super().append(
            event_type, payload, parent_id=parent_id, session_id=session_id
        )
        self._pending.append(event)
        return event

    def rollback_to(
        self, target_event_id: int, *, session_id: str = ""
    ) -> list[GameEvent]:
        truncated = super().rollback_to(target_event_id, session_id=session_id)
        # 已 flush 的 DB 行由调用方另行 truncate_after；这里只清理尚未落库的缓存
        ids = {e.event_id for e in truncated}
        self._pending = [e for e in self._pending if e.event_id not in ids]
        return truncated

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    async def flush(self, session: AsyncSession, session_id: str) -> int:
        """把待落库事件写入 `events` 表，返回本次写入条数。"""
        if not self._pending:
            return 0
        written = 0
        for event in self._pending:
            payload = dict(event.payload)
            payload.setdefault(_SESSION_KEY, session_id)
            payload.setdefault(_EVENT_KEY, event.event_id)
            payload.setdefault(_TIMESTAMP_KEY, event.timestamp)
            session.add(
                GameEventRecord(
                    session_id=session_id,
                    event_type=event.event_type,
                    payload=payload,
                    parent_id=event.parent_id,
                )
            )
            written += 1
        await session.commit()
        self._pending.clear()
        logger.info(
            "event_store_flushed",
            extra={"session_id": session_id or None, "written": written},
        )
        return written

    async def restore(self, session: AsyncSession, session_id: str) -> list[GameEvent]:
        """从 `events` 表重建内存事件流（会话恢复）。"""
        stmt = (
            select(GameEventRecord)
            .where(GameEventRecord.session_id == session_id)
            .order_by(GameEventRecord.id)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        events: list[GameEvent] = []
        for row in rows:
            payload = dict(row.payload or {})
            restored_id = payload.pop(_EVENT_KEY, row.id)
            events.append(
                GameEvent(
                    event_id=int(restored_id),
                    event_type=row.event_type,
                    payload=payload,
                    parent_id=row.parent_id,
                    timestamp=float(payload.pop(_TIMESTAMP_KEY, 0.0) or 0.0),
                )
            )
        self._events = events
        self._counter = max((e.event_id for e in events), default=0)
        self._pending.clear()
        logger.info(
            "event_store_restored",
            extra={"session_id": session_id or None, "count": len(events)},
        )
        return events

    async def truncate_after(self, session: AsyncSession, target_event_id: int) -> int:
        """删除 `target_event_id` 之后的事件行（回溯截断）。返回删除行数。"""
        stmt = delete(GameEventRecord).where(
            GameEventRecord.payload[_EVENT_KEY].as_integer() > target_event_id
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0
