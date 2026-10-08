"""语音识别端口与学生语音输入（ADR-0005 §11/§12，issue #64 M6）。

本模块定义：

- `AsrPort`：把一段录音转成文本的端口。
- `AsrTranscriber`：调用编排——配额闸 → 识别 → 计量。

三条与产品约束直接对应的取舍：

- **只转文本，不落音频**。学生语音是**临时输入**，与角色配音（合成产物、可重放）
  不同：录音字节在请求内用完即弃，不写对象存储、不进事件流。事件流里落的是
  `free_input` 命令的**文本**——事件是权威，而权威里不该有孩子的嗓音。
- **不走命令快捷方式**。识别结果由前端当普通 `free_input` 提交，而不是服务端直接
  造一条命令：`POST /api/sessions/{id}/commands` 是契约里明写的**唯一**游戏输入入口，
  给语音开一条旁路等于把幂等、CAS、事件同事务持久化全部绕开。
- **失败一律可回退**。识别失败只抛错，前端保持键盘输入可用——语音是**增强**
  输入通道，不是替代（#64 验收三）。

隐私：本模块不写任何含转写文本的日志。转写文本会随 `free_input` 事件落库（那是
游戏状态的一部分），但**录音字节不落库**。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.domain.game.media import MediaKind, MediaMeterPort, MediaQuotaPort, MediaUsage
from app.infrastructure.errx import codes, new

logger = logging.getLogger(__name__)

#: 单次录音的字节上限（默认 5MB）：Opus 约 1 分钟 500KB，5MB 足够几分钟。
DEFAULT_MAX_AUDIO_BYTES = 5 * 1024 * 1024
#: 单次录音的时长上限（秒）。识别按秒计费，也给"客户端谎报时长"设一个上界。
DEFAULT_MAX_SECONDS = 120


@dataclass(frozen=True)
class Transcript:
    """一次识别结果。

    `text` 是**学生说的话**；本模块不记它的日志。
    """

    text: str = ""
    #: 音频时长（毫秒）；provider 通常回报，也可能为 0。
    duration_ms: int = 0
    #: 时长是怎么来的：`provider`（provider 回报）/ `unknown`（没有值）。
    #: 落进 `media_usage.meta`，让"计量口径"这件事在数据里可查，而不是靠读代码猜。
    duration_source: str = "unknown"
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class TranscriptionRequest:
    """一次识别请求：字节 + 归属上下文（计量与配额都要）。"""

    audio_bytes: bytes
    content_type: str = "audio/webm"
    #: 客户端上报的录音时长（毫秒，0=未知）。**不单独采信**：只作为计量口径的
    #: 上限来源，且被 `max_seconds` 夹住——伪造一条请求最多只能少算，不能多吃额度。
    client_duration_ms: int = 0
    language: str = ""
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    script_id: int | None = None
    session_id: uuid.UUID | None = None


@runtime_checkable
class AsrPort(Protocol):
    """语音识别端口：一段音频 → 文本。"""

    async def transcribe(
        self, *, audio: bytes, content_type: str, language: str = ""
    ) -> Transcript: ...

    async def aclose(self) -> None: ...


class AsrTranscriber:
    """识别编排：校验 → 配额闸 → 识别 → 计量。

    与 `TtsSynthesizer` 同构，但方向相反（进来的是学生的声音）。**不吞异常**：
    识别失败要如实告诉前端"这次没听清"，前端才好提示改用键盘——这与"音频是增强、
    失败静默"的配音路径是两种态度，因为那是**输出**、这是**输入**。
    """

    def __init__(
        self,
        *,
        port: AsrPort,
        meter: MediaMeterPort | None = None,
        quota: MediaQuotaPort | None = None,
        max_audio_bytes: int = DEFAULT_MAX_AUDIO_BYTES,
        max_seconds: int = DEFAULT_MAX_SECONDS,
    ) -> None:
        self.port = port
        self.meter = meter
        self.quota = quota
        self.max_audio_bytes = max_audio_bytes
        self.max_seconds = max_seconds

    async def transcribe(self, request: TranscriptionRequest) -> Transcript:
        """识别一段录音；失败抛 `Error`（调用方转成信封，前端据此回退键盘）。"""
        audio = request.audio_bytes
        if not audio:
            raise new(codes.MEDIA_ASR_INVALID, extra={"reason": "empty audio"})
        if len(audio) > self.max_audio_bytes:
            raise new(
                codes.MEDIA_ASR_INVALID,
                extra={
                    "reason": f"audio too large ({len(audio)} > {self.max_audio_bytes})"
                },
            )

        seconds = self._seconds(request)
        if self.quota is not None and request.org_id is not None:
            acquired = await self.quota.try_acquire(
                org_id=request.org_id, kind=MediaKind.ASR, units=seconds
            )
            if not acquired:
                raise new(codes.MEDIA_ASR_FAILED, extra={"reason": "org quota exhausted"})

        result = await self.port.transcribe(
            audio=audio, content_type=request.content_type, language=request.language
        )
        if not (result.text or "").strip():
            # 空转写 = 没听清。判失败而不是当成"学生什么都没说"：
            # 后者会往事件流里塞一条空发言，把剧情推进卡在一个无意义的节点。
            raise new(codes.MEDIA_ASR_INVALID, extra={"reason": "empty transcription"})

        await self._meter(request, result, seconds)
        return result

    def _seconds(self, request: TranscriptionRequest) -> int:
        """计量/配额口径：秒（ADR-0005 §12）。

        量不出时长时按 1 秒计；有客户端上报就用它，但**夹在上限内**——口径宁可
        低估，也不让一条伪造请求把额度吃光。
        """
        if request.client_duration_ms > 0:
            return max(1, min(self.max_seconds, round(request.client_duration_ms / 1000)))
        return 1

    async def _meter(
        self, request: TranscriptionRequest, result: Transcript, seconds: int
    ) -> None:
        """计量 best-effort（ADR-0005 §12）：失败不影响已经拿到的转写。

        `meta` 里**不含转写文本**——计量表不该成为学生语音的第二份副本。
        """
        if self.meter is None or request.org_id is None:
            return
        # provider 没回报时退回客户端上报值，并把来源如实改写成 `client`——
        # 值兜了底却仍标 `unknown`，读数据的人没法判断这个数可不可信。
        duration_ms = result.duration_ms or request.client_duration_ms
        duration_source = result.duration_source
        if not result.duration_ms and request.client_duration_ms:
            duration_source = "client"
        try:
            await self.meter.record(
                MediaUsage(
                    kind=MediaKind.ASR,
                    provider=result.provider,
                    model=result.model,
                    units=seconds,
                    size=len(request.audio_bytes),
                    org_id=request.org_id,
                    user_id=request.user_id,
                    script_id=request.script_id,
                    session_id=request.session_id,
                    meta={
                        "duration_ms": duration_ms,
                        "duration_source": duration_source,
                        "language": request.language,
                        "content_type": request.content_type,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - 计量是旁路
            logger.warning("asr_meter_failed reason=%s", exc)


__all__ = [
    "DEFAULT_MAX_AUDIO_BYTES",
    "DEFAULT_MAX_SECONDS",
    "AsrPort",
    "AsrTranscriber",
    "Transcript",
    "TranscriptionRequest",
]
