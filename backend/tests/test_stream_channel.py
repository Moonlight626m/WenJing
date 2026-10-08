"""瞬态流出口的缓冲/取消语义测试（issue #60 / ADR-0005 §10）。

不起 DB、不起 WS：直接对着 `StreamChannel` 验证三条取舍——有界缓冲 drop-oldest、
收流必冲刷、连接坏了就静默停（命令不受影响）。
"""

from __future__ import annotations

import asyncio

from app.services.stream_channel import StreamChannel


def _collector(sent: list[dict]):
    async def _send(message: dict) -> None:
        sent.append(message)

    return _send


async def test_messages_are_flushed_in_order_on_close():
    sent: list[dict] = []
    channel = StreamChannel("s1", _collector(sent))

    stream_id = channel.start("杜甫")
    channel.delta(stream_id, "我提议")
    channel.delta(stream_id, "按进度")
    channel.end(stream_id)
    await channel.aclose()

    assert [m["type"] for m in sent] == [
        "stream_start",
        "stream_delta",
        "stream_delta",
        "stream_end",
    ]
    assert sent[0]["payload"] == {"stream_id": stream_id, "speaker": "杜甫"}
    assert [m["payload"]["text"] for m in sent[1:3]] == ["我提议", "按进度"]
    assert all(m["session_id"] == "s1" for m in sent)


async def test_empty_delta_is_not_sent():
    """空的增量不占缓冲也不发：provider 的空段不该变成一条空字幕。"""
    sent: list[dict] = []
    channel = StreamChannel("s1", _collector(sent))
    stream_id = channel.start("杜甫")
    channel.delta(stream_id, "")
    channel.end(stream_id)
    await channel.aclose()
    assert [m["type"] for m in sent] == ["stream_start", "stream_end"]


async def test_buffer_overflow_drops_oldest_delta_keeping_the_stream_start():
    """慢客户端：缓冲满了丢**最旧的字幕增量**，保住最新字幕与那条流的骨架。"""
    sent: list[dict] = []
    gate = asyncio.Event()

    async def _slow_send(message: dict) -> None:
        await gate.wait()
        sent.append(message)

    channel = StreamChannel("s1", _slow_send, buffer_size=3)
    stream_id = channel.start("杜甫")
    for index in range(10):
        channel.delta(stream_id, f"第{index}段")

    gate.set()
    await channel.aclose()

    assert len(sent) == 3, "缓冲区只留得下 3 条"
    assert sent[0]["type"] == "stream_start", "流的骨架不参与淘汰"
    assert [m["payload"].get("text", "") for m in sent[1:]] == ["第8段", "第9段"]


async def test_stream_end_survives_overflow():
    """`stream_end` 被挤掉，前端就会留着一条永远"还在长"的字幕——它不能被 drop。"""
    sent: list[dict] = []
    gate = asyncio.Event()

    async def _slow_send(message: dict) -> None:
        await gate.wait()
        sent.append(message)

    channel = StreamChannel("s1", _slow_send, buffer_size=2)
    stream_id = channel.start("杜甫")
    channel.delta(stream_id, "第一段")
    channel.delta(stream_id, "第二段")
    channel.end(stream_id)

    gate.set()
    await channel.aclose()

    assert [m["type"] for m in sent] == ["stream_start", "stream_end"]


async def test_closed_channel_stops_sending_after_connection_loss():
    """连接没了：后续 delta 静默丢弃，既不再尝试发送，也不抛回命令路径。"""
    attempts = 0

    async def _broken_send(message: dict) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("client gone")

    channel = StreamChannel("s1", _broken_send)
    stream_id = channel.start("杜甫")
    channel.delta(stream_id, "第一段")
    await channel.aclose()
    after_failure = attempts

    channel.delta(stream_id, "第二段")  # 不抛异常
    channel.end(stream_id)
    await channel.aclose()  # 可重入

    assert after_failure == 1, "首条发送失败即停"
    assert attempts == after_failure, "关闭后不得再尝试发送"


async def test_close_times_out_on_stalled_client():
    """发送卡死：收流有上限，不能把 WS 处理循环拖住。"""
    async def _stalled_send(message: dict) -> None:
        await asyncio.sleep(60)

    channel = StreamChannel("s1", _stalled_send)
    stream_id = channel.start("杜甫")
    channel.delta(stream_id, "卡住的一段")

    await asyncio.wait_for(channel.aclose(), timeout=5)
