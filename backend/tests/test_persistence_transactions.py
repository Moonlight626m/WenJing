"""事务原子性测试（issue #4 验收标准：commit 前失败不留下部分状态）。

以"命令受理"事务为最小用例（#5 SessionApplication UnitOfWork 的前例）：
一次命令写入 = commands 行 + events 行 + sessions head/version 推进，
三者要么全部落库，要么全部不可见。
另含乐观锁并发保护测试。

依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.db.event_store import EVENTS_SCHEMA_VERSION, main_branch_id
from app.models.command import CommandRecord
from app.models.event import GameEventRecord
from app.models.event_branch import EventBranchRecord
from app.models.session import Session

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_SID = uuid.uuid4()
_CMD = uuid.uuid4()


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
        pytest.skip("PostgreSQL 未可用，跳过 DB 集成测试")
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    async with engine.begin() as conn:
        from conftest import reset_baseline_schema

        await reset_baseline_schema(conn)
    f = async_sessionmaker(engine, expire_on_commit=False)
    from conftest import create_actor

    actor = await create_actor(f, name="事务测试学校")
    # FK 安全顺序播种：分开提交，避免 ORM 无 relationship 时按类名字典序 flush
    async with f() as s:
        s.add(Session(id=_SID, org_id=actor.org_id, owner_user_id=actor.user_id))
        await s.commit()
    async with f() as s:
        s.add(EventBranchRecord(id=main_branch_id(str(_SID)), session_id=_SID))
        await s.commit()
    try:
        yield f
    finally:
        async with engine.begin() as conn:
            from conftest import drop_baseline_schema

            await drop_baseline_schema(conn)
        await engine.dispose()


async def _accept_command(session, *, fail_before_commit: bool = False) -> None:
    """unit-of-work 样板：命令 + 事件 + head/version 同一事务提交。"""
    branch = main_branch_id(str(_SID))
    seq_q = await session.execute(
        select(GameEventRecord.sequence)
        .where(GameEventRecord.branch_id == branch)
        .order_by(GameEventRecord.sequence.desc())
        .limit(1)
    )
    next_seq = int(seq_q.scalar_one_or_none() or -1) + 1
    event_row = GameEventRecord(
        session_id=_SID,
        branch_id=branch,
        sequence=next_seq,
        event_type="role_selected",
        payload={"role": "父亲"},
        schema_version=EVENTS_SCHEMA_VERSION,
        causation_id=_CMD,
        correlation_id=_CMD,
    )
    session.add(event_row)
    session.add(
        CommandRecord(
            command_id=_CMD,
            session_id=_SID,
            kind="select_role",
            payload={"role": "父亲"},
            status="succeeded",
            result_event_id=None,
        )
    )
    # asyncpg 不允许同一连接并发执行：先 flush 插入行，再执行 UPDATE
    await session.flush()
    locked = await session.execute(
        update(Session)
        .where(Session.id == _SID, Session.version == 0)
        .values(head_event_id=next_seq, version=Session.version + 1)
    )
    assert locked.rowcount == 1, "乐观锁版本冲突"
    if fail_before_commit:
        raise RuntimeError("injected failure before commit")
    await session.commit()


async def test_commit_failure_leaves_no_partial_state(factory):
    """commit 前注入失败：commands/events/sessions 三处均无痕迹。"""
    with pytest.raises(RuntimeError):
        async with factory() as s:
            await _accept_command(s, fail_before_commit=True)

    async with factory() as s:
        cmds = (await s.execute(select(CommandRecord))).scalars().all()
        evts = (await s.execute(select(GameEventRecord))).scalars().all()
        sess = (
            await s.execute(select(Session).where(Session.id == _SID))
        ).scalar_one()

    assert cmds == [], "失败事务不得留下命令行"
    assert evts == [], "失败事务不得留下事件行"
    assert sess.version == 0 and sess.head_event_id is None


async def test_successful_accept_persists_all_together(factory):
    async with factory() as s:
        await _accept_command(s)

    async with factory() as s:
        cmd = (await s.execute(select(CommandRecord))).scalar_one()
        evt = (await s.execute(select(GameEventRecord))).scalar_one()
        sess = (
            await s.execute(select(Session).where(Session.id == _SID))
        ).scalar_one()

    assert cmd.status == "succeeded"
    assert evt.causation_id == _CMD
    assert sess.version == 1 and sess.head_event_id == 0
    # 命令与事件同批可见：不存在"有命令没事件"的中间态窗口
    assert evt.sequence >= 0


async def test_optimistic_lock_blocks_concurrent_head_update(factory):
    """version 不匹配的 UPDATE 必须零行命中（每会话单命令并发的守卫）。"""
    stale = update(Session).where(
        Session.id == _SID, Session.version == 0  # 已推进到 1，旧版本应为 0 失败
    ).values(head_event_id=99, version=Session.version + 1)

    async with factory() as s:
        result = await s.execute(stale)
        await s.commit()
    assert result.rowcount == 0

    fresh_ok = update(Session).where(
        Session.id == _SID, Session.version == 1
    ).values(head_event_id=5, version=2)
    async with factory() as s:
        ok = await s.execute(fresh_ok)
        await s.commit()
    assert ok.rowcount == 1


async def test_duplicate_command_id_rejected_by_pk(factory):
    """command_id 主键天然阻断重复受理（幂等的第一道闸）。"""
    from sqlalchemy.exc import IntegrityError

    async with factory() as s:
        s.add(
            CommandRecord(
                command_id=_CMD,
                session_id=_SID,
                kind="select_role",
                payload={},
                status="received",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
