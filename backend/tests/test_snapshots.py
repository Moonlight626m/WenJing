"""快照坐标与回溯页（design play-through-redesign §C1/C2，M8）。

覆盖：
- 每个快照带 `(branch_id, sequence, label, kind)`，`sessions.head_sequence` 是
  真正的分支内进度序号（不是全局事件行 id）；
- 回溯命令的两种坐标：`target_event_id`（UUID）优先，`target_sequence` 兼容；
- 按目标选快照：回溯恢复只重放到目标之前（目标之后的事件不再重放）；
- 回溯页的分支视图：活动分支可回溯，旧分支只读可审计。

依赖真实 PostgreSQL；未连库整包 skip（与 test_session_application 同口径）。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401  # 注册元数据
from app.contracts.commands import CommandKind, PlayerCommand
from app.domain.game.game_runtime import GameRuntime
from app.infrastructure.config import DEFAULT_DATABASE_URL
from app.infrastructure.errx import Error as WJError
from app.infrastructure.models.session import Session as SessionRecord
from app.infrastructure.models.snapshot import Snapshot
from app.services.session_runtime import SessionApplication
from app.services.session_store import SNAPSHOT_KIND_COMMAND, SNAPSHOT_KIND_ROLLBACK

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
async def factory():
    if not await _db_available():
        pytest.skip("PostgreSQL 未可用，跳过快照集成测试")
    from conftest import drop_baseline_schema, reset_baseline_schema

    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    async with engine.begin() as conn:
        await reset_baseline_schema(conn)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await drop_baseline_schema(conn)
    await engine.dispose()


@pytest.fixture(scope="module")
async def actor(factory):
    from conftest import create_actor

    return await create_actor(factory, name="快照测试学校")


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


async def _play(app: SessionApplication, sid: uuid.UUID, actor, steps: int = 2) -> None:
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]
    await app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    for _ in range(steps):
        await app.submit_command(
            sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
        )


def _rollbackable(entries):
    return [
        e for e in entries if e.kind.value == "narrative" and e.rollbackable
    ]


async def test_snapshots_carry_branch_coordinates_and_labels(factory, actor):
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    await _play(app, sid, actor, steps=2)

    timeline = await app.get_timeline(sid, actor=actor)
    status = await app.get_status(sid, actor=actor)
    # head_sequence 是分支内序号：与时间线尾部一致，而不是全局事件行 id
    assert status.head_sequence == timeline.head_sequence > 0
    assert status.active_branch_id == timeline.branch_id

    async with factory() as s:
        row = await s.get(SessionRecord, sid)
        assert row is not None
        assert row.head_sequence == status.head_sequence
        assert row.active_branch_id == status.active_branch_id
        snaps = (
            (
                await s.execute(
                    select(Snapshot)
                    .where(Snapshot.session_id == sid)
                    .order_by(Snapshot.id.desc())
                )
            )
            .scalars()
            .all()
        )
    assert snaps, "每条命令都应落一个存档点"
    newest = snaps[0]
    assert newest.branch_id == status.active_branch_id
    assert newest.sequence == status.head_sequence
    assert newest.kind == SNAPSHOT_KIND_COMMAND
    assert newest.label

    # 回溯页的存档点来自同一批快照坐标
    assert timeline.save_points
    last = timeline.save_points[-1]
    assert last.sequence == timeline.head_sequence
    assert last.branch_id == status.active_branch_id
    assert last.event_id  # 契约 UUID，可直接当回溯坐标


async def test_snapshot_retention_keeps_recent_per_branch(factory, actor, monkeypatch):
    """快照是缓存：每分支只留最近 K 个命令快照，超出部分删掉。"""
    from conftest import make_playable_session

    from app.services import session_store as store_mod

    monkeypatch.setattr(store_mod, "SNAPSHOT_KEEP_PER_BRANCH", 1)

    app, sid = await make_playable_session(factory, actor)
    await _play(app, sid, actor, steps=2)
    status = await app.get_status(sid, actor=actor)

    async with factory() as s:
        rows = (
            (
                await s.execute(
                    select(Snapshot)
                    .where(Snapshot.session_id == sid)
                    .order_by(Snapshot.id)
                )
            )
            .scalars()
            .all()
        )
    command_rows = [row for row in rows if row.kind != SNAPSHOT_KIND_ROLLBACK]
    assert command_rows
    assert all(
        sum(1 for row in command_rows if row.branch_id == branch) <= 1
        for branch in {row.branch_id for row in command_rows}
    )
    assert command_rows[-1].sequence == status.head_sequence


async def test_rollback_snapshots_are_never_pruned(factory, actor, monkeypatch):
    """回溯快照是审计坐标，不受保留策略影响。"""
    from conftest import make_playable_session

    from app.services import session_store as store_mod

    monkeypatch.setattr(store_mod, "SNAPSHOT_KEEP_PER_BRANCH", 1)

    app, sid = await make_playable_session(factory, actor)
    await _play(app, sid, actor, steps=2)
    timeline = await app.get_timeline(sid, actor=actor)
    target = _rollbackable(timeline.entries)[0]
    await app.submit_command(
        sid,
        _cmd(sid, CommandKind.ROLLBACK_TO_EVENT, {"target_event_id": str(target.event_id)}),
        actor=actor,
    )
    await app.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )

    async with factory() as s:
        rows = (
            (
                await s.execute(
                    select(Snapshot).where(Snapshot.session_id == sid)
                )
            )
            .scalars()
            .all()
        )
    assert any(row.kind == SNAPSHOT_KIND_ROLLBACK for row in rows)


async def test_rollback_by_event_uuid_and_read_only_branch_view(factory, actor):
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    await _play(app, sid, actor, steps=2)

    timeline = await app.get_timeline(sid, actor=actor)
    targets = _rollbackable(timeline.entries)
    assert len(targets) >= 2
    target = targets[0]  # 最早的可回溯拍
    assert timeline.can_rollback
    assert target.branch_id == timeline.branch_id

    await app.submit_command(
        sid,
        _cmd(sid, CommandKind.ROLLBACK_TO_EVENT, {"target_event_id": str(target.event_id)}),
        actor=actor,
    )

    after = await app.get_timeline(sid, actor=actor)
    assert after.branch_id != timeline.branch_id
    assert any(e.kind.value == "system" and "已回溯" in e.text for e in after.entries)
    assert len(after.branches) >= 2
    old = next(b for b in after.branches if not b.is_active)
    assert old.branch_id == timeline.branch_id

    # 旧分支只读：进度原样保留（回溯不往旧分支追加任何事件），但不能继续回溯
    view = await app.get_timeline(sid, actor=actor, branch_id=old.branch_id)
    assert view.read_only is True
    assert view.can_rollback is False
    assert all(not e.rollbackable for e in view.entries)
    assert [(e.sequence, e.text) for e in view.entries] == [
        (e.sequence, e.text) for e in timeline.entries
    ]

    with pytest.raises(WJError):
        await app.get_timeline(sid, actor=actor, branch_id=uuid.uuid4())


async def test_rollback_restores_only_up_to_the_target(factory, actor, monkeypatch):
    """按目标选快照：恢复重放止于目标，目标之后的事件不再重放（M8 §C1）。"""
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    await _play(app, sid, actor, steps=2)
    timeline = await app.get_timeline(sid, actor=actor)
    targets = _rollbackable(timeline.entries)
    # 取较晚的一拍：它前面一定已有别的命令留下的存档点，才测得出「按目标选快照」
    target = targets[-1]
    assert target.sequence < timeline.head_sequence

    calls: list[tuple[bool, int]] = []
    original = GameRuntime.replay_from

    def spy(self, snapshot_state, events):
        calls.append((snapshot_state is not None, len(events)))
        return original(self, snapshot_state, events)

    monkeypatch.setattr(GameRuntime, "replay_from", spy)
    await app.submit_command(
        sid,
        _cmd(sid, CommandKind.ROLLBACK_TO_EVENT, {"target_event_id": str(target.event_id)}),
        actor=actor,
    )

    # 恢复路径（带快照基线的重放）只重放到目标：长度不超过目标在路径上的位置
    restore_replays = [length for has_base, length in calls if has_base]
    assert restore_replays
    assert max(restore_replays) <= target.sequence
    # 回溯本身仍按前缀整段重放（事件是唯一权威）
    assert any(not has_base and length > 0 for has_base, length in calls)
