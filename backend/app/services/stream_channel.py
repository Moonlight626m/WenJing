"""每连接的瞬态流出口（ADR-0005 §10 / issue #60）。

与 `SessionEventHub` 的分工：hub 按**会话**投递命令外的持久事件（可丢，因为能从事件流
重建）；本模块按**连接**投递命令内的流式字幕（纯瞬态，连接没了就作废）。

三条取舍：

- **不入 outbox**：`stream_*` 没有 `seq`，也就不参与 `confirm`/`resync` 补发。断线重连
  看到的是 `character_speech` 的完整文本，而不是逐字回放——这正是"事件只存最终完整
  文本"的直接后果。
- **有限缓冲 + drop-oldest**：缓冲有界，满了丢最旧的一条。慢客户端宁可少看几个字，
  也不能把生成拖住——流式存在的全部意义就是降 TTFT。
- **发送失败即停**：连接没了就关通道，之后的 `delta` 静默丢弃。命令本身照常跑完落库：
  事件才是权威，客户端一断就掐事务只会留下半个世界（与 ADR-0005 §11 "barge-in 不抢占
  LLM" 同一条理由）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("wenjing.session.stream")

#: 单连接待发的瞬态消息上限。一条发言几十段，32 足够吸收一次网络抖动。
#: 溢出时丢的是最旧的**增量**；`stream_start` / `stream_end` 不参与淘汰。
DEFAULT_BUFFER_SIZE = 32
#: 收流时的冲刷上限：慢客户端不能把 WS 处理循环拖住（超时就放弃未发完的字幕）。
FLUSH_TIMEOUT_SECONDS = 1.0


class StreamChannel:
    """连接级的流式字幕出口：有界缓冲 + 后台发送 + drop-oldest。"""

    def __init__(
        self,
        session_id: uuid.UUID | str,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        self._session_id = str(session_id)
        self._send = send
        self._buffer_size = max(1, buffer_size)
        self._pending: deque[dict[str, Any]] = deque()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._closing = False
        self._closed = False
        self._dropped = 0

    # ===== SpeechStreamSink =====

    def start(self, speaker: str) -> str:
        stream_id = uuid.uuid4().hex
        self._enqueue("stream_start", {"stream_id": stream_id, "speaker": speaker})
        return stream_id

    def delta(self, stream_id: str, text: str) -> None:
        if text:
            self._enqueue("stream_delta", {"stream_id": stream_id, "text": text})

    def end(self, stream_id: str) -> None:
        self._enqueue("stream_end", {"stream_id": stream_id})

    # ===== 生命周期 =====

    async def aclose(self) -> None:
        """冲刷待发消息并停掉发送任务；由命令返回后、发持久消息之前调用。

        冲刷有上限：留着一堆发不出去的字幕只会让客户端拿到过期的"滚动文本"，
        而权威文本马上就会以 `character_speech` 补上。
        """
        self._closing = True
        self._wake.set()
        worker, self._worker = self._worker, None
        if worker is None:
            self._report_dropped()
            return
        try:
            await asyncio.wait_for(worker, timeout=FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            worker.cancel()
            logger.warning(
                "stream_flush_timeout",
                extra={
                    "session_id": self._session_id,
                    "wj_extra": {"pending": len(self._pending)},
                },
            )
        except Exception:
            # 发送失败已在 `_drain` 里记过日志，这里不重复
            pass
        self._report_dropped()

    def _report_dropped(self) -> None:
        if self._dropped:
            logger.warning(
                "stream_buffer_overflow_total",
                extra={
                    "session_id": self._session_id,
                    "wj_extra": {"dropped": self._dropped},
                },
            )
            self._dropped = 0  # `aclose` 可重入：别把同一笔丢弃报两遍

    # ===== 内部 =====

    def _enqueue(self, kind: str, payload: dict[str, Any]) -> None:
        if self._closing or self._closed:
            return
        if len(self._pending) >= self._buffer_size:
            # drop-oldest 只针对**字幕增量**：start/end 是协议骨架，把它挤掉等于丢
            # 状态而不是丢字——前端会留一条永远"还在长"的字幕。没有增量可丢时
            # （缓冲里全是控制帧）才退让，丢最旧的那条。
            victim = next(
                (
                    index
                    for index, message in enumerate(self._pending)
                    if message["type"] == "stream_delta"
                ),
                0,
            )
            del self._pending[victim]
            self._dropped += 1
            if self._dropped == 1:
                # 只报第一次：一个卡住的客户端能刷出成千上万条，日志不该跟着淹
                logger.warning(
                    "stream_buffer_overflow",
                    extra={
                        "session_id": self._session_id,
                        "wj_extra": {"buffer_size": self._buffer_size},
                    },
                )
        self._pending.append(
            {"type": kind, "session_id": self._session_id, "payload": payload}
        )
        self._wake.set()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._pending:
                    await self._send(self._pending.popleft())
                if self._closing:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 连接没了。流是瞬态的：丢掉，命令照常跑完落库。
            self._pending.clear()
            logger.warning(
                "stream_channel_send_failed",
                extra={
                    "session_id": self._session_id,
                    "wj_extra": {"reason": str(exc)},
                },
            )
        finally:
            self._closed = True


__all__ = ["DEFAULT_BUFFER_SIZE", "FLUSH_TIMEOUT_SECONDS", "StreamChannel"]
