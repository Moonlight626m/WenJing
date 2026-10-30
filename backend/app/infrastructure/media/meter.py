"""`MediaMeterPort` 持久化实现（issue #41 / ADR-0005 §12）。

把一次媒体调用的计量事实写入 `media_usage`；**best-effort**：任何失败只告警，
绝不阻断主流程（与 `UsageRecorder` 同构）。配额由 `MediaQuotaPort` 独立承担。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.game.media import MediaUsage as MediaUsageFact
from app.infrastructure.models.media_usage import MediaUsage

logger = logging.getLogger("wenjing.media.meter")


class MediaUsageRecorder:
    """把媒体调用明细写入 `media_usage` 的薄适配器（best-effort，独立事务）。"""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def record(self, usage: MediaUsageFact) -> None:
        """写入一条计量记录；无归属或落库失败只告警，不向调用方抛出。"""
        if usage.org_id is None or usage.user_id is None:
            logger.warning(
                "media_usage_record_skipped_no_owner kind=%s provider=%s",
                usage.kind.value,
                usage.provider,
            )
            return
        try:
            async with self._factory() as session:
                session.add(
                    MediaUsage(
                        kind=usage.kind.value,
                        provider=usage.provider or "unknown",
                        model=usage.model,
                        units=usage.units,
                        size=usage.size,
                        org_id=usage.org_id,
                        user_id=usage.user_id,
                        script_id=usage.script_id,
                        session_id=usage.session_id,
                        meta=dict(usage.meta),
                    )
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - 计量永不阻断业务
            logger.warning(
                "media_usage_record_failed error=%s kind=%s org=%s",
                exc,
                usage.kind.value,
                usage.org_id,
            )


__all__ = ["MediaUsageRecorder"]
