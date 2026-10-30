"""剧本生成进度广播中枢（进程内，事件流推送，进程内单 worker）。

教师在详情页盯着生成进度时不该靠 1.5s 轮询——_attempt_sink 每次进度落库
都会广播一份快照，被订阅的 SSE 连接即刻收到。订阅以外仍可 GET 详情（权威
终态与失败详情仍在 attempt 落库面），SSE 只是「立即性」增强，丢一条消息
不会丢状态：前端重连后下一次 GET 会拿到完整进度。

单 worker 前提与 `session_events.SessionEventHub` 相同：注册表在进程内存里，
不做跨进程分发。每订阅一个有界队列，满即丢弃**新到**的快照（进度是终态
可补偿的增强信号，慢客户端下一轮 GET 详情自会拿到最新）。

复用 SessionEventHub：hub 的形状一样（按 key 的队列集合），但 publish 的
对象是 GenerationProgress 快照（dict），签订 session id 也一样是 str key。
不继承了：key 语义不同（script_id vs session_id），而且这里的订阅 key 是
script_id（int → str）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("wenjing.scripts.progress")

# 单连接待发快照上限：一次生成全程几十帧，8 足够吸收瞬时突发；满即丢新帧
# （进度可由 GET 详情补偿）。比 SessionEventHub 的 32 小：这里每帧是整份
# 进度快照（七节点 + doubter 历史），消息更重，慢客户端不值得存太多。
DEFAULT_QUEUE_SIZE = 8


# 生成尝试的终态：SSE 订阅收到其一即收流（前端 lib/api.ts FINAL_GENERATION_STATUSES 镜像）。
FINAL_STATUSES = {"succeeded", "failed", "awaiting_review"}


class GenerationProgressHub:
    """按剧本索引的生成进度订阅注册表 + 进程内投递。"""

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._by_script: dict[str, set[asyncio.Queue[dict]]] = {}

    @contextmanager
    def subscribe(self, script_id: int) -> Iterator[asyncio.Queue[dict]]:
        """登记一条 SSE 连接的投递队列；退出即注销。"""
        key = str(script_id)
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._queue_size)
        self._by_script.setdefault(key, set()).add(queue)
        try:
            yield queue
        finally:
            conns = self._by_script.get(key)
            if conns is not None:
                conns.discard(queue)
                if not conns:
                    del self._by_script[key]

    async def publish(self, script_id: int, snapshot: dict) -> None:
        """投递进度快照到该剧本的所有订阅者；无订阅者零开销。"""
        conns = self._by_script.get(str(script_id))
        if not conns:
            return
        for queue in conns:
            try:
                queue.put_nowait(snapshot)
            except asyncio.QueueFull:
                # 慢客户端：丢弃这条快照，重连/下一轮落库可见
                logger.warning(
                    "generation_progress_queue_full script_id=%s", script_id
                )

    def subscriber_count(self, script_id: int) -> int:
        return len(self._by_script.get(str(script_id), ()))


__all__ = ["FINAL_STATUSES", "GenerationProgressHub"]
