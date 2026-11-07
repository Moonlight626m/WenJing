"""离线 tick 的持久化语义（M7 §B6）：claim-first 幂等闸。

依赖真实 Postgres；未连库整包 skip（与 test_db_event_store 同口径）。
不跑完整 Stage3 会话——只钉住 `SessionStore.commit(claim=...)` 与
`SessionApplication` 的 tick 索引/时间查询。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401  # 注册元数据
from app.contracts.enums import UserRole
from app.domain.game.event import EVENT_WORLD_FACT
from app.infrastructure.config import DEFAULT_DATABASE_URL
from app.infrastructure.db.event_store import PersistentEventStore
from app.infrastructure.llm.fake import DeterministicAgentLLM
from app.infrastructure.models.command import CommandRecord
from app.infrastructure.models.event import GameEventRecord
from app.infrastructure.models.event_branch import EventBranchRecord
from app.infrastructure.models.org import Org
from app.infrastructure.models.session import Session as SessionRecord
from app.infrastructure.models.session_tick import SessionTick
from app.infrastructure.models.snapshot import Snapshot
from app.infrastructure.models.user import User
from app.services.session_runtime import SessionApplication
from app.services.session_store import SessionStore

_DB_URL = os.environ.get("WENJING_DATABASE_URL", DEFAULT_DATABASE_URL)


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
async def db_factory():
    if not await _db_available():
        pytest.skip("PostgreSQL 不可用：先 make db-up && make migrate")
    from conftest import drop_baseline_schema, reset_baseline_schema

    engine = create_async_engine(_DB_URL)
    # 与 conftest 的集成测试口径一致：进时重置基线 schema、出时交还空库
    # （连同 alembic_version 一起清，避免「版本戳在、表已清」让迁移变 no-op）
    async with engine.begin() as conn:
        await reset_baseline_schema(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await drop_baseline_schema(conn)
    await engine.dispose()


@pytest.fixture
async def session_row(db_factory):
    """建 org/user/session 三元组，测试后按 FK 顺序清理。"""
    async with db_factory() as s:
        org = Org(name=f"tick-{uuid.uuid4().hex[:8]}")
        s.add(org)
        await s.flush()
        user = User(
            id=uuid.uuid4(),
            org_id=org.id,
            role=UserRole.TEACHER.value,
            email=f"{uuid.uuid4().hex[:8]}@tick.local",
            nickname="tick",
            password_hash="unused",
        )
        s.add(user)
        await s.flush()
        row = SessionRecord(
            id=uuid.uuid4(),
            org_id=org.id,
            owner_user_id=user.id,
            current_stage="stage3_extending",
            script_id=None,
            status="active",
        )
        s.add(row)
        await s.commit()
    yield row
    async with db_factory() as s:
        for model in (SessionTick, Snapshot, CommandRecord, GameEventRecord, EventBranchRecord):
            await s.execute(delete(model).where(model.session_id == row.id))
        await s.execute(delete(SessionRecord).where(SessionRecord.id == row.id))
        await s.execute(delete(User).where(User.id == row.owner_user_id))
        await s.execute(delete(Org).where(Org.id == row.org_id))
        await s.commit()


def _claim(session_id: uuid.UUID, tick_index: int):
    async def claim(s) -> bool:
        if await s.get(SessionTick, (session_id, tick_index)) is not None:
            return False
        s.add(SessionTick(session_id=session_id, tick_index=tick_index))
        return True

    return claim


async def test_claim_is_first_wins_and_second_commit_is_noop(db_factory, session_row):
    store = SessionStore(session_factory=db_factory)
    sid = session_row.id

    first = PersistentEventStore()
    first.append(EVENT_WORLD_FACT, {"fact_id": "a", "text": "第一次"}, session_id=str(sid))
    assert await store.commit(
        session_id=sid,
        store=first,
        stage="stage3_extending",
        expected_version=None,
        op="offline_tick",
        claim=_claim(sid, 1),
    ) is True

    second = PersistentEventStore()
    second.append(EVENT_WORLD_FACT, {"fact_id": "b", "text": "不该落库"}, session_id=str(sid))
    assert await store.commit(
        session_id=sid,
        store=second,
        stage="stage3_extending",
        expected_version=None,
        op="offline_tick",
        claim=_claim(sid, 1),
    ) is False

    async with db_factory() as s:
        rows = (
            await s.execute(
                select(GameEventRecord)
                .where(GameEventRecord.session_id == sid)
                .order_by(GameEventRecord.id)
            )
        ).scalars()
        facts = [r.payload.get("fact_id") for r in rows]
    assert facts == ["a"]  # 第二个 tick 的事实整体回滚
    async with db_factory() as s:
        assert await s.get(SessionTick, (sid, 1)) is not None


async def test_tick_index_and_last_at_helpers(db_factory, session_row):
    app = SessionApplication(
        session_factory=db_factory, agent_llm=DeterministicAgentLLM()
    )
    sid = session_row.id
    assert await app._next_tick_index(sid) == 1
    assert await app._last_tick_at(sid) is None

    async with db_factory() as s:
        s.add(SessionTick(session_id=sid, tick_index=1))
        s.add(SessionTick(session_id=sid, tick_index=2))
        await s.commit()

    assert await app._next_tick_index(sid) == 3
    assert await app._last_tick_at(sid) is not None


async def test_non_stage3_session_does_not_tick(db_factory, session_row):
    app = SessionApplication(
        session_factory=db_factory, agent_llm=DeterministicAgentLLM()
    )
    async with db_factory() as s:
        row = await s.get(SessionRecord, session_row.id)
        assert row is not None
        row.current_stage = "stage2_reenacting"
        await s.commit()

    await app._run_offline_ticks(session_row.id, row)

    assert await app._next_tick_index(session_row.id) == 1  # 没有认领任何 tick
