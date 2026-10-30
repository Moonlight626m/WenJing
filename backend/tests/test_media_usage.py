"""媒体计量与配额测试（issue #41 / ADR-0005 §12）。

覆盖：media_usage 落库、计量 best-effort 不阻断、配额 check+consume 与 DB 种子。
依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401
from app.domain.game.media import MediaKind, MediaUsage
from app.infrastructure.media import MediaQuotaService, MediaUsageRecorder
from app.infrastructure.models.media_usage import MediaUsage as MediaUsageRow

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _db_available() -> bool:
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
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
        pytest.skip("PostgreSQL 未可用，跳过媒体计量集成测试")
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    async with engine.begin() as conn:
        from conftest import reset_baseline_schema

        await reset_baseline_schema(conn)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            from conftest import drop_baseline_schema

            await drop_baseline_schema(conn)
        await engine.dispose()


async def _new_actor(factory, name: str = "媒体计量学校"):
    from conftest import create_actor

    return await create_actor(factory, name=name)


async def _rows(factory, org_id):
    async with factory() as session:
        stmt = select(MediaUsageRow).where(MediaUsageRow.org_id == org_id)
        return (await session.execute(stmt)).scalars().all()


async def test_recorder_writes_media_usage_row(factory) -> None:
    actor = await _new_actor(factory)
    recorder = MediaUsageRecorder(session_factory=factory)
    await recorder.record(
        MediaUsage(
            kind=MediaKind.IMAGE,
            provider="test-provider",
            model="test-model",
            units=1,
            size=4096,
            org_id=actor.org_id,
            user_id=actor.user_id,
            script_id=7,
            session_id=uuid.uuid4(),
            meta={"width": 1024},
        )
    )
    rows = await _rows(factory, actor.org_id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.kind, row.provider, row.model, row.units, row.size) == (
        "image",
        "test-provider",
        "test-model",
        1,
        4096,
    )
    assert row.script_id == 7
    assert row.meta["width"] == 1024


async def test_recorder_skips_without_owner(factory) -> None:
    """缺 org/user 归属时不落库、不抛错（无法归属的调用不应产生脏行）。"""
    async with factory() as session:
        before = len((await session.execute(select(MediaUsageRow))).scalars().all())
    recorder = MediaUsageRecorder(session_factory=factory)
    await recorder.record(MediaUsage(kind=MediaKind.IMAGE, provider="p"))
    async with factory() as session:
        after = len((await session.execute(select(MediaUsageRow))).scalars().all())
    assert after == before


async def test_recorder_failure_does_not_raise() -> None:
    """计量失败绝不阻断主流程（best-effort）。"""

    class _BoomFactory:
        def __call__(self):  # noqa: ANN204
            raise RuntimeError("db down")

    recorder = MediaUsageRecorder(session_factory=_BoomFactory())
    await recorder.record(
        MediaUsage(
            kind=MediaKind.TTS,
            provider="p",
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )
    )


async def test_quota_blocks_before_paid_call(factory) -> None:
    """配额在付费调用前生效：check+consume 达到上限后 check 为 False。"""
    actor = await _new_actor(factory)
    quota = MediaQuotaService(session_factory=factory, limits={MediaKind.IMAGE: 2})

    assert await quota.check(org_id=actor.org_id, kind=MediaKind.IMAGE) is True
    await quota.consume(org_id=actor.org_id, kind=MediaKind.IMAGE)
    assert await quota.check(org_id=actor.org_id, kind=MediaKind.IMAGE) is True
    await quota.consume(org_id=actor.org_id, kind=MediaKind.IMAGE)
    assert await quota.check(org_id=actor.org_id, kind=MediaKind.IMAGE) is False


async def test_quota_seeds_from_existing_usage(factory) -> None:
    """进程启动后按 media_usage 已用量种子，重启不丢已消费额度。"""
    actor = await _new_actor(factory)
    recorder = MediaUsageRecorder(session_factory=factory)
    await recorder.record(
        MediaUsage(
            kind=MediaKind.IMAGE,
            provider="p",
            units=3,
            org_id=actor.org_id,
            user_id=actor.user_id,
        )
    )
    quota = MediaQuotaService(session_factory=factory, limits={MediaKind.IMAGE: 3})
    assert await quota.check(org_id=actor.org_id, kind=MediaKind.IMAGE) is False
    assert (
        await quota.check(org_id=actor.org_id, kind=MediaKind.IMAGE, units=0) is True
    )


async def test_quota_unlimited_when_budget_zero(factory) -> None:
    actor = await _new_actor(factory)
    quota = MediaQuotaService(session_factory=factory, limits={MediaKind.IMAGE: 0})
    assert (
        await quota.check(org_id=actor.org_id, kind=MediaKind.IMAGE, units=999) is True
    )


async def test_quota_try_acquire_is_atomic(factory) -> None:
    """并发 try_acquire 不会超额（锁内 seed+check+预扣）。"""
    actor = await _new_actor(factory)
    quota = MediaQuotaService(session_factory=factory, limits={MediaKind.IMAGE: 2})
    results = await asyncio.gather(
        *[
            quota.try_acquire(org_id=actor.org_id, kind=MediaKind.IMAGE)
            for _ in range(10)
        ]
    )
    assert sum(results) == 2


async def test_quota_tts_budget_is_character_units(factory) -> None:
    """TTS 预算按字符（units）计，而非调用次数。"""
    actor = await _new_actor(factory)
    quota = MediaQuotaService(session_factory=factory, limits={MediaKind.TTS: 1000})
    assert (
        await quota.try_acquire(org_id=actor.org_id, kind=MediaKind.TTS, units=600)
        is True
    )
    assert (
        await quota.try_acquire(org_id=actor.org_id, kind=MediaKind.TTS, units=500)
        is False
    )


async def test_quota_consume_unlimited_is_noop(factory) -> None:
    actor = await _new_actor(factory)
    quota = MediaQuotaService(session_factory=factory, limits={MediaKind.IMAGE: 0})
    await quota.consume(org_id=actor.org_id, kind=MediaKind.IMAGE, units=100)
    assert quota._counts.get((actor.org_id, MediaKind.IMAGE), 0) == 0
