"""分支回溯原子持久化测试（issue #8 验收标准 5：快照与 branch/head 原子提交）。

依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.db.branch import commit_rollback_branch
from app.db.event_store import EVENTS_SCHEMA_VERSION, main_branch_id
from app.models.event import GameEventRecord
from app.models.event_branch import EventBranchRecord
from app.models.session import Session
from app.models.snapshot import Snapshot

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_SID = uuid.uuid4()
_CMD = uuid.uuid4()
_BRANCH_MAIN = main_branch_id(str(_SID))
_seed: dict[str, int] = {}


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

    actor = await create_actor(f, name="分支测试学校")
    # FK 安全顺序播种：先 sessions，再 event_branches，再 events（避免 ORM 无
    # relationship 时按类名字典序 flush 造成父行未落库）
    async with f() as s:
        s.add(Session(id=_SID, org_id=actor.org_id, owner_user_id=actor.user_id))
        await s.commit()
    async with f() as s:
        s.add(EventBranchRecord(id=_BRANCH_MAIN, session_id=_SID, root_sequence=0))
        await s.commit()
    async with f() as s:
        event = GameEventRecord(
            session_id=_SID,
            branch_id=_BRANCH_MAIN,
            sequence=3,
            event_type="player_action",
            payload={"event_id": 3},
            schema_version=EVENTS_SCHEMA_VERSION,
        )
        s.add(event)
        await s.commit()
        _seed["head_event_id"] = event.id
    try:
        yield f
    finally:
        async with engine.begin() as conn:
            from conftest import drop_baseline_schema

            await drop_baseline_schema(conn)
        await engine.dispose()


async def _counts(factory) -> tuple[int, int]:
    async with factory() as s:
        branches = (await s.execute(select(EventBranchRecord))).scalars().all()
        snaps = (await s.execute(select(Snapshot))).scalars().all()
    return len(branches), len(snaps)


async def test_rollback_branch_atomic_commit(factory):
    """新建分支 + 快照 + head/version 推进三者同事务提交。"""
    branches_before, snaps_before = await _counts(factory)

    async with factory() as s:
        new_branch = await commit_rollback_branch(
            s,
            session_id=_SID,
            parent_branch_id=_BRANCH_MAIN,
            root_sequence=1,
            head_event_id=_seed["head_event_id"],
            expected_version=0,
            created_by_command_id=_CMD,
            snapshot={
                "state_machine": "stage2_reenacting",
                "character_memories": {"父亲": []},
            },
        )

    async with factory() as s:
        sess = (
            await s.execute(select(Session).where(Session.id == _SID))
        ).scalar_one()
        branch = (
            await s.execute(
                select(EventBranchRecord).where(EventBranchRecord.id == new_branch)
            )
        ).scalar_one()
        snaps = (await s.execute(select(Snapshot))).scalars().all()

    assert sess.active_branch_id == new_branch
    assert sess.head_event_id == _seed["head_event_id"]
    assert sess.version == 1
    assert branch.parent_branch_id == _BRANCH_MAIN
    assert branch.root_sequence == 1
    assert branch.created_by_command_id == _CMD
    assert len(snaps) == snaps_before + 1
    assert snaps[-1].state_machine == "stage2_reenacting"


async def test_rollback_branch_version_conflict_leaves_no_partial_state(factory):
    """乐观锁版本冲突：整事务回滚，不留下半条分支/快照。"""
    branches_before, snaps_before = await _counts(factory)

    with pytest.raises(RuntimeError):
        async with factory() as s:
            await commit_rollback_branch(
                s,
                session_id=_SID,
                parent_branch_id=_BRANCH_MAIN,
                root_sequence=1,
                head_event_id=_seed["head_event_id"],
                expected_version=999,  # 必然过期的版本号
                created_by_command_id=_CMD,
            )

    branches_after, snaps_after = await _counts(factory)
    async with factory() as s:
        sess = (
            await s.execute(select(Session).where(Session.id == _SID))
        ).scalar_one()

    assert branches_after == branches_before, "版本冲突不得留下半条分支行"
    assert snaps_after == snaps_before, "版本冲突不得留下快照行"
    assert sess.version == 1, "head/version 不得被陈旧写覆盖"
