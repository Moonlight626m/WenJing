"""OpenAI 兼容语音识别 adapter（ADR-0005 §11，issue #64 M6）。

- `POST {base}/audio/transcriptions`：multipart 表单（`file` + `model` + 可选
  `language`/`response_format`），返回 JSON `{"text": "..."}`。选兼容形状而非
  厂商专属 API，换 provider 不改 adapter（与生图/TTS 同一取舍）。
- **录音字节不落盘、不进日志**：它是学生的临时输入，用完即弃。日志里只出现字节数
  与内容类型，绝不出现转写文本或音频内容。
- 失败一律抛 `MEDIA_ASR_*`：与配音路径相反，识别失败**要**让调用方知道——
  输入没了就得让前端提示改用键盘（#64 验收三）。
"""

from __future__ import annotations

import json

import httpx

from app.domain.game.asr import Transcript
from app.infrastructure.errx import codes, new, wrap

OPENAI_TRANSCRIPTIONS_PATH = "/audio/transcriptions"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "whisper-1"
DEFAULT_CONNECT_TIMEOUT = 5.0
# 识别要等整段音频传完再出结果，且长录音排队更久：读超时给足。
DEFAULT_READ_TIMEOUT = 120.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_RESPONSE_FORMAT = "json"

#: 不信任客户端声明的 content-type（与产物侧同理），只接受这些容器。
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
        "audio/flac",
        "audio/L16",
    }
)


class OpenAITranscriber:
    """`AsrPort` 的 OpenAI 兼容实现。"""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        response_format: str = DEFAULT_RESPONSE_FORMAT,
        allowed_content_types: frozenset[str] = ALLOWED_CONTENT_TYPES,
    ) -> None:
        if not api_key:
            raise new(codes.CFG_MEDIA_ASR_INCOMPLETE, extra={"missing": "api_key"})
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise new(
                codes.CFG_MEDIA_ASR_INCOMPLETE,
                extra={"missing": f"base_url({base_url!r})"},
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_bytes = max_bytes
        self._response_format = response_format
        self._allowed = allowed_content_types
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout
            ),
        )

    async def aclose(self) -> None:
        """关闭自建的 httpx 连接池（由组合根在 lifespan 收尾时调）。"""
        if self._owns_client:
            await self._client.aclose()

    async def transcribe(
        self, *, audio: bytes, content_type: str, language: str = ""
    ) -> Transcript:
        if not audio:
            raise new(codes.MEDIA_ASR_INVALID, extra={"reason": "empty audio"})
        if len(audio) > self._max_bytes:
            raise new(
                codes.MEDIA_ASR_INVALID,
                extra={"reason": f"audio too large ({len(audio)} > {self._max_bytes})"},
            )
        mime = (content_type or "").split(";")[0].strip().lower()
        if mime not in self._allowed:
            raise new(
                codes.MEDIA_ASR_INVALID,
                extra={"reason": f"unsupported content type: {content_type!r}"},
            )

        data: dict[str, str] = {
            "model": self._model,
            "response_format": self._response_format,
        }
        if language:
            data["language"] = language
        try:
            response = await self._client.post(
                f"{self._base_url}{OPENAI_TRANSCRIPTIONS_PATH}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                data=data,
                files={"file": (_filename_for(mime), audio, mime)},
            )
        except httpx.TimeoutException as exc:
            raise wrap(exc, codes.MEDIA_ASR_TIMEOUT, extra={"reason": str(exc)}) from exc
        except httpx.HTTPError as exc:
            raise wrap(exc, codes.MEDIA_ASR_FAILED, extra={"reason": str(exc)}) from exc

        if response.status_code >= 400:
            raise new(
                codes.MEDIA_ASR_FAILED,
                extra={"reason": f"status {response.status_code}: {response.text[:200]}"},
            )
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> Transcript:
        """解析响应。只取 `text`，**不记内容**——转写文本不进日志。"""
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise wrap(
                exc, codes.MEDIA_ASR_INVALID, extra={"reason": "response is not JSON"}
            ) from exc
        if not isinstance(payload, dict):
            raise new(codes.MEDIA_ASR_INVALID, extra={"reason": "unexpected response shape"})
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise new(codes.MEDIA_ASR_INVALID, extra={"reason": "no transcription text"})
        duration = payload.get("duration")
        duration_ms = (
            round(float(duration) * 1000)
            if isinstance(duration, (int, float)) and duration > 0
            else 0
        )
        return Transcript(
            text=text.strip(),
            duration_ms=duration_ms,
            # provider 回了时长就用它；没回则由编排层退回客户端上报值
            duration_source="provider" if duration_ms else "unknown",
            provider="openai",
            model=self._model,
        )


def _filename_for(mime: str) -> str:
    """multipart 的文件名——有些 provider 按扩展名判容器，不能随便叫 `audio`。"""
    return {
        "audio/webm": "audio.webm",
        "audio/ogg": "audio.ogg",
        "audio/mpeg": "audio.mp3",
        "audio/mp4": "audio.mp4",
        "audio/wav": "audio.wav",
        "audio/x-wav": "audio.wav",
        "audio/flac": "audio.flac",
        "audio/L16": "audio.pcm",
    }.get(mime, "audio.bin")


__all__ = ["ALLOWED_CONTENT_TYPES", "OpenAITranscriber"]
