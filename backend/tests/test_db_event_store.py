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

import app.infrastructure.models  # noqa: F401  # 注册元数据
from app.infrastructure.db.event_store import PersistentEventStore
from app.infrastructure.models.session import Session

S1 = str(uuid4())
S2 = str(uuid4())
S3 = str(uuid4())
S4 = str(uuid4())

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
    from conftest import create_actor

    actor = await create_actor(factory, name="事件存储测试学校")
    # events/commands.material 等表外键 sessions.id：预置测试会话行（带归属）
    async with factory() as session:
        session.add(
            Session(id=uuid.UUID(S1), org_id=actor.org_id, owner_user_id=actor.user_id)
        )
        session.add(
            Session(id=uuid.UUID(S2), org_id=actor.org_id, owner_user_id=actor.user_id)
        )
        session.add(
            Session(id=uuid.UUID(S4), org_id=actor.org_id, owner_user_id=actor.user_id)
        )
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


async def test_scene_assets_derive_after_pg_round_trip(session_factory):
    """#55「重放一致」：经 PG 落库 + `restore_active_branch` 后派生的资产索引与内存态相同。

    这一层差异只在真实持久化路径上暴露：JSONB 往返会给 payload 补 session_id/event_id/
    timestamp 等键，分支整数 id 由 event_branches 行反查重排——内存 EventStore 覆盖不到。
    """
    from app.domain.game.assets import RuntimeAssets

    first, second = str(uuid4()), str(uuid4())
    store = PersistentEventStore()
    store.append("asset_ready", {"scene_key": "scene:1", "asset_id": first}, session_id=S4)
    store.append("plot_advancement", {"summary": "转场"}, session_id=S4)
    # 同一 scene_key 后写覆盖先写；另一 scene_key 取默认 kind
    store.append("asset_ready", {"scene_key": "scene:1", "asset_id": second}, session_id=S4)
    store.append(
        "asset_ready",
        {"scene_key": "scene:2", "asset_id": first, "kind": "avatar"},
        session_id=S4,
    )
    expected = RuntimeAssets.rebuild(store)

    async with session_factory() as session:
        await store.flush(session, S4)

    restored = PersistentEventStore()
    async with session_factory() as session:
        await restored.restore_active_branch(session, S4)

    index = RuntimeAssets.rebuild(restored)
    assert index.by_scene == expected.by_scene
    assert index.current("scene:1").asset_id == uuid.UUID(second)
    assert index.current("scene:2").kind == "avatar"
    assert index.current("scene:missing") is None
