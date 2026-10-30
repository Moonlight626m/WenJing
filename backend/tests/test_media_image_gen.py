"""生图 adapter 测试（issue #46 / ADR-0005 §2/§6）。

- 工厂与端口形状、尺寸映射（16:9/1:1 理想尺寸 → provider 档位）、安全过滤（生成前）。
- OpenAI 兼容 adapter：mock 响应映射（b64_json / url）、请求体、超时/HTTP/坏字节降级、
  以及「违禁 prompt 绝不发往 provider」这一付费前闸门。
- 真实链路 key-gated 冒烟：`WENJING_TEST_IMAGE_GEN=1` 时执行。
"""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO

import httpx
import pytest

from app.domain.game.media import ASSET_SIZES, AssetKind, ImageGenPort
from app.domain.game.media_safety import MAX_PROMPT_CHARS, inspect_prompt
from app.infrastructure.config import Settings
from app.infrastructure.errx import Error, codes, match_code
from app.infrastructure.media import NullImageGen, OpenAIImageGen, build_image_gen
from app.infrastructure.media.image_gen_openai import (
    DEFAULT_BASE_URL,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_GEN_MAX_BYTES,
    DEFAULT_MODEL,
    DEFAULT_READ_TIMEOUT,
    SIZE_MODE_EXACT,
    image_dimensions,
    sniff_image_mime,
)

_REQUIRE_NETWORK = os.environ.get("WENJING_TEST_IMAGE_GEN") == "1"

# 每个用例自建 httpx client，用 autouse fixture 统一收口，避免泄漏连接（评审发现）。
_OPEN_CLIENTS: list[httpx.AsyncClient] = []


@pytest.fixture(autouse=True)
async def _close_clients():
    yield
    while _OPEN_CLIENTS:
        await _OPEN_CLIENTS.pop().aclose()


def _png_bytes(width: int = 4, height: int = 4) -> bytes:
    """真实可解 PNG（尺寸断言需要 Pillow 能读出真宽高）。"""
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


_PNG = _png_bytes()
_JPEG = b"\xff\xd8\xff\xe0" + b"fake-image-payload"


def _mock_client(handler) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _OPEN_CLIENTS.append(client)
    return client


def _allow_all(_url: str) -> None:
    return None


def _gen(handler, *, validator=_allow_all, **kwargs) -> OpenAIImageGen:
    # validator 会**替换** SafePageFetcher 内置的 DNS/SSRF 校验（见 safe_fetcher.py），
    # 因此 mock 域名用例传 _allow_all 绕开解析；SSRF 用例必须传 None 验真实闸门。
    return OpenAIImageGen(
        api_key="test-key",
        client=_mock_client(handler),
        validator=validator,
        **kwargs,
    )


def _b64_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_PNG).decode()}]})


def _calls(handler):
    """包一层记录请求，供「违禁 prompt 不发请求」类断言使用。"""
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return wrapped, seen


# ===== 工厂与端口形状 =====


def test_build_image_gen_null_by_default():
    assert isinstance(build_image_gen(Settings(media_image_gen_provider="null")), NullImageGen)


def test_build_image_gen_openai_satisfies_port():
    gen = build_image_gen(Settings(media_image_gen_provider="openai", media_image_gen_api_key="k"))
    assert isinstance(gen, OpenAIImageGen)
    assert isinstance(gen, ImageGenPort)


def test_build_image_gen_openai_without_key_is_config_error():
    with pytest.raises(Error) as excinfo:
        build_image_gen(Settings(media_image_gen_provider="openai", media_image_gen_api_key=""))
    assert match_code(excinfo.value, codes.CFG_MEDIA_IMAGE_GEN_INCOMPLETE)


def test_adapter_defaults_match_settings_defaults():
    """模块常量与 Settings 默认值是两份副本，靠本用例防止分叉（评审发现）。"""
    settings = Settings()
    assert settings.media_image_gen_base_url == DEFAULT_BASE_URL
    assert settings.media_image_gen_model == DEFAULT_MODEL
    assert settings.media_image_gen_connect_timeout == DEFAULT_CONNECT_TIMEOUT
    assert settings.media_image_gen_read_timeout == DEFAULT_READ_TIMEOUT
    assert settings.media_image_gen_max_bytes == DEFAULT_GEN_MAX_BYTES
    assert settings.media_image_gen_max_prompt_chars == MAX_PROMPT_CHARS


# ===== 尺寸：理想比例 → provider 档位 =====


def test_asset_sizes_match_adr_ratios():
    w, h = ASSET_SIZES[AssetKind.BACKGROUND]
    assert w * 9 == h * 16  # 16:9
    aw, ah = ASSET_SIZES[AssetKind.AVATAR]
    assert aw == ah  # 1:1


async def test_preset_mode_maps_ratio_to_provider_supported_size():
    """gpt-image-1 只认固定档位；直发 1280x720 会 400（评审发现的高严重度问题）。"""
    handler, seen = _calls(_b64_response)
    gen = _gen(handler)
    await gen.generate(prompt="江南水乡黄昏", kind=AssetKind.BACKGROUND)
    await gen.generate(prompt="人物头像", kind=AssetKind.AVATAR)
    sizes = [json.loads(r.read())["size"] for r in seen]
    assert sizes == ["1536x1024", "1024x1024"]  # 横版 / 方版，均为 provider 支持值


async def test_exact_mode_sends_requested_size():
    handler, seen = _calls(_b64_response)
    gen = _gen(handler, size_mode=SIZE_MODE_EXACT)
    await gen.generate(prompt="江南水乡黄昏", kind=AssetKind.BACKGROUND)
    assert json.loads(seen[0].read())["size"] == "1280x720"


async def test_partial_size_dimension_is_derived_not_dropped():
    """只给一维时按 kind 比例补另一维，而不是静默丢弃（评审发现）。"""
    handler, seen = _calls(_b64_response)
    gen = _gen(handler, size_mode=SIZE_MODE_EXACT)
    await gen.generate(prompt="头像", kind=AssetKind.AVATAR, width=1024)
    assert json.loads(seen[0].read())["size"] == "1024x1024"


# ===== 生成后：字节嗅探、真实尺寸与校验 =====


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (_PNG, "image/png"),
        (_JPEG, "image/jpeg"),
        (b"GIF89a" + b"\x00" * 8, "image/gif"),
        (b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8, "image/webp"),
        (b"\x00\x00\x00\x20ftypavif" + b"\x00" * 8, "image/avif"),
        (b"<html>not an image</html>", None),
        (b"", None),
    ],
)
def test_sniff_image_mime(data, expected):
    assert sniff_image_mime(data) == expected


def test_image_dimensions_reads_header():
    assert image_dimensions(_png_bytes(7, 5)) == (7, 5)
    assert image_dimensions(b"not an image") == (0, 0)  # 读不出不抛，交由上层降级


async def test_generate_reports_real_dimensions_not_requested():
    """provider 可能取整/忽略 size；回填请求值会让 assets 元数据说谎（评审发现）。"""
    image = await _gen(_b64_response).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert (image.width, image.height) == (4, 4)  # 真实字节是 4x4，而非请求的 1280x720
    assert image.content_type == "image/png"
    assert image.image_bytes == _PNG


async def test_generate_rejects_garbage_bytes():
    payload = base64.b64encode(b"junk").decode()
    handler = lambda _r: httpx.Response(200, json={"data": [{"b64_json": payload}]})  # noqa: E731
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_INVALID)


async def test_generate_rejects_oversized_image():
    with pytest.raises(Error) as excinfo:
        await _gen(_b64_response, max_bytes=4).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_INVALID)


@pytest.mark.parametrize(
    "encoded",
    [
        pytest.param(lambda b: base64.b64encode(b).decode(), id="standard"),
        pytest.param(lambda b: base64.urlsafe_b64encode(b).decode(), id="urlsafe"),
        pytest.param(lambda b: base64.encodebytes(b).decode(), id="wrapped-newlines"),
        pytest.param(lambda b: base64.b64encode(b).decode().rstrip("="), id="no-padding"),
    ],
)
async def test_b64_variants_accepted(encoded):
    """兼容 provider 的 base64 变体不该被当成坏图（评审发现的换厂商假失败）。"""
    payload = encoded(_PNG)
    handler = lambda _r: httpx.Response(200, json={"data": [{"b64_json": payload}]})  # noqa: E731
    image = await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert image.image_bytes == _PNG


# ===== 生成前：违禁 prompt 是付费前的闸门 =====


async def test_blocked_prompt_never_reaches_provider():
    handler, seen = _calls(_b64_response)
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="需要一些 nsfw 内容", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_BLOCKED)
    assert seen == []  # 关键：命中即拒，绝不产生付费调用


async def test_empty_and_overlong_prompts_rejected():
    gen = _gen(_b64_response)
    for prompt in ("", "   ", "背" * (MAX_PROMPT_CHARS + 1)):
        with pytest.raises(Error) as excinfo:
            await gen.generate(prompt=prompt, kind=AssetKind.BACKGROUND)
        assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_BLOCKED)


@pytest.mark.parametrize(
    "blocked",
    ["一段nsfw画面", "画个nsfw图", "不要出现naked人物", "一段 suicide 描写", "真实人物照片"],
)
def test_inspect_prompt_catches_cjk_adjacent_ascii(blocked):
    """回归：\\b 把 CJK 当词字符，会让中文紧贴的英文违禁词全部漏检（评审发现）。"""
    assert not inspect_prompt(blocked).ok


def test_inspect_prompt_avoids_substring_false_positives():
    assert inspect_prompt("a gorgeous mountain landscape").ok
    assert inspect_prompt("a denuded forest").ok
    assert inspect_prompt("一幅宁静的江南水乡背景，黄昏").ok


# ===== provider 故障与降级 =====


async def test_timeout_maps_to_timeout_code():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_TIMEOUT)


async def test_http_status_error_maps_to_failed_code():
    handler = lambda _r: httpx.Response(429, json={"error": {"message": "rate limited"}})  # noqa: E731
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_FAILED)


async def test_top_level_error_body_is_not_swallowed():
    """兼容网关常见「200 + 顶层 error」；真实原因不该退化成 empty data array。"""
    handler = lambda _r: httpx.Response(  # noqa: E731
        200, json={"error": {"message": "content policy violation"}}
    )
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_BLOCKED)
    assert "policy" in excinfo.value.msg


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(None, id="json-null"),
        pytest.param({"data": {"b64_json": "x"}}, id="data-is-object"),
        pytest.param({"data": ["not-a-dict"]}, id="data0-is-string"),
        pytest.param({"data": [{"b64_json": 123}]}, id="b64-not-string"),
        pytest.param({"data": []}, id="empty-data"),
    ],
)
async def test_malformed_bodies_raise_coded_errors(body):
    """本模块承诺失败只抛 MEDIA_IMAGE_GEN_*；裸 AttributeError/TypeError 会击穿 #47 的降级。"""
    handler = lambda _r: httpx.Response(200, json=body)  # noqa: E731
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert excinfo.value.code in (
        codes.MEDIA_IMAGE_GEN_FAILED,
        codes.MEDIA_IMAGE_GEN_INVALID,
    )


async def test_provider_side_rejection_maps_to_blocked():
    handler = lambda _r: httpx.Response(  # noqa: E731
        200, json={"data": [{"error": "content policy violation"}]}
    )
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_BLOCKED)


# ===== 构造期校验与请求契约 =====


@pytest.mark.parametrize("bad_url", ["", "api.openai.com/v1", "ftp://x/y"])
def test_invalid_base_url_fails_at_construction(bad_url):
    """留空 base_url 会在首个请求才炸，且被兜成 provider 故障（评审发现）。"""
    with pytest.raises(Error) as excinfo:
        OpenAIImageGen(api_key="k", base_url=bad_url)
    assert match_code(excinfo.value, codes.CFG_MEDIA_IMAGE_GEN_INCOMPLETE)


async def test_sends_authorization_and_optional_response_format():
    handler, seen = _calls(_b64_response)
    gen = _gen(handler, response_format="b64_json")
    await gen.generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert seen[0].headers["authorization"] == "Bearer test-key"
    assert json.loads(seen[0].read())["response_format"] == "b64_json"


async def test_close_is_idempotent_and_safe_without_owned_client():
    gen = OpenAIImageGen(api_key="k")  # 自建 client
    await gen.close()
    await gen.close()


# ===== url 形态产物（部分兼容 provider 只回 url）=====


def _url_handler(remote_url: str, *, fetch_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": remote_url}]})
        if fetch_status != 200:
            return httpx.Response(fetch_status)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=_PNG)

    return handler


async def test_generate_downloads_url_variant():
    image = await _gen(_url_handler("https://cdn.example.com/a.png")).generate(
        prompt="黄昏", kind=AssetKind.BACKGROUND
    )
    assert image.content_type == "image/png"
    assert image.image_bytes == _PNG


async def test_url_variant_fetch_failure_maps_to_failed():
    handler = _url_handler("https://cdn.example.com/a.png", fetch_status=404)
    with pytest.raises(Error) as excinfo:
        await _gen(handler).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_FAILED)


async def test_url_variant_blocks_private_target():
    """产物 URL 走 SSRF 校验；不能因为「是 provider 给的下载地址」就放行内网。"""
    handler = _url_handler("http://169.254.169.254/a.png")
    with pytest.raises(Error) as excinfo:
        await _gen(handler, validator=None).generate(prompt="黄昏", kind=AssetKind.BACKGROUND)
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_GEN_BLOCKED)


# ===== 真实链路 key-gated 冒烟 =====


@pytest.mark.skipif(
    not _REQUIRE_NETWORK,
    reason="真实生图冒烟需 WENJING_TEST_IMAGE_GEN=1 且配置 provider（key-gated）",
)
async def test_real_provider_smoke():
    settings = Settings()
    if settings.media_image_gen_provider == "null":
        pytest.skip("未配置真实生图 provider")
    gen = build_image_gen(settings)
    image = await gen.generate(prompt="中国江南水乡黄昏，无人，写实风格", kind=AssetKind.BACKGROUND)
    assert sniff_image_mime(image.image_bytes) is not None
    assert image.width > 0 and image.height > 0
