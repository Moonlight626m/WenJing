"""`AsrPort` 工厂（ADR-0005 §11，issue #64）。

- `null`：不转写，返回空文本——`AsrTranscriber` 收到空文本判 `MEDIA_ASR_INVALID`。
- `openai`：OpenAI 兼容 `/audio/transcriptions` adapter（换厂商不改 adapter）。

provider 取值由 `Settings` 的 Literal 约束，非法值启动即报错（不静默回落）。
"""

from __future__ import annotations

from app.domain.game.asr import AsrPort
from app.infrastructure.config import Settings
from app.infrastructure.errx import codes, new
from app.infrastructure.media.asr_openai import OpenAITranscriber
from app.infrastructure.media.null import NullAsr


def build_asr(settings: Settings) -> AsrPort:
    """按 `media_asr_provider` 构建识别端口。"""
    provider = settings.media_asr_provider
    if provider == "null":
        return NullAsr()
    if provider == "openai":
        return OpenAITranscriber(
            api_key=settings.media_asr_api_key,
            base_url=settings.media_asr_base_url,
            model=settings.media_asr_model,
            connect_timeout=settings.media_asr_connect_timeout,
            read_timeout=settings.media_asr_read_timeout,
            max_bytes=settings.media_asr_max_bytes,
            response_format=settings.media_asr_response_format,
        )
    raise new(codes.CFG_UNKNOWN_MEDIA_PROVIDER, extra={"provider": provider})


__all__ = ["build_asr"]
