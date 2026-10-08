"""SessionEventHub 单元测试（issue #56）：命令外事件的进程内投递。

不起浏览器、不连库：hub 是纯内存注册表，这里的语义就是 WS 路由依赖的全部契约。
"""

from __future__ import annotations

import asyncio
import uuid

from app.services.session_events import SessionEventHub


def test_publish_without_subscriber_is_not_an_error():
    """玩家不在线不是错误：事件流才是权威，推送只是即时性增强。"""

    async def _run() -> int:
        hub = SessionEventHub()
        return await hub.publish(uuid.uuid4(), [{"type": "asset_ready", "seq": 0}])

    assert asyncio.run(_run()) == 0


async def test_publish_reaches_every_subscriber():
    hub = SessionEventHub()
    sid = uuid.uuid4()
    with hub.subscribe(sid) as first, hub.subscribe(sid) as second:
        assert hub.subscriber_count(sid) == 2
        delivered = await hub.publish(sid, [{"type": "asset_ready", "seq": 3}])
        assert delivered == 2
        for queue in (first, second):
            msg = queue.get_nowait()
            assert msg["type"] == "asset_ready"
            assert msg["seq"] == 3


async def test_unsubscribe_on_exit():
    hub = SessionEventHub()
    sid = uuid.uuid4()
    with hub.subscribe(sid):
        assert hub.subscriber_count(sid) == 1
    assert hub.subscriber_count(sid) == 0
    assert await hub.publish(sid, [{"type": "asset_ready", "seq": 1}]) == 0


async def test_other_session_does_not_receive():
    """按会话隔离：配图是私域资产，串会话推送等于越权换别人的背景。"""
    hub = SessionEventHub()
    mine, other = uuid.uuid4(), uuid.uuid4()
    with hub.subscribe(mine) as queue:
        await hub.publish(other, [{"type": "asset_ready", "seq": 1}])
        assert queue.empty()
        assert await hub.publish(mine, [{"type": "asset_ready", "seq": 1}]) == 1
        assert not queue.empty()


async def test_queue_full_drops_without_raising():
    """满队列丢弃而非阻塞：配图可丢，卡住生成任务不可接受。"""
    hub = SessionEventHub(queue_size=1)
    sid = uuid.uuid4()
    with hub.subscribe(sid) as queue:
        assert await hub.publish(sid, [{"type": "asset_ready", "seq": 1}]) == 1
        # 第二条撑爆队列：不抛异常，也不计入投递数
        assert await hub.publish(sid, [{"type": "asset_ready", "seq": 2}]) == 0
        assert queue.qsize() == 1
        assert queue.get_nowait()["seq"] == 1


async def test_publish_counts_connections_not_messages():
    """计数口径是「收到消息的连接数」：两条消息发给两条连接记 2，不是 4。

    调用方用它回答「这次有没有人在线」，虚高的计数会让日志与告警失真。
    """
    hub = SessionEventHub()
    sid = uuid.uuid4()
    with hub.subscribe(sid) as first, hub.subscribe(sid) as second:
        assert await hub.publish(sid, [{"seq": 1}, {"seq": 2}]) == 2
        assert first.qsize() == 2
        assert second.qsize() == 2


async def test_publish_counts_zero_when_every_queue_is_full():
    """一条都塞不进去记 0（队列大小是 hub 级配置，故不存在部分连接成功的情形）。"""
    hub = SessionEventHub(queue_size=1)
    sid = uuid.uuid4()
    with hub.subscribe(sid) as first, hub.subscribe(sid) as second:
        assert await hub.publish(sid, [{"seq": 1}]) == 2
        assert await hub.publish(sid, [{"seq": 2}]) == 0
        assert first.qsize() == 1 and second.qsize() == 1


async def test_subscribers_are_isolated_queues():
    """一条连接慢不会饿死另一条：各自独立队列，投递按连接计数。"""
    hub = SessionEventHub(queue_size=1)
    sid = uuid.uuid4()
    with hub.subscribe(sid) as slow, hub.subscribe(sid) as fast:
        assert await hub.publish(sid, [{"type": "asset_ready", "seq": 1}]) == 2
        assert slow.get_nowait()["seq"] == 1
        assert fast.get_nowait()["seq"] == 1
        assert await hub.publish(sid, [{"type": "asset_ready", "seq": 2}]) == 2
        assert slow.get_nowait()["seq"] == 2
        assert fast.get_nowait()["seq"] == 2
