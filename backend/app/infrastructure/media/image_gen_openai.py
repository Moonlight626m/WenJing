"""OpenAI 兼容文生图 adapter（ADR-0005 §2/§6，issue #46）。

- `POST {base}/images/generations`：OpenAI Images API 形状，返回 `b64_json` 或 `url`。
  选兼容形状而非厂商专属任务式 API，是为了换 provider 不改 adapter——阿里百炼、
  智谱、硅基流动等也暴露兼容端点（provider 选型仍是 ADR-0005 的待定项）。
- **尺寸**：`domain` 的 `ASSET_SIZES` 给出理想像素（背景 16:9、头像 1:1）；但
  gpt-image-1 这类 provider **只认固定档位**（1024x1024 / 1536x1024 / 1024x1536），
  直接发 1280x720 会 400。故 adapter 按宽高比把理想尺寸映射到档位（`size_mode="preset"`，
  默认）；接受任意 WxH 的兼容 provider 用 `size_mode="exact"` 直发。
- **安全过滤**：付费调用前先过 `screen_generation_prompt`（本地确定性判定）；产物字节
  再校验魔数与体积，下载 `url` 形态产物时复用 `SafePageFetcher`（SSRF/DNS/超时约束）。
- 失败**一律**抛 `MEDIA_IMAGE_GEN_*`：上层（#47）只 catch `Error` 做占位降级，
  任何裸异常穿透都会把它变成 500。
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from io import BytesIO

import httpx

from app.domain.game.media import ASSET_SIZES, AssetKind, GeneratedImage
from app.domain.game.media_safety import MAX_PROMPT_CHARS, screen_generation_prompt
from app.infrastructure.errx import Error, codes, new, wrap
from app.infrastructure.media.image_search_common import build_image_fetcher

OPENAI_IMAGES_PATH = "/images/generations"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_CONNECT_TIMEOUT = 5.0
# 生图明显慢于检索：单张 16:9 常见 10–40s，读超时给足但仍设上界。
DEFAULT_READ_TIMEOUT = 90.0
DEFAULT_GEN_MAX_BYTES = 16 * 1024 * 1024

SIZE_MODE_PRESET = "preset"
SIZE_MODE_EXACT = "exact"
# gpt-image-1 支持的档位（另有 auto）；按宽高比选最近的一档。
DEFAULT_PRESET_SIZES: Mapping[str, str] = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
}
# 宽高比落档阈值：>1.15 判横、<0.87 判竖，之间算方（16:9≈1.78、1:1=1.0、3:4≈0.75）。
_LANDSCAPE_MIN_RATIO = 1.15
_PORTRAIT_MAX_RATIO = 0.87

# 字节级魔数嗅探：不信任 provider 声明的 content-type。
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff_image_mime(data: bytes) -> str | None:
    """按魔数识别图片类型；无法识别返回 None（含 WEBP/AVIF 的 RIFF/ftyp 分支）。"""
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"mif1"):
            return "image/heic"
    return None


def image_dimensions(data: bytes) -> tuple[int, int]:
    """读图片头拿**真实**宽高；读不出返回 (0, 0)（元数据失败不该阻断主流程）。"""
    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - 尺寸是元数据，解不出不影响图本身可用
        return 0, 0


def _decode_b64(value: object) -> bytes:
    """宽松解码 provider 的 base64：去空白、补 padding、兼容 URL-safe 变体。

    `validate=True` 会误杀兼容 provider 常见的换行/省略 padding/URL-safe 输出，
    把合法图片判成坏图（换厂商时的典型假失败）。
    """
    if not isinstance(value, str):
        raise new(
            codes.MEDIA_IMAGE_GEN_INVALID,
            extra={"reason": f"b64_json is not a string ({type(value).__name__})"},
        )
    cleaned = "".join(value.split())
    cleaned = cleaned.replace("-", "+").replace("_", "/")
    cleaned += "=" * (-len(cleaned) % 4)
    try:
        return base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise wrap(exc, codes.MEDIA_IMAGE_GEN_INVALID, extra={"reason": "bad base64"}) from exc


class OpenAIImageGen:
    """`ImageGenPort` 的 OpenAI 兼容实现。"""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_GEN_MAX_BYTES,
        max_prompt_chars: int = MAX_PROMPT_CHARS,
        # 兼容 provider：多数认 "b64_json"/"url"；gpt-image-1 不接受该参数，故默认不发。
        response_format: str | None = None,
        size_mode: str = SIZE_MODE_PRESET,
        preset_sizes: Mapping[str, str] | None = None,
        validator: Callable[[str], None] | None = None,
    ) -> None:
        if not api_key:
            raise new(codes.CFG_MEDIA_IMAGE_GEN_INCOMPLETE, extra={"missing": "api_key"})
        if not base_url or not base_url.startswith(("http://", "https://")):
            # 早失败：留空 base_url 会让 httpx 抛 UnsupportedProtocol，
            # 被兜成「provider 故障」，把配置错误伪装成运行时故障。
            raise new(
                codes.CFG_MEDIA_IMAGE_GEN_INCOMPLETE,
                extra={"missing": f"base_url({base_url!r})"},
            )
        if size_mode not in (SIZE_MODE_PRESET, SIZE_MODE_EXACT):
            raise new(
                codes.CFG_MEDIA_IMAGE_GEN_INCOMPLETE, extra={"missing": f"size_mode({size_mode})"}
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_bytes = max_bytes
        self._max_prompt_chars = max_prompt_chars
        self._response_format = response_format
        self._size_mode = size_mode
        self._preset_sizes = dict(preset_sizes or DEFAULT_PRESET_SIZES)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(connect_timeout, read=read_timeout),
        )
        # 复用安全抓取器下载 `url` 形态产物，但错误码归生图域，
        # 这样「取图超时」仍报 TIMEOUT、「目标被 SSRF 拦」仍报 BLOCKED，
        # 不会被压成一个通用失败码（#46 评审）。
        self._fetcher = build_image_fetcher(
            client=self._client,
            validator=validator,
            max_bytes=max_bytes,
            unavailable_code=codes.MEDIA_IMAGE_GEN_FAILED,
            blocked_code=codes.MEDIA_IMAGE_GEN_BLOCKED,
            timeout_code=codes.MEDIA_IMAGE_GEN_TIMEOUT,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _resolve_size(self, kind: AssetKind, width: int, height: int) -> tuple[int, int]:
        """理想像素尺寸：两维都给就用；只给一维按其比例补另一维；都不给取 kind 默认。"""
        base_w, base_h = ASSET_SIZES.get(kind, ASSET_SIZES[AssetKind.BACKGROUND])
        if width > 0 and height > 0:
            return width, height
        if width > 0:
            return width, max(1, round(width * base_h / base_w))
        if height > 0:
            return max(1, round(height * base_w / base_h)), height
        return base_w, base_h

    def _provider_size(self, width: int, height: int) -> str:
        """把理想尺寸映射成 provider 认的 size 字符串。"""
        if self._size_mode == SIZE_MODE_EXACT:
            return f"{width}x{height}"
        ratio = width / height if height else 1.0
        if ratio > _LANDSCAPE_MIN_RATIO:
            return self._preset_sizes["landscape"]
        if ratio < _PORTRAIT_MAX_RATIO:
            return self._preset_sizes["portrait"]
        return self._preset_sizes["square"]

    async def generate(
        self,
        *,
        prompt: str,
        kind: AssetKind,
        width: int = 0,
        height: int = 0,
    ) -> GeneratedImage:
        # 生成前：本地确定性过滤（命中即拒，绝不发往 provider——付费调用前的闸门）。
        screen_generation_prompt(prompt, max_chars=self._max_prompt_chars)
        w, h = self._resolve_size(kind, width, height)

        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "size": self._provider_size(w, h),
            "n": 1,
        }
        if self._response_format:
            payload["response_format"] = self._response_format

        try:
            resp = await self._client.post(
                f"{self._base_url}{OPENAI_IMAGES_PATH}",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise new(
                codes.MEDIA_IMAGE_GEN_TIMEOUT, extra={"reason": f"timeout ({self._model})"}
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise new(
                codes.MEDIA_IMAGE_GEN_FAILED,
                extra={"reason": f"http {exc.response.status_code}"},
            ) from exc
        except httpx.HTTPError as exc:
            raise wrap(exc, codes.MEDIA_IMAGE_GEN_FAILED, extra={"reason": str(exc)}) from exc

        data = await self._extract_bytes(resp)
        mime = sniff_image_mime(data)
        if mime is None:
            raise new(codes.MEDIA_IMAGE_GEN_INVALID, extra={"reason": "unrecognised image bytes"})
        # 回填**真实**尺寸：provider 可能忽略/取整 size，用请求值会让 assets 元数据说谎。
        actual_w, actual_h = image_dimensions(data)
        return GeneratedImage(
            image_bytes=data,
            content_type=mime,
            width=actual_w or w,
            height=actual_h or h,
        )

    async def _extract_bytes(self, resp: httpx.Response) -> bytes:
        """从响应取图：优先内联 `b64_json`，否则下载 `url`（经安全抓取器）。

        响应体结构一律防御式解析——本模块承诺失败只抛 `MEDIA_IMAGE_GEN_*`，
        裸 `AttributeError`/`TypeError` 会穿透上层的 `except Error` 降级。
        """
        try:
            body = resp.json()
        except ValueError as exc:
            raise wrap(exc, codes.MEDIA_IMAGE_GEN_FAILED, extra={"reason": "invalid json"}) from exc
        if not isinstance(body, dict):
            raise new(
                codes.MEDIA_IMAGE_GEN_FAILED,
                extra={"reason": f"unexpected body type {type(body).__name__}"},
            )

        # 兼容网关/代理常见「200 + 顶层 error」，真实原因不应被吞掉。
        top_error = body.get("error")
        if top_error:
            raise new(
                codes.MEDIA_IMAGE_GEN_BLOCKED if _looks_like_policy(top_error) else
                codes.MEDIA_IMAGE_GEN_FAILED,
                extra={"reason": f"provider error: {_err_text(top_error)}"},
            )

        items = body.get("data")
        if not isinstance(items, list) or not items:
            raise new(codes.MEDIA_IMAGE_GEN_FAILED, extra={"reason": "empty data array"})
        first = items[0]
        if not isinstance(first, dict):
            raise new(
                codes.MEDIA_IMAGE_GEN_FAILED,
                extra={"reason": f"unexpected data[0] type {type(first).__name__}"},
            )
        if first.get("error"):
            raise new(
                codes.MEDIA_IMAGE_GEN_BLOCKED,
                extra={"reason": f"provider rejected: {_err_text(first['error'])}"},
            )

        b64 = first.get("b64_json")
        if b64:
            return self._check_size(_decode_b64(b64))

        remote = first.get("url") or first.get("image_url")
        if not isinstance(remote, str) or not remote:
            raise new(codes.MEDIA_IMAGE_GEN_FAILED, extra={"reason": "no b64_json or url"})
        try:
            page = await self._fetcher.fetch(remote)
        except Error:
            raise  # 已带 MEDIA_IMAGE_GEN_* 语义（TIMEOUT/BLOCKED/FAILED），不再重贴标签
        return self._check_size(page.body_bytes)

    def _check_size(self, data: bytes) -> bytes:
        if not data:
            raise new(codes.MEDIA_IMAGE_GEN_INVALID, extra={"reason": "empty image"})
        if len(data) > self._max_bytes:
            raise new(
                codes.MEDIA_IMAGE_GEN_INVALID,
                extra={"reason": f"image too large ({len(data)}>{self._max_bytes})"},
            )
        return data


def _err_text(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("code") or value)
    return str(value)


def _looks_like_policy(value: object) -> bool:
    """粗判 provider 侧是否为内容策略拒绝（决定降级语义：BLOCKED vs FAILED）。"""
    text = _err_text(value).casefold()
    return any(k in text for k in ("policy", "safety", "moderation", "content filter", "blocked"))


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OPENAI_IMAGES_PATH",
    "SIZE_MODE_EXACT",
    "SIZE_MODE_PRESET",
    "OpenAIImageGen",
    "image_dimensions",
    "sniff_image_mime",
]
