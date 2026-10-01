"""`TtsPort` 工厂与音色池装配（ADR-0005 §11，issue #63）。

- `null`：不合成，返回空字节（`TtsSynthesizer` 静默跳过；字幕不受影响）。
- `openai`：OpenAI 兼容 `/audio/speech` adapter（换厂商不改 adapter）。

provider 取值由 `Settings` 的 Literal 约束，非法值启动即报错（不静默回落）。

音色池（`build_voice_map`）与 provider 分开装配：它是**领域策略**（角色名 → 音色
的确定性分配），不是 provider 细节。换 provider 只换 voice id 的取值域，
分配规则不变——同一个角色在换厂商后仍拿到池子里的同一格。
"""

from __future__ import annotations

from app.domain.game.tts import TtsPort, VoiceMap, VoiceProfile
from app.infrastructure.config import Settings
from app.infrastructure.errx import codes, new
from app.infrastructure.media.null import NullTts
from app.infrastructure.media.tts_openai import OpenAITts


def build_tts(settings: Settings) -> TtsPort:
    """按 `media_tts_provider` 构建合成端口。"""
    provider = settings.media_tts_provider
    if provider == "null":
        return NullTts()
    if provider == "openai":
        return OpenAITts(
            api_key=settings.media_tts_api_key,
            base_url=settings.media_tts_base_url,
            model=settings.media_tts_model,
            default_voice=settings.media_tts_default_voice,
            connect_timeout=settings.media_tts_connect_timeout,
            read_timeout=settings.media_tts_read_timeout,
            max_bytes=settings.media_tts_max_bytes,
            max_chars=settings.media_tts_max_chars,
            response_format=settings.media_tts_response_format,
        )
    raise new(codes.CFG_UNKNOWN_MEDIA_PROVIDER, extra={"provider": provider})


def _split(value: str) -> list[str]:
    """逗号分隔配置项 → 去空去重的列表（保序）。"""
    seen: dict[str, None] = {}
    for item in value.split(","):
        item = item.strip()
        if item:
            seen.setdefault(item, None)
    return list(seen)


def build_voice_map(settings: Settings) -> VoiceMap:
    """按配置装配角色 → 音色的映射。

    - `media_tts_voices` 是池子，角色名哈希取模分配；
    - `media_tts_voice_overrides` 的 `角色=音色` 优先于池子；
    - 池子为空时全场用 `media_tts_default_voice`（此时角色不可区分——运营可以从
      `VoiceMap.describe()` 看出来，不必额外告警）。
    """
    voices = tuple(VoiceProfile(voice_id=v) for v in _split(settings.media_tts_voices))
    default = VoiceProfile(voice_id=settings.media_tts_default_voice)
    overrides: dict[str, VoiceProfile] = {}
    for pair in _split(settings.media_tts_voice_overrides):
        name, _, voice = pair.partition("=")
        name, voice = name.strip(), voice.strip()
        if name and voice:
            overrides[name] = VoiceProfile(voice_id=voice)
    return VoiceMap(voices=voices, default=default, overrides=overrides)


__all__ = ["build_tts", "build_voice_map"]
