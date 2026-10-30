"""`MediaQuotaPort` 的 org 级配额闸（issue #41 / ADR-0005 §12）。

- **付费调用前**扣减额度：`try_acquire` 在**同一把锁内**完成 seed + check + 预扣，
  并发调用不会超额；推荐付费调用方使用：
  `if await quota.try_acquire(...): await paid_call()`。
- `check` / `consume` 是端口形状（非原子，适合串行/单飞行路径）；并发路径请用
  `try_acquire`。
- 预算单位与 `media_usage.units` 一致：image=张、tts=字符、asr=秒；调用方须传入预计
  `units`，否则预扣与计量口径不一致。
- 首次触达某 `(org, kind)` 时从 `media_usage` 聚合**种子**，此后按进程内计数推进；
  进程重启后重新种子（单 worker 约束）。
- 与计量严格分离，但计量 best-effort、预扣也可能随进程崩溃丢失，故配额是**软约束**
  （ADR-0005 §12），硬上限由 M4-3 的每会话上限兜底。
- 未配置或 `limit <= 0` 视为不限额。
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.game.media import MediaKind
from app.infrastructure.models.media_usage import MediaUsage

_Key = tuple[uuid.UUID, MediaKind]


class MediaQuotaService:
    """基于 `media_usage` 已用量 + 进程内预扣的配额实现。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        limits: Mapping[MediaKind, int],
    ) -> None:
        self._factory = session_factory
        self._limits = dict(limits)
        self._counts: Counter[_Key] = Counter()
        self._seeded: set[_Key] = set()
        self._lock = asyncio.Lock()

    async def try_acquire(
        self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1
    ) -> bool:
        """原子闸门：额度足够则预扣并返回 True，否则返回 False。"""
        limit = self._limits.get(kind, 0)
        if limit <= 0:
            return True
        key = (org_id, kind)
        async with self._lock:
            if key not in self._seeded:
                self._counts[key] = await self._used(org_id, kind)
                self._seeded.add(key)
            if self._counts[key] + units > limit:
                return False
            self._counts[key] += units
            return True

    async def check(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> bool:
        """只读检查（非原子）；并发路径请用 `try_acquire`。"""
        limit = self._limits.get(kind, 0)
        if limit <= 0:
            return True
        await self._seed(org_id, kind)
        return self._counts[(org_id, kind)] + units <= limit

    async def consume(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> None:
        """预扣额度（非原子）；不限额时为空操作。"""
        if self._limits.get(kind, 0) <= 0:
            return
        await self._seed(org_id, kind)
        self._counts[(org_id, kind)] += units

    async def _seed(self, org_id: uuid.UUID, kind: MediaKind) -> None:
        key = (org_id, kind)
        if key in self._seeded:
            return
        async with self._lock:
            if key in self._seeded:
                return
            self._counts[key] = await self._used(org_id, kind)
            self._seeded.add(key)

    async def _used(self, org_id: uuid.UUID, kind: MediaKind) -> int:
        async with self._factory() as session:
            stmt = select(func.coalesce(func.sum(MediaUsage.units), 0)).where(
                MediaUsage.org_id == org_id,
                MediaUsage.kind == kind.value,
            )
            return int((await session.execute(stmt)).scalar_one() or 0)


__all__ = ["MediaQuotaService"]
