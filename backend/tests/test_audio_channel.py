"""连接级音轨出口（issue #63 / ADR-0005 §11）。

覆盖：控制帧与二进制帧的次序、barge-in 取消、整轨淘汰（不截断音频）、
发送失败即停（命令照常跑完）。
"""

from __future__ import annotations

import asyncio
import uuid

from app.services.audio_channel import AudioTrackChannel


class _Recorder:
    """按到达顺序记录两种帧，`kinds` 便于断言交错次序。"""

    def __init__(self) -> None:
        self.json: list[dict] = []
        self.bytes: list[bytes] = []
        self.kinds: list[str] = []

    async def send_json(self, message: dict) -> None:
        self.json.append(message)
        self.kinds.append(message["type"])

    async def send_bytes(self, data: bytes) -> None:
        self.bytes.append(data)
        self.kinds.append("binary")


def _channel(recorder: _Recorder, **kwargs) -> AudioTrackChannel:
    return AudioTrackChannel(uuid.uuid4(), recorder.send_json, recorder.send_bytes, **kwargs)


async def test_frames_arrive_in_start_chunk_end_order():
    """一条音轨的帧序：audio_start → 二进制 → audio_end（前端据此拼 Blob）。"""
    rec = _Recorder()
    channel = _channel(rec)
    track = channel.start("母亲", content_type="audio/mpeg")
    channel.chunk(track, b"ID3part1")
    channel.chunk(track, b"ID3part2")
    channel.end(track)
    await channel.aclose()

    assert rec.kinds == ["audio_start", "binary", "binary", "audio_end"]
    assert b"".join(rec.bytes) == b"ID3part1ID3part2"
    assert rec.json[0]["payload"] == {
        "track_id": track,
        "speaker": "母亲",
        "codec": "audio/mpeg",
        "sample_rate": 0,
    }
    assert rec.json[1]["payload"]["track_id"] == track


async def test_tracks_do_not_interleave_bytes():
    """多音轨并发：各轨字节不串（前端按 track_id 各拼各的 Blob）。"""
    rec = _Recorder()
    channel = _channel(rec)
    first = channel.start("母亲", content_type="audio/mpeg")
    second = channel.start("父亲", content_type="audio/mpeg")
    channel.chunk(first, b"AAA")
    channel.chunk(second, b"BBB")
    channel.end(first)
    channel.end(second)
    await channel.aclose()

    assert rec.bytes == [b"AAA", b"BBB"]
    starts = [m["payload"]["track_id"] for m in rec.json if m["type"] == "audio_start"]
    assert starts == [first, second]


async def test_cancel_drops_the_pending_track():
    """barge-in：取消后该轨的待发帧不再发出（已写进 socket 的收不回来）。"""
    rec = _Recorder()
    channel = _channel(rec)
    track = channel.start("母亲", content_type="audio/mpeg")
    assert channel.cancel(track) is True
    channel.chunk(track, b"late")
    channel.end(track)
    await channel.aclose()

    assert rec.bytes == []
    assert "audio_start" not in rec.kinds


async def test_cancel_of_unknown_track_reports_false():
    """取消一条不存在的轨不算成功（日志里 `cancelled` 字段才有意义）。"""
    rec = _Recorder()
    channel = _channel(rec)
    assert channel.cancel("nope") is False


async def test_cancel_leaves_other_tracks_intact():
    """取消只作用于指定音轨，不误伤并发的另一条。"""
    rec = _Recorder()
    channel = _channel(rec)
    keep = channel.start("父亲", content_type="audio/mpeg")
    drop = channel.start("母亲", content_type="audio/mpeg")
    channel.chunk(keep, b"KEEP")
    channel.chunk(drop, b"DROP")
    channel.cancel(drop)
    channel.end(keep)
    await channel.aclose()

    assert rec.bytes == [b"KEEP"]


async def test_overflow_drops_whole_oldest_track_not_a_truncated_one():
    """溢出丢**整条**最旧的音轨：截断的 MP3 在浏览器里是噪音，比没有更糟。"""
    rec = _Recorder()
    channel = _channel(rec, max_tracks=2)
    old = channel.start("甲", content_type="audio/mpeg")
    channel.chunk(old, b"OLD")
    channel.end(old)
    middle = channel.start("乙", content_type="audio/mpeg")
    channel.chunk(middle, b"MID")
    channel.end(middle)
    # 第三条入队时超限：最旧的「甲」整条（含 audio_end）被丢
    newest = channel.start("丙", content_type="audio/mpeg")
    channel.chunk(newest, b"NEW")
    channel.end(newest)
    await channel.aclose()

    assert rec.bytes == [b"MID", b"NEW"]
    speakers = [m["payload"]["speaker"] for m in rec.json if m["type"] == "audio_start"]
    assert speakers == ["乙", "丙"]


async def test_empty_chunk_is_ignored():
    """空帧不该占缓冲（provider 可能回空段）。"""
    rec = _Recorder()
    channel = _channel(rec)
    track = channel.start("母亲", content_type="audio/mpeg")
    channel.chunk(track, b"")
    channel.end(track)
    await channel.aclose()
    assert rec.kinds == ["audio_start", "audio_end"]


async def test_send_failure_stops_the_channel_without_raising():
    """连接没了：通道静默停摆，命令照常跑完落库（事件才是权威）。"""

    class _Broken:
        async def send_json(self, message: dict) -> None:
            raise ConnectionError("client gone")

        async def send_bytes(self, data: bytes) -> None:
            raise ConnectionError("client gone")

    channel = AudioTrackChannel(uuid.uuid4(), _Broken().send_json, _Broken().send_bytes)
    track = channel.start("母亲", content_type="audio/mpeg")
    channel.chunk(track, b"data")
    channel.end(track)
    await channel.aclose()  # 不抛

    # 通道已关：后续写入静默丢弃，不再试图发送
    channel.start("父亲", content_type="audio/mpeg")
    await channel.aclose()


async def test_close_timeout_does_not_hang_the_command():
    """慢客户端不能把 WS 处理循环拖住（冲刷有上限）。"""

    class _Stalled:
        async def send_json(self, message: dict) -> None:
            await asyncio.sleep(30)

        async def send_bytes(self, data: bytes) -> None:
            await asyncio.sleep(30)

    channel = AudioTrackChannel(uuid.uuid4(), _Stalled().send_json, _Stalled().send_bytes)
    track = channel.start("母亲", content_type="audio/mpeg")
    channel.chunk(track, b"data")
    await asyncio.wait_for(channel.aclose(), timeout=5)


async def test_flush_keeps_the_channel_open_for_the_next_command():
    """命令返回时只 `flush`，不 `aclose`。

    音轨出口是**连接级**的，而命令是一条条来的。若每条命令都关掉通道，`_closing`
    在第一条命令后就永久置位，第二条命令的音频会被静默吞掉——只有第一个说话的
    角色有声音。这个 bug 被 WS 端到端用例逮住，这里把它钉在单元层。
    """
    rec = _Recorder()
    channel = _channel(rec)
    first = channel.start("母亲", content_type="audio/mpeg")
    channel.chunk(first, b"FIRST")
    channel.end(first)
    await channel.flush()

    # 第二条命令：通道仍然可用
    second = channel.start("父亲", content_type="audio/mpeg")
    channel.chunk(second, b"SECOND")
    channel.end(second)
    await channel.flush()

    assert rec.bytes == [b"FIRST", b"SECOND"]


async def test_flush_returns_immediately_when_nothing_is_pending():
    """空队列的 `flush` 不能等满超时（否则每条命令白等 1 秒）。"""
    rec = _Recorder()
    channel = _channel(rec)
    await asyncio.wait_for(channel.flush(), timeout=0.2)


async def test_cancel_after_close_is_a_no_op():
    """连接已关：`cancel` 不该抛，也不该谎报取消成功。"""
    rec = _Recorder()
    channel = _channel(rec)
    track = channel.start("母亲", content_type="audio/mpeg")
    await channel.aclose()
    assert channel.cancel(track) is False


async def test_close_is_safe_when_nothing_was_sent():
    """从未入队过帧时 `aclose` 是空操作（不能因为没 worker 就抛）。"""
    rec = _Recorder()
    channel = _channel(rec)
    await channel.aclose()
    assert rec.kinds == []


async def test_channel_satisfies_the_audio_track_sink_protocol():
    """`TtsSynthesizer` 只认 `AudioTrackSink`；形状对不上会在运行期静默丢音。"""
    from app.domain.game.tts import AudioTrackSink

    rec = _Recorder()
    assert isinstance(_channel(rec), AudioTrackSink)
