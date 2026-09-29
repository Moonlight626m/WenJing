"""命令外事件路径 + 运行期配图（issue #56/#57 验收，真实 PG + fake adapters）。

覆盖 ADR-0005 §5 / design M4-2、M4-3 的验收：

- 端到端：新场景占位 → 生成 → 事件落库 → 推送（前端据此替换背景）（#56）；
- 并发命令不破坏 CAS：配图落库与玩家命令撞版本时重试，两边都不丢（#56）；
- 失败占位不阻塞游玩：设计器失败只让这场没有图，叙事照常推进（#56）；
- 每会话生图上限：超限只留占位，不再发起生成（#57）；
- 崩溃恢复：进程留下的 pending 票据判死、TTL 内的在途任务重排并补推（#57）。

依赖真实 PostgreSQL；不可用时 skip。这里用**真的** `SqlAssetJobStore` /
`SqlAssetRepository`（上限与恢复的语义都建在库上），只把设计器换成假的。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401
from app.contracts.commands import CommandKind, PlayerCommand
from app.domain.game.media import (
    AssetJobStatus,
    AssetKind,
    AssetRecord,
    AssetStatus,
    SceneAssetRequest,
)
from app.infrastructure.errx import codes, new
from app.infrastructure.media import SqlAssetJobStore, SqlAssetRepository
from app.infrastructure.models.asset_job import AssetJob as AssetJobRow
from app.infrastructure.models.command import CommandRecord
from app.infrastructure.models.session import Session as SessionRecord
from app.services.scene_assets import SceneAssetScheduler
from app.services.session_events import SessionEventHub
from app.services.session_runtime import SessionApplication

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
        await engine.dispose()
        return False


@pytest.fixture(scope="module")
async def factory():
    if not await _db_available():
        pytest.skip("PostgreSQL 未可用，跳过命令外事件路径集成测试")
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
async def actor(factory):
    from conftest import create_actor

    return await create_actor(factory, name="命令外事件学校")


class FakeSceneDesigner:
    """假设计器：只实现调度器用到的 `design_scene`，记录收到的请求。"""

    def __init__(self, status: AssetStatus = AssetStatus.READY) -> None:
        self.status = status
        self.calls: list[dict] = []

    async def design_scene(self, **kwargs) -> AssetRecord:
        self.calls.append(kwargs)
        return AssetRecord(
            asset_id=uuid.uuid4(),
            object_key=f"org/{kwargs.get('org_id')}/bg.png",
            kind=AssetKind.BACKGROUND,
            status=self.status,
            script_id=kwargs.get("script_id"),
            session_id=kwargs.get("session_id"),
        )


class Harness:
    """一个装配了假设计器 + hub 的应用，便于同时断言「落库」与「推送」。"""

    def __init__(
        self, app: SessionApplication, sid: uuid.UUID, designer, hub, jobs, assets
    ) -> None:
        self.app = app
        self.sid = sid
        self.designer = designer
        self.hub = hub
        self.jobs = jobs
        self.assets = assets

    async def drain(self) -> None:
        """等在途生成收尾——不然「没有推送」可能只是因为任务还没跑。"""
        assert self.app._asset_scheduler is not None
        await self.app._asset_scheduler.drain()


async def _make_harness(
    factory,
    actor,
    *,
    status: AssetStatus = AssetStatus.READY,
    max_images_per_session: int = 0,
    job_ttl_seconds: int = 900,
) -> Harness:
    """建可玩会话：应用挂了假设计器与 hub（组合根接线等价物）。

    台账与资产仓库用**真实现**（#57 的上限/恢复语义就建在它们上面），
    只有设计器是假的——真设计器要连 provider。
    """
    from conftest import generate_script_id

    from app.infrastructure.llm.fake import DeterministicAgentLLM

    designer = FakeSceneDesigner(status)
    hub = SessionEventHub()
    jobs = SqlAssetJobStore(session_factory=factory)
    assets = SqlAssetRepository(session_factory=factory)
    app = SessionApplication(
        session_factory=factory,
        agent_llm=DeterministicAgentLLM(),
        asset_scheduler=SceneAssetScheduler(
            designer=lambda: designer,
            jobs=jobs,
            max_images_per_session=max_images_per_session,
            job_ttl_seconds=job_ttl_seconds,
        ),
        event_hub=hub,
        assets=assets,
    )
    script_id = await generate_script_id(factory, actor)
    sid = (
        await app.create_session(
            org_id=actor.org_id, owner_user_id=actor.user_id, script_id=script_id
        )
    ).session_id
    await app.initialize_session(sid, actor)
    return Harness(app, sid, designer, hub, jobs, assets)


def _cmd(sid: uuid.UUID, kind: CommandKind, payload: dict | None = None) -> PlayerCommand:
    return PlayerCommand(session_id=sid, kind=kind, payload=payload or {})


async def _drive_to_stage3(app: SessionApplication, sid: uuid.UUID, actor) -> dict:
    """选角 → 推进到结局确认 → 进入续写；返回进 stage3 那次的 RuntimeUpdate。"""
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]
    await app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    for _ in range(12):
        upd = await app.submit_command(
            sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
        )
        ix = upd.state.active_interaction
        if ix is not None and any("续写" in o.label for o in ix.options):
            break
    else:
        raise AssertionError("未能推进到结局确认交互点")
    # 选「进入剧情续写」→ stage2_complete → enter_stage3
    await app.submit_command(
        sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
    )
    upd = await app.submit_command(sid, _cmd(sid, CommandKind.ENTER_STAGE3), actor=actor)
    assert upd.state.stage.value == "stage3_extending"
    return {"stage": upd.state.stage.value, "scene_key": upd.state.scene_key}


async def _playable_in_scene(
    factory, actor
) -> tuple[SessionApplication, uuid.UUID, str, uuid.UUID]:
    """建可玩会话并选角：此刻已有「当前场景」（scene_key 非空）与活动分支。

    未选角时 beat_cursor 仍为 0，引擎按约定不认「当前场景」（#53），拿不到 scene_key。
    """
    from conftest import make_playable_session

    app, sid = await make_playable_session(factory, actor)
    role = (await app.get_status(sid, actor=actor)).playable_roles[0]
    await app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    init = await app.session_init(sid, actor=actor)
    assert init["scene_key"]
    return app, sid, init["scene_key"], uuid.UUID(init["branch_id"])


async def _count_commands(factory, sid: uuid.UUID) -> int:
    async with factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(CommandRecord)
                    .where(CommandRecord.session_id == sid)
                )
            ).scalar_one()
        )


# ===== 端到端：新场景占位 → 生成 → 事件落库 → 推送 =====


async def test_new_scene_triggers_generation_and_push(factory, actor):
    harness = await _make_harness(factory, actor)
    sid, hub = harness.sid, harness.hub

    with hub.subscribe(sid) as queue:
        state = await _drive_to_stage3(harness.app, sid, actor)
        # 占位先行：进入新场景那一刻还没有图（前端降级为渐变）
        assert state["scene_key"]
        pushed = await asyncio.wait_for(queue.get(), timeout=15)

    assert pushed["type"] == "asset_ready"
    assert pushed["payload"]["category"] == "asset_ready"
    assert pushed["payload"]["scene_key"] == state["scene_key"]
    asset_id = pushed["payload"]["current_asset"]["asset_id"]
    assert pushed["payload"]["current_asset"]["kind"] == "background"

    # 设计器收到了运行期请求，且请求期绑定了 session/script
    assert len(harness.designer.calls) == 1
    call = harness.designer.calls[0]
    assert call["subject_key"] == state["scene_key"]
    assert call["session_id"] == sid
    assert call["script_id"] is not None

    # 事件落库后：权威快照带上这张图。session_init 走的是「从 DB 重建 + 重放」
    # 同一条路（_restore_runtime），所以这里同时验证了重连/重放不会丢背景。
    init = await harness.app.session_init(sid, actor=actor)
    assert init["current_asset"]["asset_id"] == asset_id
    assert init["scene_key"] == state["scene_key"]


# ===== 命令外事件的落库语义 =====


async def test_report_asset_ready_writes_event_without_command(factory, actor):
    app, sid, scene_key, branch_id = await _playable_in_scene(factory, actor)
    before = await _count_commands(factory, sid)

    asset_id = uuid.uuid4()
    msgs = await app.report_asset_ready(
        sid, branch_id=branch_id, scene_key=scene_key, asset_id=asset_id
    )

    assert len(msgs) == 1
    assert msgs[0]["type"] == "asset_ready"
    assert msgs[0]["payload"]["current_asset"]["asset_id"] == str(asset_id)
    # 不带 player command：命令表不得多出行（幂等闸是命令的语义，配图不是命令）
    assert await _count_commands(factory, sid) == before
    # 落库后可经 session_init（断线重建）读到
    again = await app.session_init(sid, actor=actor)
    assert again["current_asset"]["asset_id"] == str(asset_id)


async def test_report_asset_ready_noop_on_inactive_branch(factory, actor):
    """回溯放弃的分支上补图必须 no-op，否则资产会挂到已被抛弃的历史上。"""
    app, sid, scene_key, _branch = await _playable_in_scene(factory, actor)

    msgs = await app.report_asset_ready(
        sid,
        branch_id=uuid.uuid4(),  # 不是当前活动分支
        scene_key=scene_key,
        asset_id=uuid.uuid4(),
    )

    assert msgs == []
    assert (await app.session_init(sid, actor=actor))["current_asset"] is None


async def test_report_asset_ready_retries_cas_conflict(factory, actor, monkeypatch):
    """与玩家命令撞版本时重试落库：命令与配图都不丢（验收「并发命令不破坏 CAS」）。"""
    app, sid, scene_key, branch_id = await _playable_in_scene(factory, actor)

    attempts: list[int] = []
    original = app._store.commit

    async def _conflict_once(**kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise new(codes.SESS_CONFLICT, extra={"id": str(sid)})
        await original(**kwargs)

    monkeypatch.setattr(app._store, "commit", _conflict_once)

    msgs = await app.report_asset_ready(
        sid, branch_id=branch_id, scene_key=scene_key, asset_id=uuid.uuid4()
    )

    assert len(attempts) == 2  # 第一次冲突，重试成功
    assert len(msgs) == 1
    # 同一分支上仍能继续提交命令（冲突没有把会话行或分支指针弄坏）
    upd = await app.submit_command(
        sid, _cmd(sid, CommandKind.FREE_INPUT, {"text": "我先去买药"}), actor=actor
    )
    assert upd.new_events


async def test_report_asset_ready_gives_up_after_conflicts(factory, actor, monkeypatch):
    """持续冲突时放弃投递（不抛错）：事件流是权威，配图可丢，命令路径不能受牵连。"""
    app, sid, scene_key, branch_id = await _playable_in_scene(factory, actor)

    calls: list[int] = []

    async def _always_conflict(**kwargs):
        calls.append(1)
        raise new(codes.SESS_CONFLICT, extra={"id": str(sid)})

    monkeypatch.setattr(app._store, "commit", _always_conflict)

    msgs = await app.report_asset_ready(
        sid, branch_id=branch_id, scene_key=scene_key, asset_id=uuid.uuid4()
    )

    assert msgs == []
    assert len(calls) == 3  # 重试到上限即放弃
    monkeypatch.undo()
    assert (await app.session_init(sid, actor=actor))["current_asset"] is None


# ===== 失败占位不阻塞游玩 =====


async def test_failed_generation_does_not_block_play(factory, actor):
    harness = await _make_harness(factory, actor, status=AssetStatus.FAILED)
    sid = harness.sid

    with harness.hub.subscribe(sid) as queue:
        state = await _drive_to_stage3(harness.app, sid, actor)
        assert state["scene_key"]
        await harness.drain()
        assert queue.empty()  # 失败不推送

    assert len(harness.designer.calls) == 1
    # 占位：当前资产为空，页面降级为渐变
    assert (await harness.app.session_init(sid, actor=actor))["current_asset"] is None

    # 游玩照常：后续命令仍可提交并推进
    upd = await harness.app.submit_command(
        sid, _cmd(sid, CommandKind.FREE_INPUT, {"text": "继续往前走"}), actor=actor
    )
    assert upd.state.stage.value == "stage3_extending"
    assert upd.new_events


async def test_designer_error_does_not_block_play(factory, actor, monkeypatch):
    """设计器抛异常（provider 5xx 之类）同样只降级，不打断游玩。"""
    harness = await _make_harness(factory, actor)
    sid = harness.sid

    async def _boom(**kwargs):
        raise RuntimeError("provider 503")

    monkeypatch.setattr(harness.designer, "design_scene", _boom)

    with harness.hub.subscribe(sid) as queue:
        await _drive_to_stage3(harness.app, sid, actor)
        await harness.drain()
        assert queue.empty()

    upd = await harness.app.submit_command(
        sid, _cmd(sid, CommandKind.FREE_INPUT, {"text": "继续往前走"}), actor=actor
    )
    assert upd.new_events


async def test_stage2_does_not_generate_at_runtime(factory, actor):
    """Stage2 的图由剧本生成 workflow 离线预生成（#48）：游走中不再发起生成。

    否则等于对已审批的剧本私自改图，还要为同一张图付两次费。
    """
    harness = await _make_harness(factory, actor)
    sid = harness.sid
    role = (await harness.app.get_status(sid, actor=actor)).playable_roles[0]
    await harness.app.submit_command(
        sid, _cmd(sid, CommandKind.SELECT_ROLE, {"role_name": role}), actor=actor
    )
    for _ in range(3):
        upd = await harness.app.submit_command(
            sid, _cmd(sid, CommandKind.CHOOSE_OPTION, {"option_id": "0"}), actor=actor
        )
        if upd.terminal:
            break

    await harness.drain()
    assert harness.designer.calls == []


# ===== 每会话生图上限（#57）=====


async def _request_for(
    harness: Harness,
    actor,
    *,
    scene_key: str,
    branch_id: uuid.UUID,
    description: str = "长安酒馆偶遇",
) -> SceneAssetRequest:
    """按真实路径的绑定口径造一个配图请求（归属上下文全从会话取）。"""
    from app.infrastructure.models.session import Session as SessionRow

    async with harness.app._factory() as s:
        sess = await s.get(SessionRow, harness.sid)
    return SceneAssetRequest(
        session_id=harness.sid,
        branch_id=branch_id,
        scene_key=scene_key,
        description=description,
        org_id=sess.org_id,
        script_id=sess.script_id,
        user_id=sess.owner_user_id,
    )


async def _playable_harness(factory, actor, **kwargs) -> tuple[Harness, str, uuid.UUID]:
    """建可玩会话并选角：返回 (harness, 当前 scene_key, 活动 branch_id)。

    选角本身不发起配图（只有 stage3 的运行期新场景才发起），所以这里拿到的
    「当前场景」正是待配图的那个。
    """
    harness = await _make_harness(factory, actor, **kwargs)
    role = (await harness.app.get_status(harness.sid, actor=actor)).playable_roles[0]
    await harness.app.submit_command(
        harness.sid,
        _cmd(harness.sid, CommandKind.SELECT_ROLE, {"role_name": role}),
        actor=actor,
    )
    init = await harness.app.session_init(harness.sid, actor=actor)
    return harness, init["scene_key"], uuid.UUID(init["branch_id"])


async def _schedule(app: SessionApplication, request: SceneAssetRequest) -> bool:
    assert app._asset_scheduler is not None
    return app._asset_scheduler.schedule(request, on_ready=app._apply_asset_ready)


async def test_session_cap_keeps_placeholder(factory, actor):
    """超限那场只留占位：上限是**硬**成本闸，不是「尽量少生成」。"""
    harness, scene_key, branch_id = await _playable_harness(
        factory, actor, max_images_per_session=1
    )
    first = await _request_for(harness, actor, scene_key=scene_key, branch_id=branch_id)
    second = await _request_for(
        harness, actor, scene_key=f"{scene_key}+1", branch_id=branch_id
    )

    assert await _schedule(harness.app, first) is True
    assert await _schedule(harness.app, second) is True
    await harness.drain()

    assert len(harness.designer.calls) == 1
    # 第一张照常落库：上限拦住的是「继续花钱」，不是「已经花掉的那张」
    assert (await harness.app.session_init(harness.sid, actor=actor))[
        "current_asset"
    ] is not None


async def test_session_cap_is_per_session(factory, actor):
    """上限按会话算：另一个会话不该被邻居的额度拖累。"""
    harness, scene_key, branch_id = await _playable_harness(
        factory, actor, max_images_per_session=1
    )
    async with harness.app._factory() as s:
        sess = await s.get(SessionRecord, harness.sid)
    other = (
        await harness.app.create_session(
            org_id=sess.org_id, owner_user_id=sess.owner_user_id, script_id=sess.script_id
        )
    ).session_id
    other_init = await harness.app.session_init(other, actor=actor)

    mine = await _request_for(harness, actor, scene_key=scene_key, branch_id=branch_id)
    theirs = SceneAssetRequest(
        session_id=other,
        branch_id=uuid.UUID(other_init["branch_id"]),
        scene_key=scene_key,
        description="长安酒馆偶遇",
        org_id=sess.org_id,
        script_id=sess.script_id,
        user_id=sess.owner_user_id,
    )

    assert await _schedule(harness.app, mine) is True
    assert await _schedule(harness.app, theirs) is True
    await harness.drain()

    assert len(harness.designer.calls) == 2


async def test_same_scene_is_not_regenerated_after_restart(factory, actor):
    """重启后仍不重复付费：进程内去重集合丢了，`asset_jobs` 的唯一约束还在。"""
    harness, scene_key, branch_id = await _playable_harness(factory, actor)
    request = await _request_for(harness, actor, scene_key=scene_key, branch_id=branch_id)

    assert await _schedule(harness.app, request) is True
    await harness.drain()
    # 换一个调度器（等于重启后新进程），同一场景再发起
    fresh = SceneAssetScheduler(
        designer=lambda: harness.designer, jobs=harness.jobs
    )

    assert fresh.schedule(request, on_ready=harness.app._apply_asset_ready) is True
    await fresh.drain()

    assert len(harness.designer.calls) == 1


# ===== 崩溃恢复（#57）=====


async def test_crash_leaves_recoverable_pending_job(factory, actor):
    """崩溃现场重排：TTL 内的在途任务重新生成，图照样出现在会话里。

    这里手工造出「进程崩在生成中途」的现场——台账一行 pending、assets 一张
    pending 票据——再走一次启动恢复，等价于重启后玩家重连。
    """
    harness, scene_key, branch_id = await _playable_harness(factory, actor)
    request = await _request_for(harness, actor, scene_key=scene_key, branch_id=branch_id)
    job = await harness.jobs.open(request)
    assert job is not None
    stale_id = uuid.uuid4()
    await harness.assets.save(
        AssetRecord(
            asset_id=stale_id,
            object_key="org/x/assets/stale/original.webp",
            kind=AssetKind.BACKGROUND,
            status=AssetStatus.PENDING,
            org_id=request.org_id,
            script_id=request.script_id,
            dedup_key="crash-leftover",
        )
    )

    with harness.hub.subscribe(harness.sid) as queue:
        report = await harness.app.recover_asset_jobs()
        await harness.drain()
        pushed = await asyncio.wait_for(queue.get(), timeout=15)

    assert report.requeued == 1
    assert len(harness.designer.calls) == 1
    # 崩溃留下的 pending 票据判死：表里不再挂永远不动的行
    stale = await harness.assets.get_by_id(stale_id)
    assert stale is not None and stale.status is AssetStatus.FAILED
    # 补上的图进了事件流：玩家重连走 session_init 就能拿到
    assert pushed["payload"]["scene_key"] == scene_key
    init = await harness.app.session_init(harness.sid, actor=actor)
    assert init["current_asset"]["asset_id"] == pushed["payload"]["current_asset"]["asset_id"]


async def test_recover_expires_job_past_ttl(factory, actor):
    """超 TTL 的在途任务判死而不重排：崩溃循环不该反复为同一场景付费。"""
    harness, scene_key, branch_id = await _playable_harness(
        factory, actor, job_ttl_seconds=60
    )
    request = await _request_for(harness, actor, scene_key=scene_key, branch_id=branch_id)
    job = await harness.jobs.open(request)
    assert job is not None
    async with harness.app._factory() as s:
        row = await s.get(AssetJobRow, job.job_id)
        row.created_at = datetime.now(UTC) - timedelta(seconds=120)
        await s.commit()

    report = await harness.app.recover_asset_jobs()
    await harness.drain()

    assert report.expired == 1
    assert report.requeued == 0
    assert harness.designer.calls == []
    async with harness.app._factory() as s:
        row = await s.get(AssetJobRow, job.job_id)
    assert row.status == AssetJobStatus.FAILED.value
    assert row.reason


async def test_failed_attempt_is_recorded_with_reason(factory, actor):
    """失败也要在台账上留原因：光有 status 归因不出失败率。"""
    harness, scene_key, branch_id = await _playable_harness(factory, actor)

    async def _boom(**kwargs):
        raise RuntimeError("provider 503")

    harness.designer.design_scene = _boom
    request = await _request_for(harness, actor, scene_key=scene_key, branch_id=branch_id)

    await _schedule(harness.app, request)
    await harness.drain()

    async with harness.app._factory() as s:
        row = (
            await s.execute(
                select(AssetJobRow).where(AssetJobRow.session_id == harness.sid)
            )
        ).scalars().one()
    assert row.status == AssetJobStatus.FAILED.value
    assert "provider 503" in row.reason
