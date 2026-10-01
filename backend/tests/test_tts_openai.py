"""TTS adapter 测试（issue #63 / ADR-0005 §11）。

- 工厂与端口形状、配置不全时早失败。
- OpenAI 兼容 adapter：请求体形状、响应字节的魔数校验、超时/HTTP/非音频体降级。
- 真实链路 key-gated 冒烟：`WENJING_TEST_TTS=1` 时执行。
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from app.domain.game.tts import TtsPort, VoiceProfile
from app.infrastructure.config import Settings
from app.infrastructure.errx import Error, codes, match_code
from app.infrastructure.media import NullTts, OpenAITts, build_tts
from app.infrastructure.media.tts_openai import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    OPENAI_SPEECH_PATH,
    sniff_audio_mime,
)

_REQUIRE_NETWORK = os.environ.get("WENJING_TEST_TTS") == "1"

_OPEN_CLIENTS: list[httpx.AsyncClient] = []


@pytest.fixture(autouse=True)
async def _close_clients():
    yield
    while _OPEN_CLIENTS:
        await _OPEN_CLIENTS.pop().aclose()


def _mock_client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _OPEN_CLIENTS.append(client)
    return client


def _tts(handler, **kwargs) -> OpenAITts:  # noqa: ANN001
    return OpenAITts(api_key="test-key", client=_mock_client(handler), **kwargs)


def _ok(audio: bytes = b"ID3\x03\x00\x00audio", status: int = 200):  # noqa: ANN001
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=audio)

    return handler


def _voice(voice_id: str = "", speed: float = 1.0) -> VoiceProfile:
    return VoiceProfile(voice_id=voice_id, speed=speed)


# ===== 工厂 =====


def test_null_provider_builds_the_null_port():
    settings = Settings(media_tts_provider="null")
    assert isinstance(build_tts(settings), NullTts)
    assert isinstance(build_tts(settings), TtsPort)


def test_openai_provider_builds_the_adapter():
    settings = Settings(
        media_tts_provider="openai",
        media_tts_api_key="k",
        media_tts_base_url=DEFAULT_BASE_URL,
    )
    assert isinstance(build_tts(settings), OpenAITts)


def test_missing_api_key_fails_fast():
    """配置不全必须启动即报错，不能等到第一句话才发现。"""
    with pytest.raises(Error) as info:
        OpenAITts(api_key="")
    assert match_code(info.value, codes.CFG_MEDIA_TTS_INCOMPLETE)


def test_bad_base_url_fails_fast():
    with pytest.raises(Error) as info:
        OpenAITts(api_key="k", base_url="not-a-url")
    assert match_code(info.value, codes.CFG_MEDIA_TTS_INCOMPLETE)


def test_unknown_provider_is_rejected():
    settings = Settings.model_construct(media_tts_provider="nope")
    with pytest.raises(Error) as info:
        build_tts(settings)
    assert match_code(info.value, codes.CFG_UNKNOWN_MEDIA_PROVIDER)


# ===== 请求形状 =====


async def test_request_body_carries_model_input_voice_and_format():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3audio")

    adapter = _tts(handler)
    await adapter.synthesize(text="路上小心。", voice=_voice("nova"))

    assert seen["url"] == f"{DEFAULT_BASE_URL}{OPENAI_SPEECH_PATH}"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {
        "model": DEFAULT_MODEL,
        "input": "路上小心。",
        "voice": "nova",
        "response_format": "mp3",
    }


async def test_empty_voice_falls_back_to_the_configured_default():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3audio")

    await _tts(handler).synthesize(text="句子。", voice=_voice(""))
    assert seen["body"]["voice"] == DEFAULT_VOICE


async def test_default_speed_is_not_sent():
    """部分兼容 provider 不认 `speed`；默认值不发，省掉一类 400。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3audio")

    await _tts(handler).synthesize(text="句子。", voice=_voice("nova", 1.0))
    assert "speed" not in seen["body"]


async def test_non_default_speed_is_sent():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3audio")

    await _tts(handler).synthesize(text="句子。", voice=_voice("nova", 0.8))
    assert seen["body"]["speed"] == 0.8


# ===== 响应校验 =====


async def test_audio_bytes_pass_through_with_sniffed_content_type():
    """不信任 provider 的 content-type：按魔数定 MIME，前端据此造 Blob。"""
    adapter = _tts(_ok(b"ID3\x03\x00\x00payload"))
    audio = await adapter.synthesize(text="六个字啊。", voice=_voice("nova"))

    assert audio.audio_bytes == b"ID3\x03\x00\x00payload"
    assert audio.content_type == "audio/mpeg"
    assert audio.units == 5
    assert audio.provider == "openai"
    assert audio.model == DEFAULT_MODEL


async def test_wav_magic_is_recognised():
    adapter = _tts(_ok(b"RIFF\x00\x00\x00\x00WAVEfmt "))
    audio = await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert audio.content_type == "audio/wav"


async def test_json_error_body_with_200_is_rejected():
    """provider 把 JSON 错误体当 200 回：落进 `<audio>` 只会静默无声，不如早失败。"""
    adapter = _tts(_ok(b'{"error": "quota exceeded"}'))
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_INVALID)


async def test_empty_body_is_rejected():
    adapter = _tts(_ok(b""))
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_INVALID)


async def test_oversized_audio_is_rejected():
    adapter = _tts(_ok(b"ID3" + b"x" * 100), max_bytes=32)
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_INVALID)


async def test_overlong_text_is_rejected_not_truncated():
    """超长直接截断会念出半句话；宁可拒绝，让上层只丢这一句音频。"""
    adapter = _tts(_ok(), max_chars=4)
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="一二三四五", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_INVALID)


async def test_blank_text_is_rejected():
    adapter = _tts(_ok())
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="   ", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_INVALID)


# ===== 故障映射 =====


async def test_http_error_maps_to_tts_failed():
    adapter = _tts(_ok(b"nope", status=500))
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_FAILED)


async def test_timeout_maps_to_tts_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    adapter = _tts(handler)
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_TIMEOUT)


async def test_transport_error_maps_to_tts_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    adapter = _tts(handler)
    with pytest.raises(Error) as info:
        await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert match_code(info.value, codes.MEDIA_TTS_FAILED)


# ===== 魔数嗅探 =====


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"ID3\x03", "audio/mpeg"),
        (b"\xff\xfb\x90", "audio/mpeg"),
        (b"RIFF\x00\x00\x00\x00WAVE", "audio/wav"),
        (b"OggS\x00", "audio/ogg"),
        (b"fLaC\x00", "audio/flac"),
        (b"\x1aE\xdf\xa3", "audio/webm"),
    ],
)
def test_sniff_audio_mime(data: bytes, expected: str):
    assert sniff_audio_mime(data) == expected


def test_riff_that_is_not_wave_is_not_audio():
    """RIFF 也是 WEBP/AVI 的容器头：只看前四字节会把图片当音频。"""
    assert sniff_audio_mime(b"RIFF\x00\x00\x00\x00WEBP") == ""


def test_unknown_bytes_sniff_to_nothing():
    """嗅探本身只报告事实；是降级还是判失败由 adapter 决定。"""
    assert sniff_audio_mime(b"\x00\x01\x02") == ""


async def test_raw_pcm_format_accepts_headerless_bytes():
    """裸 PCM 没有容器头：认不出属于预期，不能因此判失败。"""
    adapter = _tts(_ok(b"\x00\x01\x02\x03"), response_format="pcm")
    audio = await adapter.synthesize(text="句子。", voice=_voice("nova"))
    assert audio.audio_bytes == b"\x00\x01\x02\x03"
    assert audio.content_type == "audio/L16"


# ===== 真实链路（key-gated）=====


@pytest.mark.skipif(not _REQUIRE_NETWORK, reason="需要 WENJING_TEST_TTS=1 与真实 key")
async def test_real_provider_smoke():
    settings = Settings()
    if not settings.media_tts_api_key:
        pytest.skip("未配置 media_tts_api_key")
    adapter = OpenAITts(
        api_key=settings.media_tts_api_key,
        base_url=settings.media_tts_base_url,
        model=settings.media_tts_model,
    )
    audio = await adapter.synthesize(text="你好。", voice=_voice("alloy"))
    assert audio.audio_bytes
    await adapter._close()
