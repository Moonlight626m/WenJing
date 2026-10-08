"""资产仓库集成测试（issue #42 / ADR-0005 §4）。

仅 async 夹具，避免与端点模块（同步 TestClient）的事件循环混用。
依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401
from app.domain.game.media import AssetKind, AssetRecord, AssetStatus
from app.infrastructure.media import SqlAssetRepository

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def _engine():
    return create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})


async def _db_available() -> bool:
    engine = _engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def factory():
    if not await _db_available():
        pytest.skip("PostgreSQL 未可用，跳过资产仓库集成测试")
    engine = _engine()
    async with engine.begin() as conn:
        from conftest import reset_baseline_schema

        await reset_baseline_schema(conn)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            from conftest import drop_baseline_schema

            await drop_baseline_schema(conn)
        await engine.dispose()


async def test_repo_save_get_and_dedup(factory) -> None:
    from conftest import create_actor

    actor = await create_actor(factory, name="资产仓库学校")
    repo = SqlAssetRepository(session_factory=factory)
    record = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="org/scene-1.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        org_id=actor.org_id,
        dedup_key="dedup-1",
    )
    await repo.save(record)

    fetched = await repo.get_by_id(record.asset_id)
    assert fetched is not None
    assert fetched.object_key == "org/scene-1.webp"
    assert fetched.status is AssetStatus.READY

    found = await repo.find_by_dedup_key(org_id=actor.org_id, dedup_key="dedup-1")
    assert found is not None and found.asset_id == record.asset_id
    assert await repo.find_by_dedup_key(org_id=uuid.uuid4(), dedup_key="dedup-1") is None


async def test_repo_save_upserts_by_asset_id(factory) -> None:
    from conftest import create_actor

    actor = await create_actor(factory, name="资产 upsert 学校")
    repo = SqlAssetRepository(session_factory=factory)
    record = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="org/a.webp",
        kind=AssetKind.AVATAR,
        status=AssetStatus.PENDING,
        org_id=actor.org_id,
    )
    await repo.save(record)
    record.status = AssetStatus.READY
    record.object_key = "org/a-ready.webp"
    await repo.save(record)

    fetched = await repo.get_by_id(record.asset_id)
    assert fetched is not None
    assert fetched.status is AssetStatus.READY
    assert fetched.object_key == "org/a-ready.webp"
