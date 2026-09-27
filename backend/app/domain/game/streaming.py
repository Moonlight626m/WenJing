"""流式 tee 编排骨架（ADR-0005 §10，issue #39 M0）。

职责（M5 #62 实现）：`LLM 文本流 → {WS 文本消费者, 分句器 → TTS → 音频出口}`，
多角色并发生成、增量带 `speaker`、有限缓冲 + drop-oldest、客户端 barge-in 停播。

本模块 M0 只放编排骨架与瞬态数据形状，**不定义 WS 协议**（`stream_*` 归 #60）、
也**不建 TtsPort/AsrPort 代码端口**（ADR-0005 §2，留待 M6）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TextDelta:
    """一段增量文本（真 token 流），带 speaker 供前端按去向路由。"""

    stream_id: str
    speaker: str
    text: str


@dataclass
class StreamTee:
    """文本流 tee 编排骨架：文本消费者 +（未来）分句器→TTS→音频出口。

    `max_buffer` 为 per-connection 有限缓冲上限，溢出 drop-oldest（§10 背压）。
    M5（#62）填空，当前不接业务。
    """

    max_buffer: int = 64
    _buffer: list[TextDelta] = field(default_factory=list)

    def push(self, delta: TextDelta) -> None:
        """入缓冲；超过上限丢弃最旧（drop-oldest）。"""

        self._buffer.append(delta)
        if len(self._buffer) > self.max_buffer:
            del self._buffer[: len(self._buffer) - self.max_buffer]

    def drain(self) -> list[TextDelta]:
        """取走并清空缓冲。"""

        out = self._buffer
        self._buffer = []
        return out


__all__ = ["StreamTee", "TextDelta"]
