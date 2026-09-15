"""真实核心集成端到端（issue #12，真实 PG + 真实管线 + fake agent LLM）。

以 SessionApplication 为唯一入口跑通：
Stage1 生成 → 选角 → Stage2 至结局 → Stage3（三交互模式）→ 回溯分支 →
重启恢复 → 退出（terminal）→ 终局后命令报错（envelope + error_id）。

生成用确定性合成（真 LLM 路径由 scripts/e2e_real_flow.py 驱动）；
ContentPipeline / GameRuntime / 事件持久化 / 事务边界全部为真实链路。
依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.access import Actor
from app.agents.fake_llm import DeterministicAgentLLM
from app.contracts.commands import CommandKind, PlayerCommand
from app.contracts.material import MaterialInput, MaterialSource
from app.db.event_store import PersistentEventStore, branch_uuid
from app.diagnostics.errors import envelope_for
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
        pytest.skip("PostgreSQL 未可用，跳过 #12 全流程集成测试")
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


def _make_app(factory) -> SessionApplication:
    return SessionApplication(
        session_factory=factory,
        agent_llm=DeterministicAgentLLM(),
        script_llm=None,
    )


@pytest.fixture(scope="module")
async def actor(factory) -> Actor:
    """会话归属所需的领域身份（#18）：一个 org + 一个教师账号。"""
    from conftest import create_actor

    return await create_actor(factory, name="全流程测试学校")


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


async def _active_store(app: SessionApplication, sid: uuid.UUID) -> PersistentEventStore:
    runtime, store = await app._ensure_runtime(sid)
    _ = runtime
    return store


async def _advance_until(
    app: SessionApplication,
    sid: uuid.UUID,
    *,
    actor: Actor,
    kind: CommandKind = CommandKind.CHOOSE_OPTION,
    payload: dict | None = None,
    predicate,
    max_rounds: int = 12,
) -> dict:
    """重复提交选项直到交互点满足 predicate；返回满足时的 RuntimeUpdate.state。"""
    for _ in range(max_rounds):
        upd = await app.submit_command(
            sid, _cmd(sid, kind, payload or {"option_id": "0"}), actor=actor
        )
        ix = upd.state.active_interaction
        if ix is not None and predicate(ix):
            return upd
        if upd.terminal:
            raise AssertionError("流程提前终止")
    raise AssertionError("推进超过上限仍未到达目标交互点")


async def test_stage1_to_stage3_full_flow(factory, actor):
    app = _make_app(factory)
    sid = (
        await app.create_session(org_id=actor.org_id, owner_user_id=actor.user_id)
    ).session_id

    # 导入（真实 ContentPipeline）
    analysis = await app.import_material(
        sid,
        MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT),
        actor=actor,
    )
    assert analysis.genre.is_supported and analysis.characters

    # 生成（确定性合成）+ 进度记录
    pkg = await app.generate_script(sid, actor=actor)
    status = await app.get_status(sid, actor=actor)
    assert status.stage == "stage1_complete"
    assert status.generation is not None and status.generation.status == "succeeded"
    phases = {p.name: p.state for p in status.generation.phases}
    assert phases["genre"] == "succeeded" and phases["verify"] == "succeeded"

    # 选角 → Stage2（模式 A：options）
    upd = await app.submit_command(
        sid,
        _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": pkg.playable_roles[0]}),
        actor=actor,
    )
    assert upd.state.stage.value == "stage2_reenacting"
    assert upd.state.active_interaction is not None
    assert upd.state.active_interaction.mode.value == "options"
    assert upd.state.allowed_commands()  # 非空

    # Stage2 推进到课文结局确认点
    upd = await _advance_until(
        app, sid, actor=actor, predicate=lambda ix: "结局" in ix.prompt
    )
    assert upd.state.stage.value == "stage2_reenacting"
    option_labels = [o.label for o in upd.state.active_interaction.options]
    assert any("续写" in label for label in option_labels), option_labels

    # 选择续写 → stage2_complete → enter_stage3
    upd = await app.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )
    assert upd.state.stage.value == "stage2_complete"
    upd = await app.submit_command(
        sid, _cmd(sid, CommandKind.ENTER_STAGE3), actor=actor
    )
    assert upd.state.stage.value == "stage3_extending"

    # Stage3（模式 C：options_with_fallback）+ 自由输入（模式 B）
    assert upd.state.active_interaction is not None
    assert upd.state.active_interaction.mode.value == "options_with_fallback"
    upd = await app.submit_command(
        sid,
        _cmd(sid, CommandKind.FREE_INPUT, {"text": "我想先去买药再回家"}),
        actor=actor,
    )
    assert upd.state.stage.value == "stage3_extending"

    # 回溯：回到活动分支早期（保留历史、新分支）
    store = await _active_store(app, sid)
    before_events = len(store.active_events())
    before_branch = branch_uuid(sid, store.active_branch_id)
    upd = await app.submit_command(
        sid, _cmd(sid, CommandKind.ROLLBACK_TO_EVENT, {"target_sequence": 3}),
        actor=actor,
    )
    store = await _active_store(app, sid)
    after_branch = branch_uuid(sid, store.active_branch_id)
    assert after_branch != before_branch, "回溯必须切到新分支"
    # 既定语义（#5）：回溯保留当前阶段，从恢复点继续推进
    assert upd.state.stage.value == "stage3_extending"
    assert upd.state.active_interaction is not None
    # 历史保留：事件总数只增不减（旧分支事件仍在库中）
    all_events = await _count_all_events(factory, sid)
    assert all_events >= before_events

    # 重启恢复：全新应用实例从 DB 重建，随后命令继续可用
    revived = _make_app(factory)
    upd = await revived.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )
    assert upd.state.active_interaction is not None or upd.terminal
    assert upd.state.stage.value in {
        "stage2_reenacting",
        "stage2_complete",
        "stage3_extending",
    }

    # 退出游戏（terminal）→ 终局后命令报错（envelope + error_id 可对账）
    upd = await revived.submit_command(
        sid, _cmd(sid, CommandKind.EXIT_GAME), actor=actor
    )
    assert upd.terminal
    assert upd.state.stage.value == "ended"
    try:
        await revived.submit_command(
            sid, _cmd(sid, CommandKind.EXIT_GAME), actor=actor
        )
        raise AssertionError("终局后命令应被拒绝")
    except WJError as exc:
        env = envelope_for(exc)
        assert env.code == "SESSION_ENDED"
        assert str(env.error_id), "error_id 必须存在（服务端日志可对账）"
        assert env.message


async def test_import_rejects_garbage_with_envelope(factory, actor):
    app = _make_app(factory)
    sid = (
        await app.create_session(org_id=actor.org_id, owner_user_id=actor.user_id)
    ).session_id
    try:
        # 非叙事体裁（说明文）→ 内容域错误 envelope
        await app.import_material(
            sid,
            MaterialInput(
                source=MaterialSource.PASTE,
                raw_text="地球绕太阳公转。水由氢和氧组成。光速约为每秒三十万公里。",
            ),
            actor=actor,
        )
        raise AssertionError("说明文应被拒绝")
    except WJError as exc:
        env = envelope_for(exc)
        assert env.domain.value == "content"
        assert env.code == "CONTENT_UNSUPPORTED_GENRE"
        assert str(env.error_id)


async def test_generation_progress_failed_keeps_session_clean(factory, actor):
    """未导入材料直接生成 → CNT/SESSION 错误；会话仍可继续导入。"""
    app = _make_app(factory)
    sid = (
        await app.create_session(org_id=actor.org_id, owner_user_id=actor.user_id)
    ).session_id
    try:
        await app.generate_script(sid, actor=actor)
        raise AssertionError("未导入材料生成应失败")
    except WJError as exc:
        assert envelope_for(exc).code in {
            "SESSION_NOT_FOUND",
            "CONTENT_INSUFFICIENT_SOURCE",
        }

    analysis = await app.import_material(
        sid,
        MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT),
        actor=actor,
    )
    assert analysis.characters


async def _count_all_events(factory, sid: uuid.UUID) -> int:
    async with factory() as s:
        rows = await s.execute(
            text("select count(*) from events where session_id = :sid"),
            {"sid": str(sid)},
        )
        return int(rows.scalar_one())
