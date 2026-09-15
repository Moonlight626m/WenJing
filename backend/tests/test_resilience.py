"""生产化加固：故障注入与可恢复性（issue #13；#19 起生成归剧本库）。

覆盖矩阵：
- LLM 超时/非法结构化输出 → 剧本库生成进度失败、无半合法剧本落库；
- DB 事务失败 → 无部分状态、运行时被丢弃、可安全重试；
- 快照损坏/schema 不兼容 → 可重建、不崩溃；
- 剧本数据不兼容 → 明确 PERSISTENCE 错误；
- 命令重发 → 无重复领域事件；
- 搜索失败 → 降级为纯原文。

依赖真实 PostgreSQL 的用例在不可用时 skip。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.access import Actor
from app.contracts.commands import CommandKind, PlayerCommand
from app.contracts.material import MaterialInput, MaterialSource
from app.db.event_store import PersistentEventStore
from app.diagnostics.errors import envelope_for
from app.errx import Error as WJError
from app.errx import codes, new
from app.models.command import CommandRecord
from app.models.event import GameEventRecord
from app.models.script import Script as ScriptRecord
from app.models.snapshot import Snapshot as SnapshotRecord
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
        pytest.skip("PostgreSQL 未可用，跳过 #13 故障注入集成测试")
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

    return await create_actor(factory, name="韧性测试学校")


class _RaisingLLM:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        raise self._exc


class _GarbageLLM:
    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        return "这不是 JSON，也不是任何合法剧本结构。"


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


async def _generate_with(factory, actor, llm):
    """用指定 LLM 走剧本库生成一个剧本，返回 (library, script_id)。"""
    from conftest import MATERIAL_TEXT

    from app.scripts.service import ScriptLibrary

    library = ScriptLibrary(session_factory=factory, script_llm=llm)
    material = await library.import_material(
        actor, MaterialInput(source=MaterialSource.PASTE, raw_text=MATERIAL_TEXT)
    )
    script = await library.create_script(
        actor, material_id=material.id, name="韧性剧本", description=None
    )
    await library.start_generation(script.id, actor)
    await library.await_generation(script.id)
    return library, script.id


async def _playable(factory, actor) -> tuple[SessionApplication, uuid.UUID]:
    from conftest import make_playable_session

    return await make_playable_session(factory, actor)


async def _count(factory, model) -> int:
    async with factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


# ===== 生成故障（剧本库）=====


async def test_generation_llm_failure_marks_progress_failed(factory, actor):
    llm = _RaisingLLM(new(codes.LLM_CALL_FAILED, extra={"reason": "timeout"}))
    library, script_id = await _generate_with(factory, actor, llm)

    progress = library.progress(script_id)
    assert progress is not None and progress["status"] == "failed"

    # 无部分状态：未落库任何剧本内容
    async with factory() as s:
        row = await s.get(ScriptRecord, script_id)
    assert row is not None and row.script_data is None


async def test_generation_invalid_output_marks_progress_failed(factory, actor):
    library, script_id = await _generate_with(factory, actor, _GarbageLLM())

    progress = library.progress(script_id)
    assert progress is not None and progress["status"] == "failed"
    async with factory() as s:
        row = await s.get(ScriptRecord, script_id)
    assert row is not None and row.script_data is None


async def test_generation_failure_is_retryable(factory, actor):
    llm = _RaisingLLM(new(codes.LLM_CALL_FAILED, extra={"reason": "timeout"}))
    library, script_id = await _generate_with(factory, actor, llm)
    assert library.progress(script_id)["status"] == "failed"

    # 失败可重试：换回确定性合成后重新生成
    library._script_llm = None
    await library.start_generation(script_id, actor)
    await library.await_generation(script_id)
    assert library.progress(script_id)["status"] == "succeeded"
    async with factory() as s:
        row = await s.get(ScriptRecord, script_id)
    assert row.script_data is not None


# ===== DB 事务故障 =====


async def test_db_failure_leaves_no_partial_state_and_can_retry(factory, actor, monkeypatch):
    svc, sid = await _playable(factory, actor)
    role = (await svc.get_status(sid, actor=actor)).playable_roles[0]
    events_before = await _count(factory, GameEventRecord)

    original = PersistentEventStore.write_pending

    async def _boom(self, session, session_id):  # noqa: ANN001
        raise OperationalError("INSERT INTO events ...", {}, Exception("db down"))

    monkeypatch.setattr(PersistentEventStore, "write_pending", _boom)

    cmd = _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role})
    with pytest.raises(WJError) as excinfo:
        await svc.submit_command(sid, cmd, actor=actor)
    assert excinfo.value.code == codes.PER_WRITE_FAILED
    env = envelope_for(excinfo.value)
    assert env.code == "PERSISTENCE_WRITE_FAILED"
    assert env.domain.value == "persistence"
    assert env.retryable is True

    # 无部分状态：命令路径无状态（不驻留运行时），失败命令未落库，无事件被追加
    assert await _count(factory, CommandRecord) == 0
    assert await _count(factory, GameEventRecord) == events_before
    status = await svc.get_status(sid, actor=actor)
    assert status.selected_role is None

    # 恢复 DB 后同 command_id 重试成功（从 DB 权威状态重建）
    monkeypatch.setattr(PersistentEventStore, "write_pending", original)
    upd = await svc.submit_command(sid, cmd, actor=actor)
    assert upd.state.stage.value == "stage2_reenacting"
    assert upd.new_events
    assert await _count(factory, CommandRecord) == 1


# ===== 快照 / schema 兼容性 =====


async def test_corrupt_snapshot_rebuilds_without_crash(factory, actor):
    svc, sid = await _playable(factory, actor)
    role = (await svc.get_status(sid, actor=actor)).playable_roles[0]
    await svc.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )

    async with factory() as s:
        await s.execute(
            update(SnapshotRecord)
            .where(SnapshotRecord.session_id == sid)
            .values(schema_version="0.0.0")
        )
        await s.commit()

    init = await svc.session_init(sid, actor=actor)
    assert init["stage"] == "stage2_reenacting"
    assert init["player_role"] == role


async def test_corrupt_snapshot_payload_rebuilds(factory, actor):
    svc, sid = await _playable(factory, actor)
    role = (await svc.get_status(sid, actor=actor)).playable_roles[0]
    await svc.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )

    async with factory() as s:
        await s.execute(
            update(SnapshotRecord)
            .where(SnapshotRecord.session_id == sid)
            .values(plot_context={"beat_cursor": "not-an-int"})
        )
        await s.commit()

    init = await svc.session_init(sid, actor=actor)
    assert init["stage"] == "stage2_reenacting"


async def test_incompatible_script_schema_returns_clear_error(factory, actor):
    svc, sid = await _playable(factory, actor)

    async with factory() as s:
        await s.execute(
            update(ScriptRecord)
            .where(ScriptRecord.id == (await _session_script_id(factory, sid)))
            .values(script_data={"broken": True})
        )
        await s.commit()

    with pytest.raises(WJError) as excinfo:
        await svc.session_init(sid, actor=actor)
    assert excinfo.value.code == codes.PER_INCOMPATIBLE_SCHEMA
    assert envelope_for(excinfo.value).code == "PERSISTENCE_INCOMPATIBLE_SCHEMA"


async def _session_script_id(factory, sid: uuid.UUID) -> int:
    from app.models.session import Session as SessionRecord

    async with factory() as s:
        return int((await s.get(SessionRecord, sid)).script_id)


# ===== 幂等 / 搜索降级 =====


async def test_command_resend_no_duplicate_domain_events(factory, actor):
    svc, sid = await _playable(factory, actor)
    role = (await svc.get_status(sid, actor=actor)).playable_roles[0]

    before = await _count(factory, GameEventRecord)
    cmd = _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role})
    first = await svc.submit_command(sid, cmd, actor=actor)
    after_first = await _count(factory, GameEventRecord)
    assert after_first > before

    second = await svc.submit_command(sid, cmd, actor=actor)
    assert second.new_events == []
    assert await _count(factory, GameEventRecord) == after_first
    _ = first


class _FailingSearch:
    async def search(self, query: str, *, limit: int = 3):  # noqa: ANN201
        raise new(codes.SEARCH_UNAVAILABLE, extra={"reason": "provider down"})


async def test_search_failure_degrades_to_original_text():
    from app.rag.service import RagService

    svc = RagService(search_provider=_FailingSearch())
    assert await svc.research("买药") == []
