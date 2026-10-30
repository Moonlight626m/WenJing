"""`AssetJobPort` 的 SQLAlchemy 实现（ADR-0005 §5，issue #57）。

台账语义见 `domain/game/media.py::AssetJobPort`。这里只强调两条实现约束：

- **`open` 的裁决要原子**：查重、数上限、落行三步在并发下会各自通过而超发。
  单 worker 部署（见 `README.md` 生产部署一节）下用一把 `asyncio.Lock` 串起来即可，
  不必上库级锁；生成本身**不在**锁内，锁只覆盖三步裁决。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.game.media import (
    _REASON_MAX_CHARS,
    AssetJob,
    AssetJobStatus,
    SceneAssetRequest,
)
from app.infrastructure.models.asset_job import AssetJob as AssetJobRow

logger = logging.getLogger("wenjing.media.asset_jobs")

def _to_job(row: AssetJobRow) -> AssetJob:
    return AssetJob(
        job_id=row.job_id,
        request=SceneAssetRequest(
            session_id=row.session_id,
            branch_id=row.branch_id,
            scene_key=row.scene_key,
            description=row.description,
            org_id=row.org_id,
            script_id=row.script_id,
            user_id=row.user_id,
        ),
        status=AssetJobStatus(row.status),
        asset_id=row.asset_id,
        reason=row.reason,
        created_at=row.created_at,
    )


class SqlAssetJobStore:
    """`asset_jobs` 表上的运行期配图台账。"""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory
        self._lock = asyncio.Lock()

    async def open(
        self, request: SceneAssetRequest, *, limit: int = 0
    ) -> AssetJob | None:
        async with self._lock:
            async with self._factory() as session:
                existing = (
                    await session.execute(
                        select(AssetJobRow).where(
                            AssetJobRow.session_id == request.session_id,
                            AssetJobRow.scene_key == request.scene_key,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    if existing.status != AssetJobStatus.ABANDONED.value:
                        logger.info(
                            "asset_job_deduped",
                            extra={
                                "session_id": str(request.session_id),
                                "wj_extra": {
                                    "scene_key": request.scene_key,
                                    "status": existing.status,
                                },
                            },
                        )
                        return None
                    # 崩溃恢复替上次进程放弃的那条：唯一允许重来的情形（ADR §5）
                    existing.status = AssetJobStatus.PENDING.value
                    existing.reason = ""
                    existing.asset_id = None
                    await session.commit()
                    await session.refresh(existing)
                    logger.info(
                        "asset_job_retried",
                        extra={
                            "session_id": str(request.session_id),
                            "wj_extra": {"scene_key": request.scene_key},
                        },
                    )
                    return _to_job(existing)
                if limit > 0:
                    used = (
                        await session.execute(
                            select(func.count())
                            .select_from(AssetJobRow)
                            .where(AssetJobRow.session_id == request.session_id)
                        )
                    ).scalar_one()
                    if int(used) >= limit:
                        logger.warning(
                            "asset_job_session_cap_reached",
                            extra={
                                "session_id": str(request.session_id),
                                "wj_extra": {
                                    "scene_key": request.scene_key,
                                    "limit": limit,
                                },
                            },
                        )
                        return None
                row = AssetJobRow(
                    session_id=request.session_id,
                    branch_id=request.branch_id,
                    scene_key=request.scene_key,
                    description=request.description,
                    org_id=request.org_id,
                    script_id=request.script_id,
                    user_id=request.user_id,
                    status=AssetJobStatus.PENDING.value,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return _to_job(row)

    async def finish(
        self,
        job_id: uuid.UUID,
        *,
        status: AssetJobStatus,
        asset_id: uuid.UUID | None = None,
        reason: str = "",
    ) -> None:
        async with self._factory() as session:
            row = await session.get(AssetJobRow, job_id)
            if row is None:
                return
            row.status = status.value
            row.asset_id = asset_id
            row.reason = reason[:_REASON_MAX_CHARS]
            await session.commit()

    async def pending(self, *, since: datetime | None = None) -> list[AssetJob]:
        stmt = select(AssetJobRow).where(
            AssetJobRow.status == AssetJobStatus.PENDING.value
        )
        if since is not None:
            stmt = stmt.where(AssetJobRow.created_at >= since)
        stmt = stmt.order_by(AssetJobRow.created_at.asc())
        async with self._factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_to_job(row) for row in rows]

    async def expire(self, *, before: datetime) -> int:
        async with self._factory() as session:
            result = await session.execute(
                update(AssetJobRow)
                .where(
                    AssetJobRow.status == AssetJobStatus.PENDING.value,
                    AssetJobRow.created_at < before,
                )
                .values(
                    status=AssetJobStatus.ABANDONED.value,
                    reason="abandoned by crash recovery (stale pending job)",
                )
            )
            await session.commit()
        count = int(result.rowcount or 0)
        if count:
            logger.warning("asset_jobs_expired", extra={"wj_extra": {"count": count}})
        return count


__all__ = ["SqlAssetJobStore"]
