"""语音识别端口与编排（issue #64 / ADR-0005 §11/§12）。

三条验收：语音输入可用、隐私/权限合规、失败可回退键盘。本模块覆盖领域侧；
adapter 的请求形状与错误映射在 `test_asr_openai.py`。
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.game.asr import AsrTranscriber, Transcript, TranscriptionRequest
from app.domain.game.media import MediaKind, MediaUsage
from app.infrastructure.errx import Error, codes, match_code


class _FakePort:
    def __init__(self, *, text: str = "我说的话", duration_ms: int = 0, fail: bool = False):
        self.calls: list[tuple[bytes, str, str]] = []
        self._text = text
        self._duration_ms = duration_ms
        self._fail = fail

    async def transcribe(
        self, *, audio: bytes, content_type: str, language: str = ""
    ) -> Transcript:
        self.calls.append((audio, content_type, language))
        if self._fail:
            raise RuntimeError("provider down")
        return Transcript(
            text=self._text,
            duration_ms=self._duration_ms,
            duration_source="provider" if self._duration_ms else "unknown",
            provider="fake",
            model="fake-1",
        )

    async def aclose(self) -> None:
        return None


class _FakeMeter:
    def __init__(self) -> None:
        self.records: list[MediaUsage] = []

    async def record(self, usage: MediaUsage) -> None:
        self.records.append(usage)


class _FakeQuota:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.requests: list[tuple[uuid.UUID, MediaKind, int]] = []

    async def try_acquire(self, *, org_id, kind, units=1):  # noqa: ANN001, ANN003
        self.requests.append((org_id, kind, units))
        return self.allow

    async def check(self, *, org_id, kind, units=1):  # noqa: ANN001, ANN003
        return self.allow

    async def consume(self, *, org_id, kind, units=1) -> None:  # noqa: ANN001, ANN003
        return None


def _request(**overrides) -> TranscriptionRequest:  # noqa: ANN003
    base = {
        "audio_bytes": b"OggSfake-audio",
        "content_type": "audio/webm",
        "client_duration_ms": 3000,
        "language": "zh",
        "org_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "script_id": 7,
        "session_id": uuid.uuid4(),
    }
    base.update(overrides)
    return TranscriptionRequest(**base)


async def test_transcription_returns_the_text():
    """验收一：语音输入可用——一段音频换回一段文本。"""
    port = _FakePort(text="我要去城里。")
    result = await AsrTranscriber(port=port).transcribe(_request())

    assert result.text == "我要去城里。"
    assert port.calls[0][0] == b"OggSfake-audio"
    assert port.calls[0][1] == "audio/webm"
    assert port.calls[0][2] == "zh"


async def test_empty_transcription_is_a_failure_not_silence():
    """没听清要**报错**，不能当成"学生什么都没说"。

    后者会往事件流里塞一条空发言，把剧情推进卡在一个无意义的节点上。
    """
    with pytest.raises(Error) as info:
        await AsrTranscriber(port=_FakePort(text="   ")).transcribe(_request())
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)


async def test_empty_audio_is_rejected_before_the_paid_call():
    port = _FakePort()
    with pytest.raises(Error) as info:
        await AsrTranscriber(port=port).transcribe(_request(audio_bytes=b""))
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)
    assert port.calls == []


async def test_oversized_audio_is_rejected_before_the_paid_call():
    port = _FakePort()
    synth = AsrTranscriber(port=port, max_audio_bytes=16)
    with pytest.raises(Error) as info:
        await synth.transcribe(_request(audio_bytes=b"x" * 32))
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)
    assert port.calls == []


async def test_provider_failure_propagates_so_the_ui_can_fall_back():
    """验收三：失败可回退键盘——所以异常必须**冒出去**，不能像配音那样静默。

    配音是输出（哑一条无所谓），识别是输入（吞掉就等于把学生的话弄丢了）。
    """
    with pytest.raises(RuntimeError):
        await AsrTranscriber(port=_FakePort(fail=True)).transcribe(_request())


async def test_quota_gate_runs_before_the_paid_call():
    """ADR-0005 §12：付费调用前 check+consume，口径是**秒**。"""
    port, quota = _FakePort(), _FakeQuota()
    request = _request(client_duration_ms=5000)
    await AsrTranscriber(port=port, quota=quota).transcribe(request)

    assert quota.requests == [(request.org_id, MediaKind.ASR, 5)]
    assert len(port.calls) == 1


async def test_exhausted_quota_blocks_the_call():
    port = _FakePort()
    with pytest.raises(Error) as info:
        await AsrTranscriber(port=port, quota=_FakeQuota(allow=False)).transcribe(
            _request()
        )
    assert match_code(info.value, codes.MEDIA_ASR_FAILED)
    assert port.calls == []


async def test_client_reported_duration_is_clamped():
    """客户端上报的时长只能**少算**不能多算：伪造一条请求吃光额度是不可接受的。"""
    quota = _FakeQuota()
    await AsrTranscriber(port=_FakePort(), quota=quota, max_seconds=10).transcribe(
        _request(client_duration_ms=999_000)
    )
    assert quota.requests[0][2] == 10


async def test_unknown_duration_counts_as_one_second():
    """量不出时长时按 1 秒计：既不白送也不把一条合法请求拦掉。"""
    quota = _FakeQuota()
    await AsrTranscriber(port=_FakePort(), quota=quota).transcribe(
        _request(client_duration_ms=0)
    )
    assert quota.requests[0][2] == 1


async def test_usage_lands_in_media_usage_without_the_transcript():
    """验收：用量入 `media_usage`（kind=asr，units=秒）——但 `meta` 里**不能**有转写文本。

    计量表不该成为学生语音的第二份副本。
    """
    meter = _FakeMeter()
    request = _request(client_duration_ms=4000)
    await AsrTranscriber(port=_FakePort(text="这是学生说的话"), meter=meter).transcribe(
        request
    )

    assert len(meter.records) == 1
    usage = meter.records[0]
    assert usage.kind is MediaKind.ASR
    assert usage.units == 4
    assert usage.size == len(request.audio_bytes)
    assert (usage.org_id, usage.user_id, usage.script_id, usage.session_id) == (
        request.org_id,
        request.user_id,
        request.script_id,
        request.session_id,
    )
    assert "这是学生说的话" not in str(usage.meta)


async def test_provider_reported_duration_wins_over_the_client():
    meter = _FakeMeter()
    await AsrTranscriber(
        port=_FakePort(duration_ms=7000), meter=meter
    ).transcribe(_request(client_duration_ms=1000))
    assert meter.records[0].meta["duration_ms"] == 7000
    assert meter.records[0].meta["duration_source"] == "provider"


async def test_meter_failure_does_not_lose_the_transcription():
    class _BoomMeter:
        async def record(self, usage: MediaUsage) -> None:
            raise RuntimeError("db down")

    result = await AsrTranscriber(
        port=_FakePort(text="照常返回"), meter=_BoomMeter()
    ).transcribe(_request())
    assert result.text == "照常返回"


async def test_transcriber_never_logs_the_transcript():
    """隐私：转写文本不进日志（用 probe logger，`caplog` 在整套跑时不可靠）。"""
    import logging

    from app.domain.game import asr as asr_module

    class _Probe(logging.Logger):
        def __init__(self) -> None:
            super().__init__("probe")
            self.messages: list[str] = []

        def warning(self, msg, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            self.messages.append(msg % args if args else str(msg))

    probe = _Probe()
    original = asr_module.logger
    asr_module.logger = probe  # type: ignore[assignment]
    try:
        await AsrTranscriber(port=_FakePort(text="秘密内容"), meter=_FakeMeter()).transcribe(
            _request()
        )
        await AsrTranscriber(port=_FakePort(text="秘密内容")).transcribe(_request())
    finally:
        asr_module.logger = original  # type: ignore[assignment]

    assert all("秘密内容" not in message for message in probe.messages)


async def test_transcriber_satisfies_the_port_shape():
    """形状对不上会在运行期静默失败。"""
    from app.domain.game.asr import AsrPort

    assert isinstance(_FakePort(), AsrPort)
