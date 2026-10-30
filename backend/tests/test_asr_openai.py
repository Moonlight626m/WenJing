"""ASR adapter 测试（issue #64 / ADR-0005 §11）。

覆盖：工厂与端口形状、配置不全早失败、multipart 请求形状、内容类型白名单、
响应解析与错误映射。真实链路 key-gated 冒烟：`WENJING_TEST_ASR=1`。
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from app.domain.game.asr import AsrPort
from app.infrastructure.config import Settings
from app.infrastructure.errx import Error, codes, match_code
from app.infrastructure.media import NullAsr, OpenAITranscriber, build_asr
from app.infrastructure.media.asr_openai import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OPENAI_TRANSCRIPTIONS_PATH,
    _filename_for,
)

_REQUIRE_NETWORK = os.environ.get("WENJING_TEST_ASR") == "1"

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


def _transcriber(handler, **kwargs) -> OpenAITranscriber:  # noqa: ANN001
    return OpenAITranscriber(api_key="test-key", client=_mock_client(handler), **kwargs)


def _ok(text: str = "我要去城里。", **extra) -> object:  # noqa: ANN003
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"text": text, **extra}))

    return handler


# ===== 工厂 =====


def test_null_provider_builds_the_null_port():
    settings = Settings(media_asr_provider="null")
    assert isinstance(build_asr(settings), NullAsr)
    assert isinstance(build_asr(settings), AsrPort)


def test_openai_provider_builds_the_adapter():
    settings = Settings(
        media_asr_provider="openai",
        media_asr_api_key="k",
        media_asr_base_url=DEFAULT_BASE_URL,
    )
    assert isinstance(build_asr(settings), OpenAITranscriber)


def test_missing_api_key_fails_fast():
    with pytest.raises(Error) as info:
        OpenAITranscriber(api_key="")
    assert match_code(info.value, codes.CFG_MEDIA_ASR_INCOMPLETE)


def test_bad_base_url_fails_fast():
    with pytest.raises(Error) as info:
        OpenAITranscriber(api_key="k", base_url="nope")
    assert match_code(info.value, codes.CFG_MEDIA_ASR_INCOMPLETE)


def test_unknown_provider_is_rejected():
    settings = Settings.model_construct(media_asr_provider="nope")
    with pytest.raises(Error) as info:
        build_asr(settings)
    assert match_code(info.value, codes.CFG_UNKNOWN_MEDIA_PROVIDER)


# ===== 请求形状 =====


async def test_request_is_multipart_with_model_and_language():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["ctype"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, content=json.dumps({"text": "好"}))

    await _transcriber(handler).transcribe(
        audio=b"OggSaudio", content_type="audio/webm", language="zh"
    )

    assert seen["url"] == f"{DEFAULT_BASE_URL}{OPENAI_TRANSCRIPTIONS_PATH}"
    assert seen["auth"] == "Bearer test-key"
    assert seen["ctype"].startswith("multipart/form-data")
    body = seen["body"]
    assert b'name="model"' in body and DEFAULT_MODEL.encode() in body
    assert b'name="language"' in body and b"zh" in body
    assert b'filename="audio.webm"' in body
    assert b"OggSaudio" in body


async def test_language_is_omitted_when_not_given():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, content=json.dumps({"text": "好"}))

    await _transcriber(handler).transcribe(audio=b"OggS", content_type="audio/webm")
    assert b'name="language"' not in seen["body"]


async def test_content_type_with_parameters_is_accepted():
    """MediaRecorder 会给 `audio/webm;codecs=opus`，不该因此被拒。"""
    await _transcriber(_ok()).transcribe(
        audio=b"OggS", content_type="audio/webm;codecs=opus"
    )


async def test_unsupported_content_type_is_rejected_before_the_call():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, content=json.dumps({"text": "好"}))

    with pytest.raises(Error) as info:
        await _transcriber(handler).transcribe(
            audio=b"data", content_type="application/octet-stream"
        )
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)
    assert called is False


async def test_oversized_audio_is_rejected_before_the_call():
    with pytest.raises(Error) as info:
        await _transcriber(_ok(), max_bytes=4).transcribe(
            audio=b"way too long", content_type="audio/webm"
        )
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)


# ===== 响应解析 =====


async def test_text_is_returned_and_stripped():
    result = await _transcriber(_ok("  我要去城里。  ")).transcribe(
        audio=b"OggS", content_type="audio/webm"
    )
    assert result.text == "我要去城里。"
    assert result.provider == "openai"
    assert result.model == DEFAULT_MODEL


async def test_provider_duration_becomes_milliseconds():
    result = await _transcriber(_ok("好", duration=3.5)).transcribe(
        audio=b"OggS", content_type="audio/webm"
    )
    assert result.duration_ms == 3500
    assert result.duration_source == "provider"


async def test_missing_duration_is_reported_as_unknown():
    result = await _transcriber(_ok("好")).transcribe(
        audio=b"OggS", content_type="audio/webm"
    )
    assert result.duration_ms == 0
    assert result.duration_source == "unknown"


async def test_empty_text_in_a_200_body_is_a_failure():
    """provider 用 200 回一个空转写：这是"没听清"，不是"学生没说话"。"""
    with pytest.raises(Error) as info:
        await _transcriber(_ok("   ")).transcribe(audio=b"OggS", content_type="audio/webm")
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)


async def test_non_json_body_is_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    with pytest.raises(Error) as info:
        await _transcriber(handler).transcribe(audio=b"OggS", content_type="audio/webm")
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)


async def test_json_without_text_is_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"error": "nope"}))

    with pytest.raises(Error) as info:
        await _transcriber(handler).transcribe(audio=b"OggS", content_type="audio/webm")
    assert match_code(info.value, codes.MEDIA_ASR_INVALID)


# ===== 故障映射 =====


async def test_http_error_maps_to_asr_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    with pytest.raises(Error) as info:
        await _transcriber(handler).transcribe(audio=b"OggS", content_type="audio/webm")
    assert match_code(info.value, codes.MEDIA_ASR_FAILED)


async def test_timeout_maps_to_asr_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(Error) as info:
        await _transcriber(handler).transcribe(audio=b"OggS", content_type="audio/webm")
    assert match_code(info.value, codes.MEDIA_ASR_TIMEOUT)


async def test_transport_error_maps_to_asr_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(Error) as info:
        await _transcriber(handler).transcribe(audio=b"OggS", content_type="audio/webm")
    assert match_code(info.value, codes.MEDIA_ASR_FAILED)


# ===== 文件名 =====


@pytest.mark.parametrize(
    ("mime", "expected"),
    [
        ("audio/webm", "audio.webm"),
        ("audio/ogg", "audio.ogg"),
        ("audio/mpeg", "audio.mp3"),
        ("audio/mp4", "audio.mp4"),
        ("audio/wav", "audio.wav"),
        ("audio/L16", "audio.pcm"),
    ],
)
def test_filename_follows_the_container(mime: str, expected: str):
    """有些 provider 按扩展名判容器，不能一律叫 audio。"""
    assert _filename_for(mime) == expected


# ===== 真实链路（key-gated）=====


@pytest.mark.skipif(not _REQUIRE_NETWORK, reason="需要 WENJING_TEST_ASR=1 与真实 key")
async def test_real_provider_smoke():
    settings = Settings()
    if not settings.media_asr_api_key:
        pytest.skip("未配置 media_asr_api_key")
    adapter = OpenAITranscriber(
        api_key=settings.media_asr_api_key,
        base_url=settings.media_asr_base_url,
        model=settings.media_asr_model,
    )
    # 一段静音 WAV 即可：验的是链路通不通，不是识别准不准
    import struct

    data_size = 16000 * 2
    wav = (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data"
        + struct.pack("<I", data_size)
        + b"\x00" * data_size
    )
    await adapter.transcribe(audio=wav, content_type="audio/wav", language="zh")
    await adapter.aclose()
