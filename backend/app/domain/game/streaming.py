"""流式 tee 编排（ADR-0005 §10，issue #39 M0 → #62 填充）。

职责：`LLM 文本流 → {WS 文本消费者, 分句器 → TTS → 音频出口}`，
多角色并发生成、增量带 `speaker`、客户端 barge-in 停播。
有限缓冲 + drop-oldest 落在**连接级**出口 `StreamChannel` 上（每条连接各自有界），
不在本层重复一层：tee 只管分流，不管攒。

#62 把 M0 的骨架接成了真的分流点：`StreamTee` 实现 `SpeechStreamSink`，运行时照旧
只认一个出口；逐段文字转给 WS 文本出口，**攒够一句**才交给 `SentenceSink`（TTS 出口，
M6 #63 接实现）。客户端 barge-in 是纯客户端行为，见 `dto.CancelAudioMessage`。

本模块 M0 只放编排骨架与瞬态数据形状，**不定义 WS 协议**（`stream_*` 归 #60）、
也**不建 TtsPort/AsrPort 代码端口**（ADR-0005 §2，留待 M6）。

#60 在此补了域内**出口协议** `SpeechStreamSink`：运行时经由它把角色发言的增量交出去，
去处（WS 瞬态消息 / 日志 / 丢弃）由基础设施实现。它只描述"往哪里吐字"，因此仍然不碰
WS 协议形状——`stream_start/stream_delta/stream_end` 的语言在契约层（`dto.StreamMessage`）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: 分句断点：中英文句末标点与换行。换行也断句——字幕按行起步，朗读也一样。
SENTENCE_ENDINGS = "。！？!?；;…\n"


@dataclass(frozen=True)
class TextDelta:
    """一段增量文本（真 token 流），带 speaker 供前端按去向路由。"""

    stream_id: str
    speaker: str
    text: str


@runtime_checkable
class SentenceSink(Protocol):
    """整句出口：M6 的 TTS（#63）实现它，本层只负责把增量攒成句。

    与 `SpeechStreamSink` 的分工：那边是**逐字**的字幕，这边是**整句**的合成输入。
    合成按句排队才有意义——逐字合成既贵又难听后处理。
    """

    def speak(self, speaker: str, sentence: str) -> None: ...


@dataclass
class StreamTee:
    """文本流 tee：一个入口（`SpeechStreamSink`），两个出口。

    - `text_sink`：WS 文本消费者，逐字转发（`StreamChannel` 是它的生产实现）；
    - `sentence_sink`：分句器的下游，攒够一句才吐（TTS 出口，M6 #63 接）。

    `start` / `delta` / `end` 是 `SpeechStreamSink` 的形状，运行时不必知道 tee 的存在。
    """

    text_sink: SpeechStreamSink | None = None
    sentence_sink: SentenceSink | None = None
    _speakers: dict[str, str] = field(default_factory=dict)
    _pending: dict[str, str] = field(default_factory=dict)

    # ===== SpeechStreamSink =====

    def start(self, speaker: str) -> str:
        stream_id = (
            self.text_sink.start(speaker)
            if self.text_sink is not None
            else uuid.uuid4().hex
        )
        self._speakers[stream_id] = speaker
        self._pending[stream_id] = ""
        return stream_id

    def delta(self, stream_id: str, text: str) -> None:
        if not text:
            return
        self.push(
            TextDelta(
                stream_id=stream_id,
                speaker=self._speakers.get(stream_id, ""),
                text=text,
            )
        )

    def end(self, stream_id: str) -> None:
        """收流：把没等到句末标点的尾巴也当一句吐出去，再关文本出口。"""
        tail = self._pending.pop(stream_id, "").strip()
        speaker = self._speakers.pop(stream_id, "")
        if tail and self.sentence_sink is not None:
            self.sentence_sink.speak(speaker, tail)
        if self.text_sink is not None:
            self.text_sink.end(stream_id)

    # ===== 扇出 =====

    def push(self, delta: TextDelta) -> None:
        """唯一的扇出点：WS 文本出口 → 分句器。"""

        self._speakers.setdefault(delta.stream_id, delta.speaker)
        if self.text_sink is not None:
            self.text_sink.delta(delta.stream_id, delta.text)
        if self.sentence_sink is not None:
            self._feed_sentences(delta)

    def _feed_sentences(self, delta: TextDelta) -> None:
        """按句末标点切分，最后一段留在 `pending` 里等下一段（或收流时冲尾）。"""
        buffered = self._pending.get(delta.stream_id, "") + delta.text
        start = 0
        for index, char in enumerate(buffered):
            if char not in SENTENCE_ENDINGS:
                continue
            following = buffered[index + 1] if index + 1 < len(buffered) else ""
            if following and following in SENTENCE_ENDINGS:
                continue  # 连续标点（"？！"）是同一句的收尾
            self._say(delta.speaker, buffered[start : index + 1])
            start = index + 1
        self._pending[delta.stream_id] = buffered[start:]

    def _say(self, speaker: str, sentence: str) -> None:
        text = sentence.strip()
        if text and self.sentence_sink is not None:
            self.sentence_sink.speak(speaker, text)


@runtime_checkable
class SpeechStreamSink(Protocol):
    """角色发言的流式出口（#60）：域内只知道"往哪里吐字"。

    - `start` 返回本条约定的 `stream_id`，由调用方透传给 `delta` / `end`；
    - 三个方法都是**同步**的：出口自己决定是排队异步送还是就地丢弃。域内正在
      `asyncio.gather` 里并发生成多角色发言，把它们变成 await 点就等于把慢客户端的
      延迟算到生成头上（背压取舍见 `services.stream_channel.StreamChannel`）；
    - `end` 必须与 `start` 配对（含异常路径），否则客户端会留着一条永不结束的流；
    - 实现**不得向上抛异常**：流式字幕是增强，坏掉的字幕管道不该拖垮命令。
    """

    def start(self, speaker: str) -> str: ...

    def delta(self, stream_id: str, text: str) -> None: ...

    def end(self, stream_id: str) -> None: ...


__all__ = ["SENTENCE_ENDINGS", "SentenceSink", "SpeechStreamSink", "StreamTee", "TextDelta"]
