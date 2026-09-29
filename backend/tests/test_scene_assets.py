"""运行期场景配图调度测试（issue #56）：去重、失败降级、不阻塞命令。

不起浏览器、不连库：调度器只与「设计器 + 就绪回调」两个协作者打交道。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.domain.game.media import (
    AssetJob,
    AssetJobStatus,
    AssetKind,
    AssetRecord,
    AssetStatus,
    SceneAssetRequest,
)
from app.services.scene_assets import SceneAssetScheduler


def _request(
    scene_key: str = "scene:1", *, session_id: uuid.UUID | None = None
) -> SceneAssetRequest:
    return SceneAssetRequest(
        session_id=session_id or uuid.uuid4(),
        branch_id=uuid.uuid4(),
        scene_key=scene_key,
        description="三人在长安酒馆相遇",
        org_id=uuid.uuid4(),
        script_id=7,
        user_id=uuid.uuid4(),
    )


def _record(status: AssetStatus = AssetStatus.READY) -> AssetRecord:
    return AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="org/x/bg.png",
        kind=AssetKind.BACKGROUND,
        status=status,
    )


@dataclass
class _FakeDesigner:
    """记录调用的假设计器：只实现调度器用到的 `design_scene`。"""

    status: AssetStatus = AssetStatus.READY
    error: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    async def design_scene(self, **kwargs) -> AssetRecord:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return _record(self.status)


@dataclass
class _FakeJobs:
    """内存台账：只实现调度器用到的 `AssetJobPort`，不模拟 DB 语义。

    上限/去重的**持久**那一半在 `SqlAssetJobStore` 上，由集成测试（
    `test_runtime_events.py`）验证；这里只保证调度器把 `limit` 传对了、
    并把收口状态如实写回。
    """

    opened: list[SceneAssetRequest] = field(default_factory=list)
    finished: list[tuple[uuid.UUID, AssetJobStatus, str]] = field(default_factory=list)
    #: 非空即模拟「台账拒绝发起」（去重命中或超上限）
    refuse: bool = False
    #: `recover()` 时返回的在途任务
    pending_jobs: list[AssetJob] = field(default_factory=list)
    limits: list[int] = field(default_factory=list)
    expired: int = 0

    async def open(
        self, request: SceneAssetRequest, *, limit: int = 0
    ) -> AssetJob | None:
        self.limits.append(limit)
        if self.refuse:
            return None
        self.opened.append(request)
        return AssetJob(job_id=uuid.uuid4(), request=request)

    async def finish(
        self,
        job_id: uuid.UUID,
        *,
        status: AssetJobStatus,
        asset_id: uuid.UUID | None = None,
        reason: str = "",
    ) -> None:
        self.finished.append((job_id, status, reason))

    async def pending(self, *, since=None) -> list[AssetJob]:
        return list(self.pending_jobs)

    async def expire(self, *, before) -> int:
        return self.expired


@dataclass
class _Recorder:
    """就绪回调记录器（调度器只要求可 await）。"""

    seen: list[tuple[SceneAssetRequest, AssetRecord]] = field(default_factory=list)

    async def __call__(self, request, record) -> None:
        self.seen.append((request, record))


async def test_ready_record_triggers_on_ready():
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=_FakeJobs())
    recorder = _Recorder()
    request = _request()

    assert scheduler.schedule(request, on_ready=recorder) is True
    await scheduler.drain()

    assert len(recorder.seen) == 1
    seen_request, record = recorder.seen[0]
    assert seen_request.scene_key == "scene:1"
    assert record.status is AssetStatus.READY
    # 请求期绑定的上下文原样转给设计器：session/branch/org 都不能丢
    call = designer.calls[0]
    assert call["session_id"] == request.session_id
    assert call["org_id"] == request.org_id
    assert call["script_id"] == 7
    assert call["subject_key"] == "scene:1"
    assert call["kind"] is AssetKind.BACKGROUND


async def test_failed_record_is_placeholder_not_error():
    """失败即占位：不回调、不抛错，游玩照常。"""
    scheduler = SceneAssetScheduler(
        designer=lambda: _FakeDesigner(status=AssetStatus.FAILED), jobs=_FakeJobs()
    )
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    await scheduler.drain()

    assert recorder.seen == []


async def test_designer_exception_is_swallowed():
    scheduler = SceneAssetScheduler(
        designer=lambda: _FakeDesigner(error=RuntimeError("provider 503")),
        jobs=_FakeJobs(),
    )
    recorder = _Recorder()

    scheduler.schedule(_request(), on_ready=recorder)
    await scheduler.drain()

    assert recorder.seen == []


async def test_on_ready_exception_is_swallowed():
    """落库/推送失败同样不得把异常丢回事件循环（会污染无关任务的日志与告警）。"""

    class _Boom:
        async def __call__(self, request, record) -> None:
            raise RuntimeError("db down")

    scheduler = SceneAssetScheduler(designer=lambda: _FakeDesigner(), jobs=_FakeJobs())
    scheduler.schedule(_request(), on_ready=_Boom())
    await scheduler.drain()


async def test_no_designer_skips_quietly():
    scheduler = SceneAssetScheduler(designer=lambda: None, jobs=_FakeJobs())
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    await scheduler.drain()

    assert recorder.seen == []


async def test_same_scene_is_scheduled_once():
    """同一 (session, scene_key) 只生成一次——重复请求就是重复付费。"""
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=_FakeJobs())
    recorder = _Recorder()
    request = _request()

    assert scheduler.schedule(request, on_ready=recorder) is True
    # 在途期间再请求（同一拍内多条命令）：拦下
    assert scheduler.schedule(request, on_ready=recorder) is False
    await scheduler.drain()
    # 已完成后再请求：仍拦下
    assert scheduler.schedule(request, on_ready=recorder) is False

    assert len(designer.calls) == 1
    assert len(recorder.seen) == 1


async def test_failed_scene_is_not_retried():
    """已失败的场景不再重试：去重键只命中 READY 资产，不拦就会每次命令都付费。"""
    designer = _FakeDesigner(status=AssetStatus.FAILED)
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=_FakeJobs())

    request = _request()
    assert scheduler.schedule(request, on_ready=_Recorder()) is True
    await scheduler.drain()
    assert scheduler.schedule(request, on_ready=_Recorder()) is False

    assert len(designer.calls) == 1


async def test_different_scenes_run_independently():
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=_FakeJobs())
    recorder = _Recorder()

    assert scheduler.schedule(_request("scene:1"), on_ready=recorder) is True
    assert scheduler.schedule(_request("scene:2"), on_ready=recorder) is True
    await scheduler.drain()

    assert len(recorder.seen) == 2


async def test_different_sessions_do_not_share_dedup():
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=_FakeJobs())
    recorder = _Recorder()

    mine, other = uuid.uuid4(), uuid.uuid4()
    assert scheduler.schedule(_request(session_id=mine), on_ready=recorder) is True
    assert scheduler.schedule(_request(session_id=other), on_ready=recorder) is True
    await scheduler.drain()

    assert len(designer.calls) == 2


async def test_schedule_defers_generation():
    """`schedule()` 同步返回、不同步跑生成：命令响应不等配图。"""
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=_FakeJobs())
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    # 返回时生成尚未发生（若 schedule 内部 await 了生成，这里就已经有一次调用）
    assert designer.calls == []
    assert recorder.seen == []

    await scheduler.drain()
    assert len(designer.calls) == 1


# ===== 台账（#57）=====


async def test_job_is_opened_and_finished_ready():
    """成功一次 = 台账上开一行、收一行 ready：崩溃恢复全靠它认账。"""
    designer = _FakeDesigner()
    jobs = _FakeJobs()
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=jobs)
    recorder = _Recorder()
    request = _request()

    scheduler.schedule(request, on_ready=recorder)
    await scheduler.drain()

    assert jobs.opened == [request]
    assert len(jobs.finished) == 1
    job_id, status, reason = jobs.finished[0]
    assert status is AssetJobStatus.READY
    assert reason == ""
    assert recorder.seen[0][1].asset_id is not None


async def test_failed_designer_finishes_job_with_reason():
    """失败也要收口并留下原因——只有 status 的话，失败率归因不出来。"""
    jobs = _FakeJobs()
    scheduler = SceneAssetScheduler(
        designer=lambda: _FakeDesigner(status=AssetStatus.FAILED), jobs=jobs
    )

    scheduler.schedule(_request(), on_ready=_Recorder())
    await scheduler.drain()

    assert jobs.finished[0][1] is AssetJobStatus.FAILED
    assert "failed" in jobs.finished[0][2]


async def test_designer_exception_finishes_job_with_reason():
    jobs = _FakeJobs()
    scheduler = SceneAssetScheduler(
        designer=lambda: _FakeDesigner(error=RuntimeError("provider 503")), jobs=jobs
    )

    scheduler.schedule(_request(), on_ready=_Recorder())
    await scheduler.drain()

    assert jobs.finished[0][1] is AssetJobStatus.FAILED
    assert "provider 503" in jobs.finished[0][2]


async def test_missing_designer_finishes_job_failed():
    """没接媒体栈也要收口：否则每次启动都会被当成「上次崩了」反复重排。"""
    jobs = _FakeJobs()
    scheduler = SceneAssetScheduler(designer=lambda: None, jobs=jobs)

    scheduler.schedule(_request(), on_ready=_Recorder())
    await scheduler.drain()

    assert jobs.finished[0][1] is AssetJobStatus.FAILED


async def test_store_refusal_skips_generation_quietly():
    """台账拒绝发起（去重命中 / 超每会话上限）→ 不生成、不回调、不报错。"""
    designer = _FakeDesigner()
    jobs = _FakeJobs(refuse=True)
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=jobs)
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    await scheduler.drain()

    assert designer.calls == []
    assert recorder.seen == []
    assert jobs.finished == []


async def test_session_cap_is_passed_to_store():
    """上限只在台账里裁决（那里才数得清、才跨重启），调度器负责把配置传下去。"""
    jobs = _FakeJobs()
    scheduler = SceneAssetScheduler(
        designer=lambda: _FakeDesigner(), jobs=jobs, max_images_per_session=3
    )

    scheduler.schedule(_request(), on_ready=_Recorder())
    await scheduler.drain()

    assert jobs.limits == [3]


async def test_recover_requeues_pending_jobs():
    """TTL 内的在途任务重新派发：进程刚重启，玩家很可能还等着这张图。"""
    designer = _FakeDesigner()
    request = _request()
    jobs = _FakeJobs(pending_jobs=[AssetJob(job_id=uuid.uuid4(), request=request)])
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=jobs)
    recorder = _Recorder()

    report = await scheduler.recover(on_ready=recorder)
    await scheduler.drain()

    assert report.requeued == 1
    assert len(designer.calls) == 1
    assert recorder.seen[0][0] == request
    # 重排**不**另开一行台账：那一行本来就还在，另开一条等于把同一场景记两次账
    assert jobs.opened == []
    assert jobs.finished[0][1] is AssetJobStatus.READY


async def test_recover_reports_expired_jobs():
    """超龄的由台账判死（不重排）：崩溃循环不该把同一场景反复付钱。"""
    designer = _FakeDesigner()
    jobs = _FakeJobs(expired=2)
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=jobs)

    report = await scheduler.recover(on_ready=_Recorder())

    assert report.expired == 2
    assert report.requeued == 0
    assert designer.calls == []


async def test_recover_does_not_double_schedule_inflight():
    """同一场景已经在途时不再重排（重启后玩家先到、恢复后到）。"""
    designer = _FakeDesigner()
    request = _request()
    jobs = _FakeJobs(pending_jobs=[AssetJob(job_id=uuid.uuid4(), request=request)])
    scheduler = SceneAssetScheduler(designer=lambda: designer, jobs=jobs)

    assert scheduler.schedule(request, on_ready=_Recorder()) is True
    report = await scheduler.recover(on_ready=_Recorder())
    await scheduler.drain()

    assert report.requeued == 0
    assert len(designer.calls) == 1
