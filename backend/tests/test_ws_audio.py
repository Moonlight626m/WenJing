"""音轨 WS 端到端（issue #63 / ADR-0005 §11）。

用假的 `TtsPort` 替掉容器里的空实现，让音频真的流过 WS 路由——验的是**协议**
（控制帧 + 二进制帧的次序、无 seq、cancel 生效），不是 provider。

依赖真实 PG；不可用时沿用 `test_api_sessions` 的 client fixture skip。
"""

from __future__ import annotations

import pytest

from app.domain.game.tts import SynthesizedAudio, VoiceProfile
from tests.test_api_sessions import _full_setup
from tests.test_api_sessions import client as _sessions_client  # noqa: F401

#: 能被魔数嗅探认出的最小 MP3 头 + 载荷。
_FAKE_MP3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 32


class _FakeTts:
    """固定产出一段音频；记录被请求过的文本，便于断言"合成了哪几句"。"""

    def __init__(self, *, audio: bytes = _FAKE_MP3) -> None:
        self.texts: list[str] = []
        self._audio = audio

    async def synthesize(self, *, text: str, voice: VoiceProfile) -> SynthesizedAudio:
        self.texts.append(text)
        return SynthesizedAudio(
            audio_bytes=self._audio, content_type="audio/mpeg", provider="fake"
        )

    async def aclose(self) -> None:
        return None


@pytest.fixture(scope="module")
def ws_client(_sessions_client):  # noqa: F811 - 复用 test_api_sessions 的装配
    return _sessions_client


@pytest.fixture
def fake_tts(monkeypatch):
    """把容器的 TTS 端口换成假实现（进程级单例，用例结束自动还原）。"""
    from app.composition import get_container

    container = get_container()
    fake = _FakeTts()
    monkeypatch.setattr(container, "_tts", fake)
    # 音色池也换成可区分的，否则默认池只有一个空 id，断言不出"音色可区分角色"
    monkeypatch.setattr(
        container,
        "_voice_map",
        __import__("app.domain.game.tts", fromlist=["VoiceMap"]).VoiceMap(
            voices=tuple(
                VoiceProfile(voice_id=v) for v in ("v1", "v2", "v3", "v4")
            )
        ),
    )
    return fake


def _submit(ws, sid: str, kind: str, payload: dict | None = None) -> None:
    ws.send_json(
        {
            "type": "submit_command",
            "command": {"session_id": sid, "kind": kind, "payload": payload or {}},
        }
    )


def _drain(ws, until: str) -> list[dict]:
    """收到 `until` 类型的 JSON 消息为止；二进制帧一并收集后丢弃。"""
    msgs: list[dict] = []
    while True:
        message = ws.receive()
        if message["type"] == "websocket.close":
            return msgs
        if message.get("bytes") is not None:
            msgs.append({"type": "_binary", "data": message["bytes"]})
            continue
        import json

        parsed = json.loads(message["text"])
        msgs.append(parsed)
        if parsed["type"] == until:
            return msgs


def test_audio_track_frames_flow_without_seq(ws_client, fake_tts):  # noqa: ANN001
    """验收：音频可播放 —— audio_start → 二进制 → audio_end，且都不带 seq。"""
    sid, role = _full_setup(ws_client)
    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()
        _submit(ws, sid, "select_role", {"role_name": role})
        _drain(ws, "interaction")
        _submit(ws, sid, "free_input", {"text": "我说一句话"})
        messages = _drain(ws, "narrative")

    starts = [m for m in messages if m["type"] == "audio_start"]
    ends = [m for m in messages if m["type"] == "audio_end"]
    binary = [m for m in messages if m["type"] == "_binary"]

    assert starts, "没有音轨：TTS 出口没接上 tee"
    assert len(starts) == len(ends)
    assert binary, "audio_start 之后没有音频字节"
    for message in starts + ends:
        assert "seq" not in message, "瞬态消息不该带 seq（不参与补发）"
        assert message["session_id"] == sid
    assert starts[0]["payload"]["codec"] == "audio/mpeg"
    assert starts[0]["payload"]["speaker"]
    assert starts[0]["payload"]["track_id"] == ends[0]["payload"]["track_id"]
    assert b"".join(m["data"] for m in binary) == _FAKE_MP3 * len(starts)


def test_synthesis_receives_whole_sentences_not_deltas(ws_client, fake_tts):  # noqa: ANN001
    """TTS 出口拿到的必须是**整句**（tee 的分句器攒过），不是逐字增量。"""
    sid, role = _full_setup(ws_client)
    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()
        _submit(ws, sid, "select_role", {"role_name": role})
        _drain(ws, "interaction")
        _submit(ws, sid, "free_input", {"text": "再说一句"})
        _drain(ws, "narrative")

    assert fake_tts.texts, "没有任何句子进合成"
    for text in fake_tts.texts:
        assert text.strip() == text and text, "空句或首尾空白不该送合成"


def test_cancel_audio_is_accepted_and_does_not_disturb_the_command(ws_client, fake_tts):  # noqa: ANN001
    """barge-in 只作用于音轨：取消一条不存在的轨不该影响命令串行。"""
    sid, role = _full_setup(ws_client)
    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()
        _submit(ws, sid, "select_role", {"role_name": role})
        _drain(ws, "interaction")

        ws.send_json({"type": "cancel_audio", "track_id": "does-not-exist"})
        _submit(ws, sid, "free_input", {"text": "打断之后照常推进"})
        messages = _drain(ws, "narrative")

    assert any(m["type"] == "character_speech" for m in messages)
    assert not any(m["type"] == "error" for m in messages)
