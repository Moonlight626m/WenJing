"""PostgreSQL 持久化事件存储集成测试。

依赖真实 Postgres（`docker compose up -d db` 即可）。未连接 DB 时整包 skip，
因此 `make test` 在有/无 DB 的环境下均应绿。
"""

from __future__ import annotations

import os
import uuid
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  # 注册元数据
from app.db.event_store import PersistentEventStore
from app.models.session import Session

S1 = str(uuid4())
S2 = str(uuid4())
S3 = str(uuid4())

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _db_available() -> bool:
    from sqlalchemy import text

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
async def session_factory():
    if not await _db_available():
        pytest.skip("PostgreSQL 未可用，跳过 DB 集成测试")
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    async with engine.begin() as conn:
        from conftest import reset_baseline_schema

        await reset_baseline_schema(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # events/commands.material 等表外键 sessions.id：预置测试会话行
    async with factory() as session:
        session.add(Session(id=uuid.UUID(S1)))
        session.add(Session(id=uuid.UUID(S2)))
        await session.commit()
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            from conftest import drop_baseline_schema

            await drop_baseline_schema(conn)
        await engine.dispose()


async def test_flush_restore_round_trip(session_factory):
    store = PersistentEventStore()
    store.append("plot_advancement", {"summary": "相遇"}, session_id=S1)
    store.append("player_action", {"type": "text", "text": "问好"}, session_id=S1)
    assert store.has_pending

    async with session_factory() as session:
        n = await store.flush(session, S1)
    assert n == 2
    assert not store.has_pending

    restored = PersistentEventStore()
    async with session_factory() as session:
        events = await restored.restore(session, S1)
    assert len(events) == 2
    assert [e.event_type for e in events] == ["plot_advancement", "player_action"]
    assert events[0].payload["summary"] == "相遇"
    assert events[1].payload["text"] == "问好"


async def test_truncate_after_via_payload_event_id(session_factory):
    store = PersistentEventStore()
    for idx in range(1, 4):
        store.append("system", {"n": idx}, session_id=S2)
    async with session_factory() as session:
        await store.flush(session, S2)

    # 截断到第 2 条之后（删除 event_id > 2 的行）
    async with session_factory() as session:
        deleted = await store.truncate_after(session, 2)
    assert deleted >= 1

    restored = PersistentEventStore()
    async with session_factory() as session:
        events = await restored.restore(session, S2)
    assert [e.payload["n"] for e in events] == [1, 2]


async def test_flush_idempotent_empty(session_factory):
    store = PersistentEventStore()
    async with session_factory() as session:
        assert await store.flush(session, 'not-a-uuid-but-empty-flush') == 0
