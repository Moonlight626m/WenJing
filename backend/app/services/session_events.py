"""会话 WS 广播中枢（进程内，ADR-0005 §5 / issue #56）。

命令外事件路径（运行期配图就绪）不在任何请求上下文里产生，没有一条 WebSocket
循环可以顺手把消息发出去——它需要一个按会话索引的投递点，本模块就是那个投递点。

单 worker 前提：注册表在进程内存里（与「会话运行时、在途生成」同一条约束，
见 `README.md` 生产部署一节）。多 worker / 多副本下每个进程只会推给自己那几条
连接，因此**不做**跨进程分发，也不假装能做。

背压：每连接一个有界队列，满即丢弃并记 warning。运行期配图是**可丢**的增强——
消息不进事件流之外的第二份存储，前端下次 `session_init` / `resync` 会从事件流
重建（`project_messages` 会把 `asset_ready` 事件重新投影出来），所以这里丢一条
不会丢状态，只丢一次「立即换图」的时机。流式字幕的限流/取消是 M5（#60）的课题。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

logger = logging.getLogger("wenjing.session.events")

# 单连接待发消息上限：命令批次一条 typ. 几条消息，32 足够吸收一次突发。
DEFAULT_QUEUE_SIZE = 32


class SessionEventHub:
    """按会话索引的连接注册表 + 进程内投递。"""

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._by_session: dict[str, set[asyncio.Queue[dict]]] = {}

    @contextmanager
    def subscribe(self, session_id: uuid.UUID | str) -> Iterator[asyncio.Queue[dict]]:
        """登记一条连接，产出它专属的投递队列；退出即注销。

        `with` 而非 `async with`：登记/注销都是纯内存操作，没有 await 点，
        不需要把调用方的清理路径变成异步的。
        """
        key = str(session_id)
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._queue_size)
        self._by_session.setdefault(key, set()).add(queue)
        try:
            yield queue
        finally:
            conns = self._by_session.get(key)
            if conns is not None:
                conns.discard(queue)
                if not conns:
                    del self._by_session[key]

    async def publish(
        self, session_id: uuid.UUID | str, messages: Iterable[dict]
    ) -> int:
        """把消息投递给该会话的每条连接；返回**收到至少一条消息的连接数**。

        计数口径是「连接」不是「消息」：调用方（`SessionApplication`）用它回答
        "这次有没有人在线"，一条消息被两条连接收下记 2，一条都没收下记 0。
        无连接（玩家不在线）不是错误：消息本来就是可丢的增强，事件流才是权威。
        """
        conns = self._by_session.get(str(session_id))
        if not conns:
            return 0
        reached: set[asyncio.Queue[dict]] = set()
        for message in messages:
            for queue in conns:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    # 丢弃而非阻塞：见模块 docstring 的背压说明
                    logger.warning(
                        "session_event_dropped",
                        extra={
                            "session_id": str(session_id),
                            "reason": "queue full",
                            "type": message.get("type"),
                        },
                    )
                    continue
                reached.add(queue)
        return len(reached)

    def subscriber_count(self, session_id: uuid.UUID | str) -> int:
        return len(self._by_session.get(str(session_id), ()))


__all__ = ["DEFAULT_QUEUE_SIZE", "SessionEventHub"]
