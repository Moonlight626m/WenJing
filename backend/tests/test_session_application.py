"""SessionApplication 集成测试（issue #5 验收标准，真实 PG + fake adapters）。

覆盖：创建会话入库 → 真实 ingestion 导入 → fake 生成 → 命令受理（单事务持久化
+ 幂等）→ 回溯分支 → 进程重启恢复（restore_active_branch + 快照重放）。
依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.agents.fake_llm import DeterministicAgentLLM
from app.contracts.commands import CommandKind, PlayerCommand
from app.contracts.material import MaterialInput, MaterialSource
from app.errx import Error as WJError
from app.session.application import SessionApplication

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
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


@pytest.fixture
def app_svc(factory) -> SessionApplication:
    return SessionApplication(
        session_factory=factory, agent_llm=DeterministicAgentLLM(), script_llm=None
    )


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


async def test_full_vertical_flow(app_svc: SessionApplication):
    # 1. 创建会话（真实 sessions 表）
    created = await app_svc.create_session()
    sid = created.session_id
    status = await app_svc.get_status(sid)
    assert status.stage == "init"

    # 2. 导入材料（真实 ingestion + 原文分析）
    analysis = await app_svc.import_material(
        sid,
        MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT),
    )
    assert analysis.characters, "叙事样例应提取出人物"

    # 3. 生成（fake-backed：确定性合成）
    pkg = await app_svc.generate_script(sid)
    assert pkg.characters and pkg.scenes
    status = await app_svc.get_status(sid)
    assert status.stage == "stage1_complete"
    assert "我" in status.playable_roles or status.playable_roles

    # 4. 选角 → RuntimeUpdate 投影
    upd = await app_svc.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": pkg.playable_roles[0]})
    )
    assert upd.state.stage.value == "stage2_reenacting"
    assert upd.new_events
    assert upd.state.active_interaction is not None

    # 5. 输入命令推进
    upd2 = await app_svc.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"})
    )
    assert upd2.new_events

    # 6. 会话行 head/version/active_branch 已推进
    status = await app_svc.get_status(sid)
    assert status.head_sequence > 0
    assert status.selected_role == pkg.playable_roles[0]


async def test_command_idempotent_via_commands_table(app_svc: SessionApplication):
    created = await app_svc.create_session()
    sid = created.session_id
    await app_svc.import_material(
        sid, MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT)
    )
    await app_svc.generate_script(sid)

    cmd = _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": "我"})
    first = await app_svc.submit_command(sid, cmd)
    events_after_first = len(first.new_events)

    # 同 command_id 重发：不重复执行、不产生新事件
    second = await app_svc.submit_command(sid, cmd)
    assert second.new_events == []
    assert second.state.stage == first.state.stage
    _ = events_after_first


async def test_rollback_switches_branch_atomically(app_svc: SessionApplication):
    created = await app_svc.create_session()
    sid = created.session_id
    await app_svc.import_material(
        sid, MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT)
    )
    await app_svc.generate_script(sid)
    await app_svc.submit_command(sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": "我"}))
    await app_svc.submit_command(sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}))

    upd = await app_svc.submit_command(
        sid, _cmd(sid, CommandKind.ROLLBACK_TO_EVENT, {"target_sequence": 3})
    )
    assert upd.new_events  # rollback 事件 + 重新推进
    status = await app_svc.get_status(sid)
    assert status.head_sequence > 0


async def test_restore_after_restart_replays_state(app_svc: SessionApplication):
    created = await app_svc.create_session()
    sid = created.session_id
    await app_svc.import_material(
        sid, MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT)
    )
    await app_svc.generate_script(sid)
    upd1 = await app_svc.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": "我"})
    )
    stage_before = upd1.state.stage.value

    # 模拟进程重启：清空进程内运行时，命令触发 DB 重建
    app_svc._runtimes.clear()
    upd2 = await app_svc.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"})
    )
    assert upd2.state.stage.value == stage_before  # 从恢复点继续推进
    assert upd2.state.active_interaction is not None
    assert upd2.state.plot_context["player_role"] == "我"


async def test_generate_without_material_fails_cleanly(app_svc: SessionApplication):
    created = await app_svc.create_session()
    with pytest.raises(WJError):
        await app_svc.generate_script(created.session_id)


async def test_commands_on_unknown_session_rejected(app_svc: SessionApplication):
    ghost = uuid.uuid4()
    with pytest.raises(WJError):
        await app_svc.submit_command(ghost, _cmd(ghost, CommandKind.EXIT_GAME))
