"""语音合成端口与音色映射（ADR-0005 §11，issue #63 M6）。

本模块定义：

- `TtsPort`：**按句**合成的端口（`SentenceSink` 的下游，M5 #62 已把 tee 接好）。
- `VoiceProfile` / `VoiceMap`：角色 → 音色。**角色名是唯一稳定的锚**——`scene_key`、
  `beat_id` 都会随剧本重生成而变，角色名不会；同一角色跨场景、跨会话音色一致。
- `TtsSynthesizer`：`SentenceSink` 的实现，把「攒好的整句」变成「一条音轨」。

三条与 ADR-0005 §11 直接对应的取舍：

- **不混音**：每条发言一条独立音轨，前端多 `<audio>` 并发播放。后端不把多角色
  音频混成一路——混音会让"谁在说话"这个信息在数据层面永久丢失，而字幕/重播/
  barge-in 都要用它。
- **后端中转**：音频字节经 WS 下发而不走对象存储预签名。合成是**即时**的：
  写一次对象存储再签发 URL，多一次往返且要把私有的即时产物变成有生命周期的资源；
  已存图片可以前端直取，是因为它本来就是持久资产（ADR-0005 §4）。
- **失败降级**：合成失败**不抛给调用方**。音频是增强，字幕与持久 `character_speech`
  才是权威；一条音轨哑了不该让整轮命令失败（与 `SpeechStreamSink` 同一条理由）。

分层约束：domain 不 import infrastructure；provider 适配器在 `infrastructure/media/`。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.domain.game.media import MediaKind, MediaMeterPort, MediaQuotaPort, MediaUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceProfile:
    """一个角色绑定的音色（provider 侧的 voice id + 语速）。"""

    #: provider 的音色标识（如 `zh-CN-XiaoxiaoNeural` / `alloy`）。空 = 用 provider 默认。
    voice_id: str = ""
    #: 相对语速，1.0 = 原速。旁白略慢，情绪激烈的角色可略快。
    speed: float = 1.0


@dataclass(frozen=True)
class SynthesizedAudio:
    """一次合成的结果：字节 + 编码信息（音频经后端中转，不落对象存储）。"""

    audio_bytes: bytes
    content_type: str = "audio/mpeg"
    #: 合成消耗的字符数（`media_usage.units` 的口径，ADR-0005 §12：tts=字符）。
    units: int = 0
    #: 时长（毫秒）。provider 不回这个字段，由 adapter 从字节量出来（逐帧累加采样数），
    #: 量不出记 0。落进 `media_usage.meta`——`units` 对 tts 是**字符**（ADR-0005 §12）。
    duration_ms: int = 0
    #: 采样率（Hz）；同样由 adapter 量出，随 `audio_start` 下发。0 = 未知。
    sample_rate: int = 0
    provider: str = ""
    model: str = ""


class VoiceMap:
    """角色名 → 音色。**确定性**：同一角色每次都拿同一个音色。

    音色池固定、按角色名哈希取模分配，不用随机数也不用"按出现顺序"（后者会让
    加一个角色就把所有人的音色整体挪位，玩家听到的是"这个人换了嗓子"）。
    同名角色的音色跨剧本、跨会话一致——这正是"音色可区分角色"（#63 验收）的落点。

    `default` 是池子用尽或只有一个角色时的兜底；`overrides` 供运营按角色名钦定。

    只映射**角色**，不映射旁白：旁白（`plot_advancement`）目前不进合成链路——
    它由引擎直接落事件，不经 `SpeechStreamSink`。为它留一个音色槽位是给一个不存在的
    需求造接口；等旁白真要出声时再加（那时得先让引擎把旁白也送进 tee）。
    """

    def __init__(
        self,
        *,
        voices: tuple[VoiceProfile, ...] = (),
        default: VoiceProfile | None = None,
        overrides: dict[str, VoiceProfile] | None = None,
    ) -> None:
        # 池子**可以为空**：此时全场用 `default`（配置只给了默认嗓没给池子）。
        # 早先写成 `voices or (VoiceProfile(),)` 会让 `default` 永远够不着，
        # 且把空池分支变成死代码——空池要能落到 default 上。
        self._voices = tuple(voices)
        self._default = default or (self._voices[0] if self._voices else VoiceProfile())
        self._overrides = dict(overrides or {})
        #: 已解析过的角色 → 音色。缓存是为了让同角色在后续调用中恒定
        #: （顺延逻辑本身依赖"先到先得"，不缓存就会每次重算而漂移）。
        self._assigned: dict[str, VoiceProfile] = {}

    def voice_for(self, speaker: str) -> VoiceProfile:
        """给发言者分配音色：**同角色恒同音色**，且尽量不与已出场的角色撞嗓。

        先用 blake2b 哈希定首选（不用内置 `hash`：它按进程随机加盐，重启就换嗓），
        撞了就在池子里顺延到下一个没被占的。撞嗓**必须**处理——纯哈希在 3 个角色
        3 个音色时按生日问题约有一半概率撞上，而"音色可区分角色"正是 #63 的验收项。

        代价说清楚：顺延依赖"谁先开口"，所以两个**哈希到同一格**的角色在不同会话里
        可能互换音色（只在撞格时发生；不撞格的绝大多数角色跨会话恒定）。要绝对稳定
        就给 `overrides` 钦定，或把音色池开大。
        """
        override = self._overrides.get(speaker)
        if override is not None:
            return override
        if not self._voices:
            return self._default
        assigned = self._assigned.get(speaker)
        if assigned is not None:
            return assigned
        digest = hashlib.blake2b(speaker.encode("utf-8"), digest_size=4).digest()
        start = int.from_bytes(digest, "big") % len(self._voices)
        taken = {p.voice_id for p in self._assigned.values()}
        chosen = self._voices[start]
        for offset in range(len(self._voices)):
            candidate = self._voices[(start + offset) % len(self._voices)]
            if candidate.voice_id not in taken:
                chosen = candidate
                break
        # 池子用尽（角色数 > 音色数）时 `chosen` 停在首选，复用是唯一选择。
        self._assigned[speaker] = chosen
        return chosen

    def describe(self) -> dict[str, str]:
        """可观测快照：角色 → 音色 id（诊断"两个人一个嗓"这类问题）。"""
        merged = {name: p.voice_id for name, p in self._assigned.items()}
        merged.update({name: p.voice_id for name, p in self._overrides.items()})
        return merged


@runtime_checkable
class TtsPort(Protocol):
    """语音合成端口（按句调用，ADR-0005 §11）。

    `text` 是 tee 的分句器攒好的**整句**，不是逐字增量——逐字合成既贵又难听后处理
    （`SentenceSink` 的 docstring）。实现方按句合成，返回单条音轨的字节。
    """

    async def synthesize(
        self, *, text: str, voice: VoiceProfile
    ) -> SynthesizedAudio: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class AudioTrackSink(Protocol):
    """音轨出口：把合成好的音频交给连接（`AudioTrackChannel` 是生产实现）。

    与 `SpeechStreamSink` 同样是**同步**方法：出口自己决定排队异步送还是就地丢弃。
    域内在 `asyncio.gather` 里并发处理多角色，把它变成 await 点等于把慢客户端的
    延迟算到生成头上。
    """

    def start(self, speaker: str, *, content_type: str, sample_rate: int = 0) -> str: ...

    def chunk(self, track_id: str, data: bytes) -> None: ...

    def end(self, track_id: str) -> None: ...


@dataclass
class TtsSynthesizer:
    """`SentenceSink` 实现：整句 → 合成 → 音轨（ADR-0005 §11 的中转环节）。

    挂在 `StreamTee.sentence_sink` 上。tee 逐字转字幕、按句喂这里，两条通道各自
    独立：TTS provider 挂了，字幕照滚（音频是增强）。

    - **按句并发**：多角色并发生成时各句独立合成，不互相排队。但**同一条发言内**
      句子必须有序——`speak` 是同步方法（`SentenceSink` 的契约），内部用队列串起
      每条流的合成任务，保证 `audio_start → chunk → audio_end` 的次序。
    - **先计量后合成**：`MediaQuotaPort` 的闸开在付费调用之前（ADR-0005 §12）。
    - **失败降级**：合成/配额/计量任一失败都只告警，不向 tee 抛（那是生成路径）。
    """

    port: TtsPort
    voices: VoiceMap
    sink: AudioTrackSink
    meter: MediaMeterPort | None = None
    quota: MediaQuotaPort | None = None
    session_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    script_id: int | None = None
    #: 单句字符上限：provider 多按字符计费，超长句一次就吃掉大量额度。
    max_sentence_chars: int = 200
    _tasks: list[asyncio.Task[None]] = field(default_factory=list, repr=False)
    #: 每个 speaker 的合成链尾：同一角色的句子必须**按序**合成，
    #: 否则 `asyncio.create_task` 的调度顺序不保证，玩家会听到后一句先播。
    _chains: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)

    def speak(self, speaker: str, sentence: str) -> None:
        """`SentenceSink` 入口（同步）：排一条合成任务，不阻塞生成路径。

        **同角色串行、跨角色并行**：多角色并发时各说各的（ADR-0005 §11 多音轨），
        但单角色的一串句子必须有序，否则台词会倒着播。
        """
        text = sentence.strip()[: self.max_sentence_chars]
        if not text:
            return
        previous = self._chains.get(speaker)
        task = _spawn(self._synthesize(speaker, text, after=previous))
        if task is None:
            return
        self._chains[speaker] = task
        self._tasks.append(task)

    async def aclose(self) -> None:
        """等所有在途合成收尾；由命令返回后、关闭连接之前调用。"""
        tasks, self._tasks = self._tasks, []
        if not tasks:
            return
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException):
                logger.warning("tts_task_failed reason=%s", result)

    async def _synthesize(
        self, speaker: str, text: str, *, after: asyncio.Task[None] | None = None
    ) -> None:
        if after is not None and not after.done():
            # 前一句还没合完：等它（异常不传染，前句失败不该吞掉这一句）
            await asyncio.gather(after, return_exceptions=True)
        voice = self.voices.voice_for(speaker)
        units = len(text)
        if self.quota is not None and self.org_id is not None:
            try:
                acquired = await self.quota.try_acquire(
                    org_id=self.org_id, kind=MediaKind.TTS, units=units
                )
            except Exception as exc:  # noqa: BLE001 - 配额是闸，坏了不该炸生成
                logger.warning("tts_quota_failed reason=%s", exc)
                acquired = False
            if not acquired:
                # 额度耗尽：静默不合成。字幕照滚，玩家少一段配音而已。
                logger.info(
                    "tts_quota_exhausted", extra={"wj_extra": {"chars": units}}
                )
                return
        try:
            audio = await self.port.synthesize(text=text, voice=voice)
        except Exception as exc:  # noqa: BLE001 - 音频是增强，失败不反噬生成
            logger.warning(
                "tts_synthesize_failed",
                extra={"wj_extra": {"speaker": speaker, "reason": str(exc)[:200]}},
            )
            return
        if not audio.audio_bytes:
            return
        track_id = self.sink.start(
            speaker, content_type=audio.content_type, sample_rate=audio.sample_rate
        )
        try:
            self.sink.chunk(track_id, audio.audio_bytes)
        finally:
            # 异常也必须收轨：前端会留着一条永不结束的音轨（与 `StreamTee.end` 同理）
            self.sink.end(track_id)
        await self._meter(speaker, audio, units)

    async def _meter(self, speaker: str, audio: SynthesizedAudio, units: int) -> None:
        """计量 best-effort（ADR-0005 §12）：失败不得影响已合成好的音轨。"""
        if self.meter is None or self.org_id is None:
            return
        try:
            await self.meter.record(
                MediaUsage(
                    kind=MediaKind.TTS,
                    provider=audio.provider,
                    model=audio.model,
                    units=audio.units or units,
                    size=len(audio.audio_bytes),
                    org_id=self.org_id,
                    user_id=self.user_id,
                    script_id=self.script_id,
                    session_id=self.session_id,
                    meta={
                        "speaker": speaker,
                        "voice": self.voices.voice_for(speaker).voice_id,
                        "duration_ms": audio.duration_ms,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - 计量是旁路
            logger.warning("tts_meter_failed reason=%s", exc)


def _spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None] | None:
    """排一条合成任务；没有运行中的事件循环时放弃这条音频（不向 tee 抛）。"""
    try:
        return asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        return None


__all__ = [
    "AudioTrackSink",
    "SynthesizedAudio",
    "TtsPort",
    "TtsSynthesizer",
    "VoiceMap",
    "VoiceProfile",
]
