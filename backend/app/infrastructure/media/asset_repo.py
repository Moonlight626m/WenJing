"""`AssetRepositoryPort` 的 SQLAlchemy 实现（ADR-0005 §4，issue #42）。

资产元数据落 `assets` 表；`object_key` 只在此与端口内部流转。`save` 按主键 upsert，
`find_by_dedup_key` 按 org 作用域查缓存（命中即跳过付费调用）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.game.media import (
    AssetCredit,
    AssetKind,
    AssetRecord,
    AssetSource,
    AssetStatus,
)
from app.infrastructure.models.asset import Asset


def _to_row(record: AssetRecord) -> Asset:
    return Asset(
        asset_id=record.asset_id,
        object_key=record.object_key,
        kind=record.kind.value,
        status=record.status.value,
        source=record.source.value,
        provider=record.provider,
        model=record.model,
        content_hash=record.content_hash,
        width=record.width,
        height=record.height,
        org_id=record.org_id,
        script_id=record.script_id,
        session_id=record.session_id,
        dedup_key=record.dedup_key,
        version=record.version,
        author=record.credit.author,
        license=record.credit.license,
        source_url=record.credit.source_url,
        license_url=record.credit.license_url,
    )


def _to_record(row: Asset) -> AssetRecord:
    return AssetRecord(
        asset_id=row.asset_id,
        object_key=row.object_key,
        kind=AssetKind(row.kind),
        status=AssetStatus(row.status),
        source=AssetSource(row.source),
        provider=row.provider,
        model=row.model,
        credit=AssetCredit(
            author=row.author,
            license=row.license,
            source_url=row.source_url,
            license_url=row.license_url,
        ),
        content_hash=row.content_hash,
        width=row.width,
        height=row.height,
        org_id=row.org_id,
        script_id=row.script_id,
        session_id=row.session_id,
        dedup_key=row.dedup_key,
        version=row.version,
        created_at=row.created_at,
    )


class SqlAssetRepository:
    """`AssetRepositoryPort` 的关系型实现。"""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def save(self, record: AssetRecord) -> AssetRecord:
        async with self._factory() as session:
            await session.merge(_to_row(record))
            await session.commit()
        return record

    async def get_by_id(self, asset_id: uuid.UUID) -> AssetRecord | None:
        async with self._factory() as session:
            row = await session.get(Asset, asset_id)
        return _to_record(row) if row is not None else None

    async def find_by_dedup_key(
        self,
        *,
        org_id: uuid.UUID,
        dedup_key: str,
        status: AssetStatus | None = None,
    ) -> AssetRecord | None:
        """按 (org, dedup_key) 取最新一行；`status` 给定时只认该状态。

        不过滤状态时会踩坑：并发/崩溃留下的 pending 行时间戳更新，会把更早的 READY
        行遮住，于是缓存假性未命中、再次付费生成。
        """
        async with self._factory() as session:
            stmt = select(Asset).where(
                Asset.org_id == org_id, Asset.dedup_key == dedup_key
            )
            if status is not None:
                stmt = stmt.where(Asset.status == status.value)
            stmt = stmt.order_by(Asset.created_at.desc(), Asset.asset_id.desc()).limit(1)
            row = (await session.execute(stmt)).scalar_one_or_none()
        return _to_record(row) if row is not None else None


__all__ = ["SqlAssetRepository"]
