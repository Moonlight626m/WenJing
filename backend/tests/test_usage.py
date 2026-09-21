"""LLM 用量计量与聚合测试（issue #22 / ADR-0002 §5）。

覆盖验收：
- Stage1 生成与每轮 Agent / 验证调用各写一条 llm_usage；
- 聚合查询正确（按 org / 时间 / 用途）；
- 计量为 best-effort：落库失败不影响主流程。

依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401
from app.contracts.enums import UsagePurpose
from app.domain.access import Actor
from app.infrastructure.usage import UsageContext, UsageRecorder, UsageRecordingLLM, estimate_tokens
from app.services.admin import AdminService

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
        pytest.skip("PostgreSQL 未可用，跳过用量计量集成测试")
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


async def _new_actor(factory, name: str = "计量测试学校") -> Actor:
    from conftest import create_actor

    return await create_actor(factory, name=name)


class _EchoLLM:
    """记录 provider/model 的确定性内层 LLM。"""

    provider = "test-provider"
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        self.calls += 1
        return "回答：" + (messages[-1]["content"] if messages else "")


async def _usage_rows(factory, org_id, purpose: str | None = None):
    from sqlalchemy import select

    from app.infrastructure.models.llm_usage import LlmUsage

    async with factory() as s:
        stmt = select(LlmUsage).where(LlmUsage.org_id == org_id)
        if purpose is not None:
            stmt = stmt.where(LlmUsage.purpose == purpose)
        return (await s.execute(stmt)).scalars().all()


def test_estimate_tokens_is_positive() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("一二三四") == 2


async def test_recording_llm_writes_one_row_per_call(factory) -> None:
    actor = await _new_actor(factory)
    recorder = UsageRecorder(session_factory=factory)
    inner = _EchoLLM()
    llm = UsageRecordingLLM(
        inner,
        recorder=recorder,
        context=UsageContext(
            org_id=actor.org_id, user_id=actor.user_id, script_id=42
        ),
    )

    await llm.chat([{"role": "user", "content": "你好"}], purpose=UsagePurpose.AGENT)
    await llm.chat([{"role": "user", "content": "再问"}], purpose=UsagePurpose.VERIFY)

    rows = await _usage_rows(factory, actor.org_id)
    assert {r.purpose for r in rows} == {"agent", "verify"}
    assert len(rows) == 2
    for row in rows:
        assert row.provider == "test-provider"
        assert row.model == "test-model"
        assert row.script_id == 42
        assert row.total_tokens == row.prompt_tokens + row.completion_tokens
        assert row.prompt_tokens > 0 and row.completion_tokens > 0
    assert inner.calls == 2


async def test_provider_reported_usage_is_preferred(factory) -> None:
    """内层若回报真实 token，计量采信之（而非按文本估算）。"""
    from app.domain.llm import TokenUsage

    actor = await _new_actor(factory)

    class _UsageLLM:
        provider = "real-provider"
        model = "real-model"

        async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
            raise AssertionError("应走 chat_with_usage")

        async def chat_with_usage(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
            return "答复", TokenUsage(
                prompt_tokens=111, completion_tokens=222, total_tokens=333
            )

    recorder = UsageRecorder(session_factory=factory)
    llm = recorder.wrap(
        _UsageLLM(),
        UsageContext(org_id=actor.org_id, user_id=actor.user_id),
    )
    await llm.chat([{"role": "user", "content": "很长的内容"}], purpose=UsagePurpose.VERIFY)

    rows = await _usage_rows(factory, actor.org_id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.prompt_tokens, row.completion_tokens, row.total_tokens) == (111, 222, 333)
    assert row.provider == "real-provider"
    assert row.purpose == "verify"


async def test_record_failure_does_not_raise() -> None:
    class _BoomFactory:
        def __call__(self):  # noqa: ANN204
            raise RuntimeError("db down")

    recorder = UsageRecorder(session_factory=_BoomFactory())  # type: ignore[arg-type]
    await recorder.record(
        UsageContext(org_id=uuid.uuid4(), user_id=uuid.uuid4()),
        provider="p",
        model="m",
        purpose=UsagePurpose.AGENT,
        messages=[{"role": "user", "content": "x"}],
        completion="y",
    )


async def test_stage1_generation_is_metered(factory) -> None:
    """Stage1 生成调用写入一条 purpose=stage1 的用量记录。"""
    actor = await _new_actor(factory)
    from app.contracts.material import MaterialInput, MaterialSource
    from app.domain.content.pipeline import ContentPipeline
    from app.domain.generation.stage1 import synthesize_script_package
    from app.services.script_library import ScriptLibrary

    text_in = "那年冬天，母亲病了。我离开家，到城里去买药。母亲说：路上小心。"
    analysis = ContentPipeline().analyze(
        MaterialInput(source=MaterialSource.PASTE, raw_text=text_in)
    )

    class _SynthLLM:
        provider = "test-provider"
        model = "stage1-test"

        async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
            return synthesize_script_package(analysis).model_dump_json()

    recorder = UsageRecorder(session_factory=factory)
    library = ScriptLibrary(
        session_factory=factory, script_llm=_SynthLLM(), usage_recorder=recorder
    )
    material = await library.import_material(
        actor, MaterialInput(source=MaterialSource.PASTE, raw_text=text_in)
    )
    script = await library.create_script(
        actor, material_id=material.id, name="计量剧本", description=None
    )
    await library.start_generation(script.id, actor)
    await library.await_generation(script.id)
    assert (await library.progress(script.id)).status == "succeeded"

    rows = await _usage_rows(factory, actor.org_id, purpose="stage1")
    assert len(rows) == 1
    assert rows[0].script_id == script.id
    assert rows[0].session_id is None
    assert rows[0].provider == "test-provider"


@pytest.mark.anyio
async def test_no_key_synth_generation_still_metered(factory) -> None:
    """生产无 key 组合根：script_llm=None 走确定性合成，仍入账 stage1 用量。

    回归 CI：全新库（WENJING_LLM_API_KEY 为空）下运营后台用量看板不得为空。
    """
    actor = await _new_actor(factory)
    from app.contracts.material import MaterialInput, MaterialSource
    from app.services.script_library import ScriptLibrary

    text_in = "那年冬天，母亲病了。我离开家，到城里去买药。母亲说：路上小心。"
    recorder = UsageRecorder(session_factory=factory)
    library = ScriptLibrary(session_factory=factory, usage_recorder=recorder)
    material = await library.import_material(
        actor, MaterialInput(source=MaterialSource.PASTE, raw_text=text_in)
    )
    script = await library.create_script(
        actor, material_id=material.id, name="合成计量剧本", description=None
    )
    await library.start_generation(script.id, actor)
    await library.await_generation(script.id)
    assert (await library.progress(script.id)).status == "succeeded"

    rows = await _usage_rows(factory, actor.org_id, purpose="stage1")
    assert len(rows) == 1
    assert rows[0].script_id == script.id
    assert rows[0].provider == "deterministic"
    assert rows[0].model == "deterministic"
    assert rows[0].total_tokens > 0


async def test_agent_and_verify_calls_are_metered(factory) -> None:
    """游玩命令触发角色提议（agent）+ 验证（verify），各写入一条并带 session_id。"""
    actor = await _new_actor(factory)

    from conftest import generate_script_id

    from app.contracts.commands import CommandKind, PlayerCommand
    from app.infrastructure.llm.fake import DeterministicAgentLLM
    from app.services.session_runtime import SessionApplication

    recorder = UsageRecorder(session_factory=factory)
    script_id = await generate_script_id(factory, actor)
    app = SessionApplication(
        session_factory=factory,
        agent_llm=DeterministicAgentLLM(),
        usage_recorder=recorder,
    )
    sid = (
        await app.create_session(
            org_id=actor.org_id, owner_user_id=actor.user_id, script_id=script_id
        )
    ).session_id
    await app.initialize_session(sid, actor)
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]
    await app.submit_command(
        sid,
        PlayerCommand(
            session_id=sid, kind=CommandKind.SELECT_ROLE, payload={"role_name": role}
        ),
        actor=actor,
    )

    rows = await _usage_rows(factory, actor.org_id)
    by_purpose = {r.purpose for r in rows}
    assert {"agent", "verify"} <= by_purpose
    assert all(r.session_id == sid for r in rows if r.session_id is not None)
    assert all(r.script_id == script_id for r in rows)


async def test_usage_aggregation_by_org_time_and_purpose(factory) -> None:
    first = await _new_actor(factory, "聚合甲校")
    other = await _new_actor(factory, "聚合乙校")
    recorder = UsageRecorder(session_factory=factory)
    for ctx_actor, purpose, n in (
        (first, UsagePurpose.AGENT, 2),
        (first, UsagePurpose.VERIFY, 1),
        (other, UsagePurpose.STAGE1, 3),
    ):
        llm = UsageRecordingLLM(
            _EchoLLM(),
            recorder=recorder,
            context=UsageContext(org_id=ctx_actor.org_id, user_id=ctx_actor.user_id),
        )
        for _ in range(n):
            await llm.chat([{"role": "user", "content": "计量"}], purpose=purpose)

    service = AdminService(session_factory=factory)

    # 按 org 分组：first 两条（agent/verify），other 一条（stage1）
    all_rows = await service.usage_aggregate()
    first_rows = [r for r in all_rows if r.org_id == first.org_id]
    assert sum(r.call_count for r in first_rows) == 3
    assert {r.purpose for r in first_rows} == {"agent", "verify"}
    other_rows = [r for r in all_rows if r.org_id == other.org_id]
    assert len(other_rows) == 1 and other_rows[0].call_count == 3

    # 按 org 过滤 + 按 purpose 过滤
    only_agent = await service.usage_aggregate(
        org_id=first.org_id, purpose=UsagePurpose.AGENT
    )
    assert len(only_agent) == 1 and only_agent[0].call_count == 2

    # 按时间窗过滤（限定本 org，避免与其他用例数据串扰）
    now = datetime.now(UTC)
    in_window = await service.usage_aggregate(
        org_id=first.org_id, since=now - timedelta(hours=1)
    )
    assert sum(r.call_count for r in in_window) == 3
    assert await service.usage_aggregate(
        org_id=first.org_id, since=now + timedelta(hours=1)
    ) == []
    assert await service.usage_aggregate(
        org_id=first.org_id, until=now - timedelta(hours=1)
    ) == []
