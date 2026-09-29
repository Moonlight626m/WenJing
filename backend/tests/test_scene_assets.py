"""运行期场景配图调度测试（issue #56）：去重、失败降级、不阻塞命令。

不起浏览器、不连库：调度器只与「设计器 + 就绪回调」两个协作者打交道。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.domain.game.media import AssetKind, AssetRecord, AssetStatus
from app.services.scene_assets import SceneAssetRequest, SceneAssetScheduler


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
class _Recorder:
    """就绪回调记录器（调度器只要求可 await）。"""

    seen: list[tuple[SceneAssetRequest, AssetRecord]] = field(default_factory=list)

    async def __call__(self, request, record) -> None:
        self.seen.append((request, record))


async def test_ready_record_triggers_on_ready():
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer)
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
        designer=lambda: _FakeDesigner(status=AssetStatus.FAILED)
    )
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    await scheduler.drain()

    assert recorder.seen == []


async def test_designer_exception_is_swallowed():
    scheduler = SceneAssetScheduler(
        designer=lambda: _FakeDesigner(error=RuntimeError("provider 503"))
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

    scheduler = SceneAssetScheduler(designer=lambda: _FakeDesigner())
    scheduler.schedule(_request(), on_ready=_Boom())
    await scheduler.drain()


async def test_no_designer_skips_quietly():
    scheduler = SceneAssetScheduler(designer=lambda: None)
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    await scheduler.drain()

    assert recorder.seen == []


async def test_same_scene_is_scheduled_once():
    """同一 (session, scene_key) 只生成一次——重复请求就是重复付费。"""
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer)
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
    scheduler = SceneAssetScheduler(designer=lambda: designer)

    request = _request()
    assert scheduler.schedule(request, on_ready=_Recorder()) is True
    await scheduler.drain()
    assert scheduler.schedule(request, on_ready=_Recorder()) is False

    assert len(designer.calls) == 1


async def test_different_scenes_run_independently():
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer)
    recorder = _Recorder()

    assert scheduler.schedule(_request("scene:1"), on_ready=recorder) is True
    assert scheduler.schedule(_request("scene:2"), on_ready=recorder) is True
    await scheduler.drain()

    assert len(recorder.seen) == 2


async def test_different_sessions_do_not_share_dedup():
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer)
    recorder = _Recorder()

    mine, other = uuid.uuid4(), uuid.uuid4()
    assert scheduler.schedule(_request(session_id=mine), on_ready=recorder) is True
    assert scheduler.schedule(_request(session_id=other), on_ready=recorder) is True
    await scheduler.drain()

    assert len(designer.calls) == 2


async def test_schedule_defers_generation():
    """`schedule()` 同步返回、不同步跑生成：命令响应不等配图。"""
    designer = _FakeDesigner()
    scheduler = SceneAssetScheduler(designer=lambda: designer)
    recorder = _Recorder()

    assert scheduler.schedule(_request(), on_ready=recorder) is True
    # 返回时生成尚未发生（若 schedule 内部 await 了生成，这里就已经有一次调用）
    assert designer.calls == []
    assert recorder.seen == []

    await scheduler.drain()
    assert len(designer.calls) == 1
