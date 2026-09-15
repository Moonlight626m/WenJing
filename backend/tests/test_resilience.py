"""生产化加固：故障注入与可恢复性（issue #13）。

覆盖矩阵：
- LLM 超时 → retryable 错误、无部分状态（无 script 落库）；
- LLM 非法结构化输出 → 重试后 terminal 错误、无半合法剧本落库；
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
from app.contracts.content import (
    CharacterMention,
    GenreClassification,
    GenreType,
    KeyEvent,
    TextAnalysis,
)
from app.contracts.material import MaterialInput, MaterialSource, OriginalEvidence
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

_MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)


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


class _RaisingLLM:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def chat(self, messages, *, session_id: str = ""):  # noqa: ANN001
        raise self._exc


class _GarbageLLM:
    async def chat(self, messages, *, session_id: str = ""):  # noqa: ANN001
        return "这不是 JSON，也不是任何合法剧本结构。"


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


def _rich_analysis() -> TextAnalysis:
    ev = OriginalEvidence(
        char_start=0, char_end=4, paragraph_index=0, excerpt="那年冬天，母亲病了"
    )
    return TextAnalysis(
        content_hash="deadbeef",
        title="买药",
        genre=GenreClassification(genre=GenreType.NARRATIVE, is_supported=True),
        characters=[
            CharacterMention(name="母亲", role="患病的母亲", evidence_refs=[ev]),
            CharacterMention(name="我", role="儿子", evidence_refs=[ev]),
        ],
        key_events=[
            KeyEvent(
                title="母亲病了",
                description="母亲生病，我离家买药",
                participants=["母亲", "我"],
                order=1,
                evidence_refs=[ev],
            )
        ],
    )


async def _prepared_app(
    factory, *, script_llm
) -> tuple[SessionApplication, uuid.UUID, Actor]:
    from conftest import create_actor

    from app.agents.fake_llm import DeterministicAgentLLM

    actor = await create_actor(factory, name="韧性测试学校")
    svc = SessionApplication(
        session_factory=factory,
        agent_llm=DeterministicAgentLLM(),
        script_llm=script_llm,
    )
    created = await svc.create_session(
        org_id=actor.org_id, owner_user_id=actor.user_id
    )
    sid = created.session_id
    await svc.import_material(
        sid,
        MaterialInput(source=MaterialSource.PASTE, raw_text=_MATERIAL_TEXT),
        actor=actor,
    )
    svc._analyses[sid] = _rich_analysis()
    return svc, sid, actor


async def _count(factory, model) -> int:
    async with factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


# ===== LLM 故障 =====


async def test_llm_timeout_is_retryable_and_leaves_no_partial_state(factory):
    llm = _RaisingLLM(new(codes.LLM_CALL_FAILED, extra={"reason": "timeout"}))
    svc, sid, actor = await _prepared_app(factory, script_llm=llm)

    with pytest.raises(WJError) as excinfo:
        await svc.generate_script(sid, actor=actor)
    assert excinfo.value.code == codes.LLM_CALL_FAILED

    # 无部分状态：无剧本落库、阶段未推进、生成进度标记失败
    assert await _count(factory, ScriptRecord) == 0
    status = await svc.get_status(sid, actor=actor)
    assert status.stage == "init"
    assert svc._generation[sid]["status"] == "failed"

    # 对外 envelope：retryable=True，映射为 LLM 域稳定码
    env = envelope_for(excinfo.value)
    assert env.code == "LLM_CALL_FAILED"
    assert env.retryable is True


async def test_llm_invalid_output_retries_then_terminal(factory):
    svc, sid, actor = await _prepared_app(factory, script_llm=_GarbageLLM())

    with pytest.raises(WJError) as excinfo:
        await svc.generate_script(sid, actor=actor)
    assert excinfo.value.code == codes.CNT_GENERATION_FAILED
    assert await _count(factory, ScriptRecord) == 0


# ===== DB 事务故障 =====


async def test_db_failure_leaves_no_partial_state_and_can_retry(factory, monkeypatch):
    svc, sid, actor = await _prepared_app(factory, script_llm=None)
    pkg = await svc.generate_script(sid, actor=actor)
    events_before = await _count(factory, GameEventRecord)

    original = PersistentEventStore.write_pending

    async def _boom(self, session, session_id):  # noqa: ANN001
        raise OperationalError("INSERT INTO events ...", {}, Exception("db down"))

    monkeypatch.setattr(PersistentEventStore, "write_pending", _boom)

    cmd = _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": pkg.playable_roles[0]})
    with pytest.raises(WJError) as excinfo:
        await svc.submit_command(sid, cmd, actor=actor)
    assert excinfo.value.code == codes.PER_WRITE_FAILED
    env = envelope_for(excinfo.value)
    assert env.code == "PERSISTENCE_WRITE_FAILED"
    assert env.domain.value == "persistence"
    assert env.retryable is True

    # 无部分状态：内存运行时被丢弃，失败命令未落库，无事件被追加
    assert sid not in svc._runtimes
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


async def test_corrupt_snapshot_rebuilds_without_crash(factory):
    svc, sid, actor = await _prepared_app(factory, script_llm=None)
    pkg = await svc.generate_script(sid, actor=actor)
    await svc.submit_command(
        sid,
        _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": pkg.playable_roles[0]}),
        actor=actor,
    )

    async with factory() as s:
        await s.execute(
            update(SnapshotRecord)
            .where(SnapshotRecord.session_id == sid)
            .values(schema_version="0.0.0")
        )
        await s.commit()

    svc._runtimes.clear()
    init = await svc.session_init(sid, actor=actor)
    assert init["stage"] == "stage2_reenacting"
    assert init["player_role"] == pkg.playable_roles[0]


async def test_corrupt_snapshot_payload_rebuilds(factory):
    svc, sid, actor = await _prepared_app(factory, script_llm=None)
    pkg = await svc.generate_script(sid, actor=actor)
    await svc.submit_command(
        sid,
        _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": pkg.playable_roles[0]}),
        actor=actor,
    )

    async with factory() as s:
        await s.execute(
            update(SnapshotRecord)
            .where(SnapshotRecord.session_id == sid)
            .values(plot_context={"beat_cursor": "not-an-int"})
        )
        await s.commit()

    svc._runtimes.clear()
    init = await svc.session_init(sid, actor=actor)
    assert init["stage"] == "stage2_reenacting"


async def test_incompatible_script_schema_returns_clear_error(factory):
    svc, sid, actor = await _prepared_app(factory, script_llm=None)
    await svc.generate_script(sid, actor=actor)

    async with factory() as s:
        await s.execute(
            update(ScriptRecord)
            .where(ScriptRecord.session_id == sid)
            .values(script_data={"broken": True})
        )
        await s.commit()

    svc._runtimes.clear()
    with pytest.raises(WJError) as excinfo:
        await svc.session_init(sid, actor=actor)
    assert excinfo.value.code == codes.PER_INCOMPATIBLE_SCHEMA
    assert envelope_for(excinfo.value).code == "PERSISTENCE_INCOMPATIBLE_SCHEMA"


# ===== 幂等 / 搜索降级 =====


async def test_command_resend_no_duplicate_domain_events(factory):
    svc, sid, actor = await _prepared_app(factory, script_llm=None)
    pkg = await svc.generate_script(sid, actor=actor)

    before = await _count(factory, GameEventRecord)
    cmd = _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": pkg.playable_roles[0]})
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
