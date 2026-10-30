"""生成进度 SSE（`GET /api/scripts/{id}/generation/stream`）单元测试。

不值走 HTTP：starlette 1.6 的 TestClient 传输层会把整个 ASGI 响应跑完才返回
（`_TestClientTransport.handle_request` 内 `portal.call(self.app, ...)`），
对不自行收流的 SSE 表现为永久挂起。故此处直接驱动路由生成器：假 `ScriptLibrary`
提供归属校验与初始快照，真 `GenerationProgressHub` 推帧，无需数据库。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from starlette.requests import Request

from app.contracts.enums import UserRole
from app.contracts.generation import GenerationProgress, GenerationStatus
from app.controllers.auth_deps import Principal
from app.controllers.scripts import stream_script_generation
from app.domain.access import Actor
from app.infrastructure.models.auth_session import AuthSession
from app.infrastructure.models.user import User
from app.services.progress_hub import GenerationProgressHub

_SCRIPT_ID = 7
_TIMEOUT = 5.0
_DATA_PREFIX = "data: "


class _FakeLibrary:
    """仅覆盖流式端点用到的两个读口：归属校验与初始快照。"""

    def __init__(
        self, hub: GenerationProgressHub, owner: Actor, snapshot=None
    ) -> None:
        self.progress_hub = hub
        self._owner = owner
        self._snapshot = snapshot

    async def get_script(self, script_id: int, actor: Actor):
        return SimpleNamespace(owner_user_id=self._owner.user_id)

    async def progress(self, script_id: int):
        return self._snapshot


async def _receive():
    """`Request.is_disconnected()` 用 CancelScope 立即取消 receive，据此判「未断开」。"""
    await asyncio.sleep(3600)


def _request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": []}, _receive
    )


def _principal(actor: Actor) -> Principal:
    user = User(
        id=actor.user_id,
        org_id=actor.org_id,
        role=actor.role.value,
        email="stream@test.local",
        nickname="流式教师",
        password_hash="unused",
    )
    auth_session = AuthSession(
        id=uuid.uuid4(),
        user_id=actor.user_id,
        token_hash="unused",
        csrf_token="unused",
        expires_at=datetime.now(UTC),
    )
    return Principal(
        user=user, auth_session=auth_session, csrf_token="unused", token="unused"
    )


def _actor() -> Actor:
    return Actor(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role=UserRole.TEACHER)


async def _open_stream(
    hub: GenerationProgressHub, actor: Actor
) -> tuple[asyncio.Task, list[str]]:
    """开流并等到订阅登记，返回 (收取任务, 已收帧)。

    订阅先于发布是必要条件：`publish` 对无订阅者的剧本零开销。
    """
    response = await stream_script_generation(
        _SCRIPT_ID, _request(), _principal(actor), _FakeLibrary(hub, actor)
    )
    frames: list[str] = []

    async def _collect() -> None:
        async for frame in response.body_iterator:
            frames.append(frame)

    task = asyncio.create_task(_collect())
    deadline = time.monotonic() + _TIMEOUT
    while hub.subscriber_count(_SCRIPT_ID) == 0:
        assert time.monotonic() < deadline, "SSE 订阅未登记"
        await asyncio.sleep(0.01)
    return task, frames


def _statuses(frames: list[str]) -> list[str]:
    """数据帧的 status（`: keepalive` 心跳是注释行，不是数据帧）。"""
    return [
        json.loads(frame[len(_DATA_PREFIX) :])["status"]
        for frame in frames
        if frame.startswith(_DATA_PREFIX)
    ]


async def test_stream_closes_on_final_status():
    """收到终态帧即收流。

    回归：判据 `FINAL_STATUSES` 定义在 `progress_hub` 模块级，曾被写成
    `GenerationProgressHub.FINAL_STATUSES` —— 类属性不存在，第一条广播帧都抛
    AttributeError，客户端拿到初始快照后即被掐断，端点整体不可用。
    """
    hub = GenerationProgressHub()
    task, frames = await _open_stream(hub, _actor())

    await hub.publish(_SCRIPT_ID, {"status": "succeeded"})
    await asyncio.wait_for(task, timeout=_TIMEOUT)

    assert _statuses(frames) == ["succeeded"]


async def test_stream_keeps_open_on_running_status():
    """非终态帧不收流：继续等下一帧（生成中途不该被提前掐断）。"""
    hub = GenerationProgressHub()
    task, frames = await _open_stream(hub, _actor())

    await hub.publish(_SCRIPT_ID, {"status": "running"})
    await asyncio.sleep(0.05)
    assert not task.done(), "running 帧不应收流"

    await hub.publish(_SCRIPT_ID, {"status": "failed"})
    await asyncio.wait_for(task, timeout=_TIMEOUT)

    assert _statuses(frames) == ["running", "failed"]


async def test_stream_closes_when_initial_snapshot_is_final():
    """订阅一个已落终态的生成：首帧即终态，服务端随即收流（不再只挂心跳）。

    回归：初始快照那帧曾不参与终态判断，与路由 docstring「推完即收流」相悖。
    """
    hub = GenerationProgressHub()
    actor = _actor()
    response = await stream_script_generation(
        _SCRIPT_ID,
        _request(),
        _principal(actor),
        _FakeLibrary(hub, actor, GenerationProgress(status=GenerationStatus.SUCCEEDED)),
    )

    async def _drain() -> list[str]:
        return [frame async for frame in response.body_iterator]

    assert _statuses(await asyncio.wait_for(_drain(), timeout=_TIMEOUT)) == ["succeeded"]
