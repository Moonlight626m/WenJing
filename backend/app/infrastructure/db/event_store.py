"""PostgreSQL 持久化事件存储（design_04 §2.3 + issue #8 分支语义）。

分支 UUID 统一映射（接缝②）：
- 内存 `EventStore` 用整数分支 id（1 = 主分支，回溯时递增）；
- 持久化用 UUID。`branch_uuid(session_id, branch_int)` 以 uuid5 确定性推导，
  同一会话同一内存分支恒映射到同一 UUID（天然幂等，恢复后不冲突）。

事务边界（#5 竖切接缝）：
- `write_pending(session, session_id)` 只做插入不提交，供 SessionApplication 把
  命令行 + 事件行 + head/version 放进同一事务；返回插入的行（含 DB 自增 id）。
- `flush` = write_pending + commit（兼容旧回调式落库）。
- flush 按分支分组、沿血缘序（父先于子）写入；为每个非主分支补建
  event_branches 行（parent/root_sequence 由内存 BranchMeta 推导）。

恢复（#5 断线重连接缝）：
- `restore_active_branch` 从 DB 重建与活动分支一致的全部内存分支结构与事件流，
  旧分支事件一并载入（可审计），活动分支由 sessions.active_branch_id 反查。
"""

from __future__ import annotations

import logging
import uuid as uuid_mod

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.game.event import MAIN_BRANCH_ID, BranchMeta, EventStore, GameEvent
from app.infrastructure.models.event import EVENTS_SCHEMA_VERSION, GameEventRecord
from app.infrastructure.models.event_branch import EventBranchRecord
from app.infrastructure.models.session import Session

logger = logging.getLogger("wenjing.db.event_store")

_SESSION_KEY = "session_id"
_EVENT_KEY = "event_id"
_TIMESTAMP_KEY = "timestamp"

MAIN_BRANCH_NS = uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, "wenjing:branches")


def main_branch_id(session_id: str | uuid_mod.UUID) -> uuid_mod.UUID:
    """会话主分支的确定性 id（同会话恒定，天然幂等）。"""
    return branch_uuid(session_id, MAIN_BRANCH_ID)


def branch_uuid(session_id: str | uuid_mod.UUID, branch_int: int) -> uuid_mod.UUID:
    """内存整数分支 → 持久化 UUID 的确定性映射（接缝②权威函数）。"""
    sid = _require_uuid(session_id)
    if branch_int == MAIN_BRANCH_ID:
        return uuid_mod.uuid5(MAIN_BRANCH_NS, f"{sid}:main")
    return uuid_mod.uuid5(MAIN_BRANCH_NS, f"{sid}:branch:{branch_int}")


EVENT_NS = uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, "wenjing:events")


def event_uuid(
    session_id: str | uuid_mod.UUID, branch_int: int, local_event_id: int
) -> uuid_mod.UUID:
    """内存整数事件 → 契约 DomainEvent UUID 的确定性映射（幂等可复现）。"""
    sid = _require_uuid(session_id)
    return uuid_mod.uuid5(EVENT_NS, f"{sid}:{branch_int}:{local_event_id}")


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

    def active_branch_uuid(self, session_id: str | uuid_mod.UUID) -> uuid_mod.UUID:
        """会话当前活动分支的持久化 UUID（由内存活动分支确定性推导）。"""
        return branch_uuid(session_id, self.active_branch_id)

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
        self, target_event_id: int, *, session_id: str = "", command_id: str = ""
    ) -> list[GameEvent]:
        superseded = super().rollback_to(
            target_event_id, session_id=session_id, command_id=command_id
        )
        # 已 flush 的 DB 行由调用方另行 truncate_after；这里只清理尚未落库的缓存
        ids = {e.event_id for e in superseded}
        self._pending = [e for e in self._pending if e.event_id not in ids]
        return superseded

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    def pending_events(self) -> list[GameEvent]:
        return list(self._pending)

    # ===== 分支行登记 =====

    async def _ensure_branch_row(
        self,
        session: AsyncSession,
        sid: uuid_mod.UUID,
        branch_int: int,
        *,
        seq_of_local: dict[int, int] | None = None,
    ) -> uuid_mod.UUID:
        """确保 event_branches 行存在（含父分支与继承终点），返回分支 UUID。"""
        ub = branch_uuid(sid, branch_int)
        if branch_int == MAIN_BRANCH_ID:
            values: dict = {"root_sequence": 0, "parent_branch_id": None}
        else:
            meta = self.branch_meta(branch_int)
            parent_int = meta.parent_branch_id or MAIN_BRANCH_ID
            await self._ensure_branch_row(session, sid, parent_int, seq_of_local=seq_of_local)
            root_seq = await self._resolve_root_sequence(
                session, sid, branch_uuid(sid, parent_int), meta.root_event_id, seq_of_local
            )
            values = {
                "root_sequence": root_seq,
                "parent_branch_id": branch_uuid(sid, parent_int),
            }
        stmt = (
            pg_insert(EventBranchRecord)
            .values(id=ub, session_id=sid, **values)
            .on_conflict_do_nothing(index_elements=[EventBranchRecord.id])
        )
        await session.execute(stmt)
        return ub

    async def _resolve_root_sequence(
        self,
        session: AsyncSession,
        sid: uuid_mod.UUID,
        parent_ub: uuid_mod.UUID,
        root_local_id: int,
        seq_of_local: dict[int, int] | None,
    ) -> int:
        """继承终点事件在父分支 sequence 空间中的位置。"""
        if seq_of_local and root_local_id in seq_of_local:
            return seq_of_local[root_local_id]
        stmt = select(GameEventRecord.sequence).where(
            GameEventRecord.session_id == sid,
            GameEventRecord.branch_id == parent_ub,
            GameEventRecord.payload[_EVENT_KEY].as_integer() == root_local_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError(
                f"回溯根事件 {root_local_id} 未落库，无法登记分支继承终点"
            )
        return int(row)

    async def _next_sequence(
        self, session: AsyncSession, branch: uuid_mod.UUID
    ) -> int:
        current = await session.execute(
            select(func.max(GameEventRecord.sequence)).where(
                GameEventRecord.branch_id == branch
            )
        )
        # 注意 max(sequence)=0 时 `0 or -1` 会得 -1（falsy-zero 陷阱），必须显式判 None
        row = current.scalar_one_or_none()
        return int(row) + 1 if row is not None else 0

    def _branches_in_lineage_order(self, branch_ints: list[int]) -> list[int]:
        """父分支先于子分支的处理顺序。"""

        def depth(b: int) -> int:
            d, cur = 0, b
            while cur != MAIN_BRANCH_ID:
                cur = self.branch_meta(cur).parent_branch_id or MAIN_BRANCH_ID
                d += 1
            return d

        return sorted(set(branch_ints), key=lambda b: (depth(b), b))

    # ===== 写入 =====

    async def write_pending(
        self, session: AsyncSession, session_id: str
    ) -> list[GameEventRecord]:
        """把待落库事件写入 `events` 表（不提交）；返回插入的行。

        - 按分支分组、血缘序处理；为涉及的非主分支补建 event_branches 行。
        - 行内 payload 保留本地 event_id，保持与内存顺序一致。
        """
        if not self._pending:
            return []
        sid = _require_uuid(session_id)

        by_branch: dict[int, list[GameEvent]] = {}
        for event in self._pending:
            by_branch.setdefault(event.branch_id, []).append(event)

        written_rows: list[GameEventRecord] = []
        seq_of_local: dict[int, int] = {}
        for branch_int in self._branches_in_lineage_order(list(by_branch)):
            ub = await self._ensure_branch_row(
                session, sid, branch_int, seq_of_local=seq_of_local
            )
            seq = await self._next_sequence(session, ub)
            offset = 0
            for event in by_branch[branch_int]:
                payload = dict(event.payload)
                payload.setdefault(_SESSION_KEY, str(sid))
                payload.setdefault(_EVENT_KEY, event.event_id)
                payload.setdefault(_TIMESTAMP_KEY, event.timestamp)
                row = GameEventRecord(
                    session_id=sid,
                    branch_id=ub,
                    sequence=seq + offset,
                    event_type=event.event_type,
                    payload=payload,
                    schema_version=EVENTS_SCHEMA_VERSION,
                )
                session.add(row)
                written_rows.append(row)
                seq_of_local[event.event_id] = seq + offset
                offset += 1
            # asyncpg 不允许同一连接并发执行：显式 flush，避免后续 execute 的
            # 隐式 autoflush 与在途语句重叠（多分支批次时必现）
            await session.flush()
        self._pending.clear()
        logger.info(
            "event_store_written",
            extra={"session_id": str(sid), "written": len(written_rows)},
        )
        return written_rows

    async def flush(self, session: AsyncSession, session_id: str) -> int:
        """write_pending + commit（兼容回调式落库）；返回写入条数。"""
        rows = await self.write_pending(session, session_id)
        await session.commit()
        return len(rows)

    # ===== 恢复（#5 断线重连接缝）=====

    async def restore_active_branch(
        self, session: AsyncSession, session_id: str
    ) -> list[GameEvent]:
        """从 DB 重建内存事件流：全部分支结构 + 活动分支指针。

        分支整数 id 按 created_at 顺序重排（主分支恒为 1）；事件流载入全部
        历史（含被放弃分支，可审计）；活动分支取 sessions.active_branch_id。
        """
        sid = _require_uuid(session_id)

        sess_row = await session.get(Session, sid)
        if sess_row is None:
            raise ValueError(f"session {sid} 不存在")

        branch_rows = (
            (
                await session.execute(
                    select(EventBranchRecord)
                    .where(EventBranchRecord.session_id == sid)
                    .order_by(EventBranchRecord.created_at, EventBranchRecord.id)
                )
            )
            .scalars()
            .all()
        )
        # 恢复 int 分支 id：优先按确定性 uuid5 反查（1..N），未命中的随机分支行
        # （如 commit_rollback_branch 直接创建）按 created_at 顺序续编
        uuid_to_int: dict[uuid_mod.UUID, int] = {}
        for candidate in range(1, len(branch_rows) + 1):
            uuid_to_int[branch_uuid(sid, candidate)] = candidate
        int_to_row: dict[int, EventBranchRecord] = {}
        next_int = len(branch_rows) + 1
        for row in branch_rows:
            if row.id in uuid_to_int:
                int_to_row[uuid_to_int[row.id]] = row
            else:
                uuid_to_int[row.id] = next_int
                int_to_row[next_int] = row
                next_int += 1
        if not uuid_to_int:
            self._events, self._counter, self._pending = [], 0, []
            return []

        event_rows = (
            (
                await session.execute(
                    select(GameEventRecord)
                    .where(GameEventRecord.session_id == sid)
                    .order_by(GameEventRecord.id)
                )
            )
            .scalars()
            .all()
        )

        events: list[GameEvent] = []
        for row in event_rows:
            payload = dict(row.payload or {})
            local_id = int(payload.pop(_EVENT_KEY, row.id))
            events.append(
                GameEvent(
                    event_id=local_id,
                    event_type=row.event_type,
                    payload=payload,
                    parent_id=row.parent_id,
                    timestamp=float(payload.pop(_TIMESTAMP_KEY, 0.0) or 0.0),
                    branch_id=uuid_to_int.get(row.branch_id, MAIN_BRANCH_ID),
                )
            )

        # 重建分支元数据：root_event_id = 父分支内第 root_sequence 个事件（0 起）
        by_branch_events: dict[int, list[GameEvent]] = {}
        for e in events:
            by_branch_events.setdefault(e.branch_id, []).append(e)
        self._branch_meta = {}
        for b_int, row in int_to_row.items():
            if row.parent_branch_id is None:
                self._branch_meta[b_int] = BranchMeta(
                    branch_id=b_int, parent_branch_id=None, root_event_id=0
                )
            else:
                parent_int = uuid_to_int.get(row.parent_branch_id, MAIN_BRANCH_ID)
                siblings = by_branch_events.get(parent_int, [])
                root_local = (
                    siblings[row.root_sequence].event_id
                    if row.root_sequence < len(siblings)
                    else 0
                )
                self._branch_meta[b_int] = BranchMeta(
                    branch_id=b_int,
                    parent_branch_id=parent_int,
                    root_event_id=root_local,
                )

        self._events = events
        self._counter = max((e.event_id for e in events), default=0)
        self._branch_counter = max(int_to_row, default=MAIN_BRANCH_ID)
        active_int = uuid_to_int.get(sess_row.active_branch_id, MAIN_BRANCH_ID)
        self._active_branch = active_int
        self._pending.clear()
        logger.info(
            "event_store_restored",
            extra={
                "session_id": str(sid),
                "count": len(events),
                "branches": len(int_to_row),
                "active_branch": active_int,
            },
        )
        return self.active_events()

    async def restore(self, session: AsyncSession, session_id: str) -> list[GameEvent]:
        """兼容旧接口：载入会话全部事件行（不分分支，按 id 序）。"""
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
