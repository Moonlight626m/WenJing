"""SessionApplication 集成测试（issue #5 验收标准，真实 PG + fake adapters）。

覆盖：从剧本建可玩会话 → 命令受理（单事务持久化 + 幂等）→ 回溯分支 →
进程重启恢复（restore_active_branch + 快照重放）。
依赖真实 PostgreSQL；不可用时 skip。

注：#19 起剧本由剧本库生成，会话经 `script_id` 引用；util 见 `conftest`。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.access import Actor
from app.contracts.commands import CommandKind, PlayerCommand
from app.errx import Error as WJError
from app.session.application import SessionApplication

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
        pytest.skip("PostgreSQL 未可用，跳过 SessionApplication 集成测试")
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


@pytest.fixture(scope="module")
async def actor(factory) -> Actor:
    from conftest import create_actor

    return await create_actor(factory, name="应用测试学校")


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


async def test_full_vertical_flow(factory, actor):
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    status = await app.get_status(sid, actor=actor)
    assert status.stage == "stage1_complete"
    assert status.playable_roles
    role = status.playable_roles[0]

    # 选角 → RuntimeUpdate 投影
    upd = await app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    assert upd.state.stage.value == "stage2_reenacting"
    assert upd.new_events
    assert upd.state.active_interaction is not None

    # 输入命令推进
    upd2 = await app.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )
    assert upd2.new_events

    # 会话行 head/version/active_branch 已推进
    status = await app.get_status(sid, actor=actor)
    assert status.head_sequence > 0
    assert status.selected_role == role


async def test_command_idempotent_via_commands_table(factory, actor):
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]

    cmd = _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role})
    first = await app.submit_command(sid, cmd, actor=actor)
    events_after_first = len(first.new_events)

    # 同 command_id 重发：不重复执行、不产生新事件
    second = await app.submit_command(sid, cmd, actor=actor)
    assert second.new_events == []
    assert second.state.stage == first.state.stage
    _ = events_after_first


async def test_rollback_switches_branch_atomically(factory, actor):
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]
    await app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    await app.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )

    upd = await app.submit_command(
        sid, _cmd(sid, CommandKind.ROLLBACK_TO_EVENT, {"target_sequence": 3}), actor=actor
    )
    assert upd.new_events  # rollback 事件 + 重新推进
    status = await app.get_status(sid, actor=actor)
    assert status.head_sequence > 0


async def test_restore_after_restart_replays_state(factory, actor):
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]
    upd1 = await app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    stage_before = upd1.state.stage.value

    # 模拟进程重启：清空进程内运行时，命令触发 DB 重建
    app._runtimes.clear()
    upd2 = await app.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )
    assert upd2.state.stage.value == stage_before  # 从恢复点继续推进
    assert upd2.state.active_interaction is not None
    assert upd2.state.plot_context["player_role"] == role


async def test_initialize_without_script_fails_cleanly(factory, actor):
    from app.agents.fake_llm import DeterministicAgentLLM

    app = SessionApplication(
        session_factory=factory, agent_llm=DeterministicAgentLLM()
    )
    sid = (
        await app.create_session(org_id=actor.org_id, owner_user_id=actor.user_id)
    ).session_id
    with pytest.raises(WJError):
        await app.initialize_session(sid, actor)


async def test_commands_on_unknown_session_rejected(factory, actor):
    from app.agents.fake_llm import DeterministicAgentLLM

    app = SessionApplication(
        session_factory=factory, agent_llm=DeterministicAgentLLM()
    )
    ghost = uuid.uuid4()
    with pytest.raises(WJError):
        await app.submit_command(
            ghost, _cmd(ghost, CommandKind.EXIT_GAME), actor=actor
        )
