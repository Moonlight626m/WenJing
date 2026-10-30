"""每连接的音轨出口（ADR-0005 §11，issue #63 M6）。

与 `StreamChannel` 的分工：那边送**文本**字幕（JSON 帧），这边送**音频**（控制帧
JSON + 音频二进制帧）。两者都是连接级瞬态出口，都不进 outbox、都没有 seq。

四条与 ADR-0005 §11 对应的取舍：

- **不混音**：一条发言一条音轨，`track_id` 各自独立。多角色并发时前端同时挂多个
  `<audio>`；后端把两路音频混成一路会永久丢掉"谁在说话"，而字幕、重播、barge-in
  都要用它。
- **有限缓冲 + drop-oldest**：与字幕同理，慢客户端不能把合成拖住。但**音频比字幕
  更不可丢**——丢一段字幕少看几个字，丢一段音频是整句话断掉。所以这里的缓冲按
  **整条音轨**计数，溢出时丢最旧的那条**完整**音轨（`audio_end` 一并丢），
  而不是在一条音轨中间截断（截断的 MP3 在浏览器里是噪音）。
- **barge-in 只作用于音轨**：`cancel(track_id)` 丢弃尚未发出的该轨数据。它**不**
  打断命令——命令串行 + 事件同事务持久化是引擎地基，服务端在生成中本就收不到新
  命令（ADR-0005 §11）。
- **发送失败即停**：连接没了就关通道，命令照常跑完落库。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("wenjing.session.audio")

#: 单连接待发音轨数上限。一条发言几十句，8 条足够吸收一次网络抖动。
DEFAULT_MAX_TRACKS = 8
#: 收流时的冲刷上限（秒）：慢客户端不能把 WS 处理循环拖住。
FLUSH_TIMEOUT_SECONDS = 1.0


class AudioTrackChannel:
    """连接级的音轨出口：控制帧 + 二进制帧，有界缓冲 + 整轨淘汰。

    `send_json` / `send_bytes` 分开注入，因为 WS 的两种帧类型在传输层就是分开的
    （`ws.send_json` / `ws.send_bytes`）；把它们合成一个回调只会让实现方去猜类型。
    """

    def __init__(
        self,
        session_id: uuid.UUID | str,
        send_json: Callable[[dict[str, Any]], Awaitable[None]],
        send_bytes: Callable[[bytes], Awaitable[None]],
        *,
        max_tracks: int = DEFAULT_MAX_TRACKS,
    ) -> None:
        self._session_id = str(session_id)
        self._send_json = send_json
        self._send_bytes = send_bytes
        self._max_tracks = max(1, max_tracks)
        #: 待发队列：(track_id, 帧)。track_id 与帧**一起**入队——裸二进制帧自己
        #: 不带归属信息，靠外部下标表记录归属会在整轨淘汰后失效（#63 自查）。
        self._pending: deque[tuple[str, dict[str, Any] | bytes]] = deque()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._closing = False
        self._closed = False
        self._dropped = 0
        #: 待发队列排空时置位。`flush` 等它，用来把"发完这批"与"关掉通道"分开。
        self._drained = asyncio.Event()
        self._drained.set()
        #: 被 barge-in 取消掉的轨。取消是**持久**的：合成器可能还在往这条轨里
        #: 推帧（它不知道客户端停了），不记下来就会把刚取消的音频又发出去。
        self._cancelled: set[str] = set()

    # ===== AudioTrackSink =====

    def start(self, speaker: str, *, content_type: str, sample_rate: int = 0) -> str:
        track_id = uuid.uuid4().hex
        self._enqueue_json(
            "audio_start",
            {
                "track_id": track_id,
                "speaker": speaker,
                "codec": content_type,
                "sample_rate": sample_rate,
            },
            track_id=track_id,
        )
        return track_id

    def chunk(self, track_id: str, data: bytes) -> None:
        if not data:
            return
        self._enqueue(data, track_id=track_id)

    def end(self, track_id: str) -> None:
        self._enqueue_json("audio_end", {"track_id": track_id}, track_id=track_id)

    def cancel(self, track_id: str) -> bool:
        """barge-in：丢弃尚未发出的该轨数据，返回是否确实取消了一条在途音轨。

        只清**待发队列**里的帧：已经写进 socket 的字节收不回来（客户端那边由
        `cancel_audio` 自己停播——`<audio>.pause()` 才是真正的"停"）。
        """
        self._cancelled.add(track_id)
        remaining = deque(
            (tid, frame) for tid, frame in self._pending if tid != track_id
        )
        if len(remaining) == len(self._pending):
            return False  # 该轨已经发完了，没什么可取消（但后续帧仍会被拦）
        self._pending = remaining
        self._dropped += 1
        logger.info(
            "audio_track_cancelled",
            extra={"session_id": self._session_id, "wj_extra": {"track_id": track_id}},
        )
        return True

    # ===== 生命周期 =====

    async def flush(self) -> None:
        """把已入队的帧发完，**不**关闭通道。命令返回前调用。

        与 `aclose` 分开是必须的：音轨出口是**连接级**的（一条连接一个），而命令
        是一条条来的。若每条命令都 `aclose`，`_closing` 会在第一条命令后就永久置位，
        之后每条命令的音频都被静默吞掉——只有第一个说话的角色有声音（#63 自查抓到
        的 bug，被 WS 端到端用例逮住）。
        """
        if not self._pending:
            return
        self._wake.set()
        try:
            await asyncio.wait_for(self._drained.wait(), timeout=FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning(
                "audio_flush_timeout",
                extra={
                    "session_id": self._session_id,
                    "wj_extra": {"pending": len(self._pending)},
                },
            )
        except Exception:
            pass  # 发送失败已在 `_drain` 里记过日志

    async def aclose(self) -> None:
        """冲刷待发帧并停掉发送任务；**连接**结束时调用（不是每条命令）。"""
        await self.flush()
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
        except Exception:
            pass  # 发送失败已在 `_drain` 里记过日志
        self._report_dropped()

    def _report_dropped(self) -> None:
        if self._dropped:
            logger.warning(
                "audio_track_dropped_total",
                extra={
                    "session_id": self._session_id,
                    "wj_extra": {"dropped": self._dropped},
                },
            )
            self._dropped = 0

    # ===== 内部 =====

    def _enqueue_json(self, kind: str, payload: dict[str, Any], *, track_id: str) -> None:
        self._enqueue(
            {"type": kind, "session_id": self._session_id, "payload": payload},
            track_id=track_id,
        )

    def _enqueue(self, frame: dict[str, Any] | bytes, *, track_id: str) -> None:
        if self._closing or self._closed or track_id in self._cancelled:
            return
        self._evict_for(track_id)
        self._pending.append((track_id, frame))
        self._drained.clear()
        self._wake.set()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())

    def _evict_for(self, incoming: str) -> None:
        """为即将入队的 `incoming` 腾位：丢**最旧的整条别的**音轨（含 `audio_end`）。

        两条边界，都是"音频不能像字幕那样丢"的直接后果：

        - **不截断**：丢就丢一整条。一条 MP3 被拦腰截断在浏览器里是噪音，
          比整句没有更糟。
        - **不淘汰自己**：`incoming` 正在被写入，它一个人就占满了配额时若按
          "丢最旧"处理，会把正在推的那条轨自己丢掉（#63 自查抓到的 bug）。
          故计数与淘汰都排除 `incoming`。
        """
        while self._others(incoming) >= self._max_tracks and self._pending:
            oldest = next(
                (tid for tid, _ in self._pending if tid and tid != incoming), None
            )
            if oldest is None:
                return
            self._pending = deque(
                (tid, frame) for tid, frame in self._pending if tid != oldest
            )
            self._dropped += 1
            if self._dropped == 1:
                logger.warning(
                    "audio_buffer_overflow",
                    extra={
                        "session_id": self._session_id,
                        "wj_extra": {"max_tracks": self._max_tracks},
                    },
                )

    def _others(self, track_id: str) -> int:
        """缓冲里除 `track_id` 外的音轨数。"""
        return len({tid for tid, _ in self._pending if tid and tid != track_id})

    async def _drain(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._pending:
                    _, frame = self._pending.popleft()
                    if isinstance(frame, bytes):
                        await self._send_bytes(frame)
                    else:
                        await self._send_json(frame)
                self._drained.set()
                if self._closing:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._pending.clear()
            # 队列没了也要放行 `flush`，否则它只能干等到超时
            self._drained.set()
            logger.warning(
                "audio_channel_send_failed",
                extra={
                    "session_id": self._session_id,
                    "wj_extra": {"reason": str(exc)},
                },
            )
        finally:
            self._closed = True


__all__ = ["DEFAULT_MAX_TRACKS", "FLUSH_TIMEOUT_SECONDS", "AudioTrackChannel"]
