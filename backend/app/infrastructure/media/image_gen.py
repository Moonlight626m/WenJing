"""`ImageGenPort` 工厂：按配置选择生图 provider（ADR-0005 §2/§6，issue #46）。

- `null`：不生成，返回空字节（安全降级，上层降级为无图/纯文本）。
- `openai`：OpenAI 兼容 Images API adapter（换厂商不改 adapter）。

provider 取值由 `Settings` 的 Literal 约束，非法值启动即报错（不静默回落）。
"""

from __future__ import annotations

from app.domain.game.media import ImageGenPort
from app.infrastructure.config import Settings
from app.infrastructure.errx import codes, new
from app.infrastructure.media.image_gen_openai import OpenAIImageGen
from app.infrastructure.media.null import NullImageGen


def build_image_gen(settings: Settings) -> ImageGenPort:
    """按 `media_image_gen_provider` 构建生图端口。"""
    provider = settings.media_image_gen_provider
    if provider == "null":
        return NullImageGen()
    if provider == "openai":
        return OpenAIImageGen(
            api_key=settings.media_image_gen_api_key,
            base_url=settings.media_image_gen_base_url,
            model=settings.media_image_gen_model,
            connect_timeout=settings.media_image_gen_connect_timeout,
            read_timeout=settings.media_image_gen_read_timeout,
            max_bytes=settings.media_image_gen_max_bytes,
            max_prompt_chars=settings.media_image_gen_max_prompt_chars,
            response_format=settings.media_image_gen_response_format or None,
            size_mode=settings.media_image_gen_size_mode,
        )
    raise new(codes.CFG_UNKNOWN_MEDIA_PROVIDER, extra={"provider": provider})


__all__ = ["build_image_gen"]
