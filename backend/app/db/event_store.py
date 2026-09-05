"""PostgreSQL 持久化事件存储（design_04 §2.3 落库衔接）。

`PersistentEventStore` 在内存 `EventStore` 之上追加持久化：`append` 仍同步维护
内存列表（供引擎无改动地使用），写库由调用方在合适的断点显式 `flush` 完成；
`restore` 从 `events` 表重建内存事件流（会话恢复）；`truncate_after` 用于回溯截断。

设计要点：
- 事件 append-only，内存与 DB 均为只追加。
- `flush` 批量将 `_pending` 写入 `events` 表：先确保会话主分支存在，再按分支内
  连续 sequence 写入；本地事件 id 记录在 payload 以保持与内存顺序一致。
- 未接 DB 时退化为纯内存，行为与 `EventStore` 一致（`make test` 无需 DB）。
"""

from __future__ import annotations

import logging
import uuid as uuid_mod

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event import EventStore, GameEvent
from app.models.event import EVENTS_SCHEMA_VERSION, GameEventRecord
from app.models.event_branch import EventBranchRecord

logger = logging.getLogger("wenjing.db.event_store")

_SESSION_KEY = "session_id"
_EVENT_KEY = "event_id"
_TIMESTAMP_KEY = "timestamp"

MAIN_BRANCH_NS = uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, "wenjing:branches")


def main_branch_id(session_id: str | uuid_mod.UUID) -> uuid_mod.UUID:
    """会话主分支的确定性 id（同会话恒定，天然幂等）。"""
    return uuid_mod.uuid5(MAIN_BRANCH_NS, f"{session_id}:main")


def _require_uuid(session_id: str | uuid_mod.UUID) -> uuid_mod.UUID:
    if isinstance(session_id, uuid_mod.UUID):
        return session_id
    try:
        return uuid_mod.UUID(str(session_id))
    except ValueError as exc:
        raise ValueError(
            f"session_id 必须是 UUID，收到 {session_id!r}（持久化要求合法会话标识）"
        ) from exc


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

    async def _ensure_main_branch(
        self, session: AsyncSession, sid: uuid_mod.UUID
    ) -> None:
        stmt = (
            pg_insert(EventBranchRecord)
            .values(id=main_branch_id(sid), session_id=sid, root_sequence=0)
            .on_conflict_do_nothing(index_elements=[EventBranchRecord.id])
        )
        await session.execute(stmt)

    async def _next_sequence(
        self, session: AsyncSession, branch: uuid_mod.UUID
    ) -> int:
        current = await session.execute(
            select(func.max(GameEventRecord.sequence)).where(
                GameEventRecord.branch_id == branch
            )
        )
        return int(current.scalar_one() or -1) + 1

    async def flush(self, session: AsyncSession, session_id: str) -> int:
        """把待落库事件写入 `events` 表（含主分支登记），返回本次写入条数。"""
        if not self._pending:
            return 0
        sid = _require_uuid(session_id)
        branch = main_branch_id(sid)
        await self._ensure_main_branch(session, sid)
        seq = await self._next_sequence(session, branch)

        written = 0
        for event in self._pending:
            payload = dict(event.payload)
            payload.setdefault(_SESSION_KEY, session_id)
            payload.setdefault(_EVENT_KEY, event.event_id)
            payload.setdefault(_TIMESTAMP_KEY, event.timestamp)
            session.add(
                GameEventRecord(
                    session_id=sid,
                    branch_id=branch,
                    sequence=seq + written,
                    event_type=event.event_type,
                    payload=payload,
                    parent_id=event.parent_id,
                    schema_version=EVENTS_SCHEMA_VERSION,
                )
            )
            written += 1
        # 原子性由调用方事务边界决定；此处统一 commit 以维持既有契约
        await session.commit()
        self._pending.clear()
        logger.info(
            "event_store_flushed",
            extra={
                "session_id": str(sid),
                "branch_id": str(branch),
                "written": written,
            },
        )
        return written

    async def restore(self, session: AsyncSession, session_id: str) -> list[GameEvent]:
        """从 `events` 表（活动分支语义由 #8 接管前为全部行）重建内存事件流。"""
        sid = _require_uuid(session_id)
        stmt = (
            select(GameEventRecord)
            .where(GameEventRecord.session_id == sid)
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
            extra={"session_id": str(sid), "count": len(events)},
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
