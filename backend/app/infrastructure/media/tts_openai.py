"""OpenAI 兼容语音合成 adapter（ADR-0005 §11，issue #63 M6）。

- `POST {base}/audio/speech`：OpenAI Speech API 形状，请求体 `{model, input, voice,
  response_format, speed}`，响应体是**裸音频字节**（不是 JSON/base64）。选兼容形状
  而非厂商专属 API，是为了换 provider 不改 adapter——硅基流动、智谱、阿里百炼等
  也暴露兼容端点（provider 选型仍是 ADR-0005 的待定项）。
- **字节级魔数嗅探**：不信任 `content-type` 头。provider 声称 `audio/mpeg` 却回一段
  JSON 错误体是很常见的失败形态，落进 `<audio src>` 只会得到静默无声——不如早失败。
- 失败**一律**抛 `MEDIA_TTS_*`：上层（`TtsSynthesizer`）只 catch `Exception` 做降级，
  但结构化错误码让日志能区分"provider 挂了"和"配额拦了"。
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from app.domain.game.tts import SynthesizedAudio, VoiceProfile
from app.infrastructure.errx import codes, new, wrap
from app.infrastructure.media.audio_probe import probe_audio

OPENAI_SPEECH_PATH = "/audio/speech"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "tts-1"
DEFAULT_VOICE = "alloy"
DEFAULT_CONNECT_TIMEOUT = 5.0
# 合成比生图快，但长句 + 排队仍可能到十几秒；给足上界。
DEFAULT_READ_TIMEOUT = 60.0
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CHARS = 4096
DEFAULT_RESPONSE_FORMAT = "mp3"

#: 字节级魔数：不信任 provider 的 content-type。
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
    (b"\xff\xf2", "audio/mpeg"),
    (b"RIFF", "audio/wav"),
    (b"OggS", "audio/ogg"),
    (b"fLaC", "audio/flac"),
    (b"\x1aE\xdf\xa3", "audio/webm"),
)
_FORMAT_MIME: Mapping[str, str] = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
}


#: 没有容器头的裸格式：认不出魔数属于**预期**（PCM 就是没有头），不该判失败。
_RAW_FORMATS = frozenset({"pcm"})


def sniff_audio_mime(data: bytes) -> str:
    """按魔数识别音频类型；认不出返回空串（调用方决定是降级还是判失败）。"""
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            # RIFF 同时是 WEBP/WAV/AVI 的容器头，靠第 8–12 字节区分
            if magic == b"RIFF" and len(data) >= 12 and data[8:12] != b"WAVE":
                continue
            return mime
    return ""


class OpenAITts:
    """`TtsPort` 的 OpenAI 兼容实现（`/audio/speech`）。"""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        default_voice: str = DEFAULT_VOICE,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_chars: int = DEFAULT_MAX_CHARS,
        response_format: str = DEFAULT_RESPONSE_FORMAT,
    ) -> None:
        if not api_key:
            raise new(codes.CFG_MEDIA_TTS_INCOMPLETE, extra={"missing": "api_key"})
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise new(
                codes.CFG_MEDIA_TTS_INCOMPLETE,
                extra={"missing": f"base_url({base_url!r})"},
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._default_voice = default_voice
        self._max_bytes = max_bytes
        self._max_chars = max_chars
        self._response_format = response_format
        self._content_type = _FORMAT_MIME.get(response_format, "audio/mpeg")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout
            ),
        )

    async def aclose(self) -> None:
        """关闭自建的 httpx 连接池（`TtsPort` 的协议方法，由组合根在 lifespan 收尾时调）。

        只关**自建**的：注入 `client` 时所有权在调用方（测试里靠 fixture 统一收口）。
        """
        if self._owns_client:
            await self._client.aclose()

    async def synthesize(
        self, *, text: str, voice: VoiceProfile
    ) -> SynthesizedAudio:
        """合成一句：`text` 是 tee 攒好的整句，不是逐字增量。"""
        body_text = text.strip()
        if not body_text:
            raise new(codes.MEDIA_TTS_INVALID, extra={"reason": "empty text"})
        if len(body_text) > self._max_chars:
            # 超长直接截断会念出半句话；宁可拒绝，让上层只丢这一句音频。
            raise new(
                codes.MEDIA_TTS_INVALID,
                extra={"reason": f"text too long ({len(body_text)} > {self._max_chars})"},
            )
        payload: dict[str, object] = {
            "model": self._model,
            "input": body_text,
            "voice": voice.voice_id or self._default_voice,
            "response_format": self._response_format,
        }
        # speed 只在与 1.0 有实际差异时发：部分兼容 provider 不认这个字段，
        # 发一个默认值只会平白多一类 400。
        if abs(voice.speed - 1.0) > 1e-6:
            payload["speed"] = voice.speed
        try:
            response = await self._client.post(
                f"{self._base_url}{OPENAI_SPEECH_PATH}",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise wrap(exc, codes.MEDIA_TTS_TIMEOUT, extra={"reason": str(exc)}) from exc
        except httpx.HTTPError as exc:
            raise wrap(exc, codes.MEDIA_TTS_FAILED, extra={"reason": str(exc)}) from exc

        if response.status_code >= 400:
            raise new(
                codes.MEDIA_TTS_FAILED,
                extra={
                    "reason": f"status {response.status_code}: {response.text[:200]}"
                },
            )
        data = response.content
        if not data:
            raise new(codes.MEDIA_TTS_INVALID, extra={"reason": "empty body"})
        if len(data) > self._max_bytes:
            raise new(
                codes.MEDIA_TTS_INVALID,
                extra={"reason": f"audio too large ({len(data)} > {self._max_bytes})"},
            )
        # 魔数认不出时**不能**一律信配置的格式：那会让"provider 把 JSON 错误体当
        # 200 回"静默通过，落进 `<audio>` 变成无声。只有裸格式（PCM 这类本就没有
        # 容器头）才接受认不出——其余一律判失败，早失败好过静默无声。
        mime = sniff_audio_mime(data)
        if not mime:
            if self._response_format not in _RAW_FORMATS:
                raise new(
                    codes.MEDIA_TTS_INVALID,
                    extra={
                        "reason": f"unrecognized audio bytes: {data[:32]!r}",
                        "format": self._response_format,
                    },
                )
            mime = self._content_type
        # provider 的响应是裸字节，没有时长字段（`/audio/speech` 不回元数据）。
        # 时长从字节里量（逐帧累加采样数，VBR 也准）——`media_usage` 要记它
        # （ADR-0005 §12），量不出来记 0，不让整条音轨失败。
        probe = probe_audio(data)
        return SynthesizedAudio(
            audio_bytes=data,
            content_type=mime,
            units=len(body_text),
            duration_ms=probe.duration_ms,
            sample_rate=probe.sample_rate,
            provider="openai",
            model=self._model,
        )


__all__ = ["OpenAITts", "sniff_audio_mime"]
