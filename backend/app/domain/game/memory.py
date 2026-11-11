"""`MemoryStore` 端口（stage3-chronicle-redesign §1.3）。

记忆模块实例化的存储抽象：角色/实例的私有知识、公开编年史、私有事件日志都
经它读写。事件仍然是权威——文件/SQLite 只是实例内的持久化载体，不是第二份
真相；换实现（文件 → SQLite → Postgres）不动上层语义。

相对设计草图的两处落地差异：
- 全部方法 async：上层是 asyncio 调用链，同步 fsync 会阻塞事件循环；
- 读方法叫 `read_events`（返回列表），限知过滤由 `chronicle(viewer=…)`
  承担（§3.2），因此 `read_events` 不接受 `viewer`。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from app.domain.game.event import GameEvent


@runtime_checkable
class MemoryStore(Protocol):
    """实例记忆存储端口。"""

    async def open(self, *, script_name: str = "") -> None: ...

    async def close(self) -> None: ...

    async def append_event(
        self, event: GameEvent, *, character: str | None = None
    ) -> None: ...

    async def sync_events(self, events: Iterable[GameEvent]) -> None: ...

    async def read_events(self, *, limit: int | None = None) -> list[GameEvent]: ...

    async def chronicle(self, *, viewer: str | None = None) -> str: ...

    async def private_knowledge(self, character: str) -> tuple[str, ...]: ...

    async def save_private_knowledge(self, character: str, items: list[str]) -> None: ...


__all__ = ["MemoryStore"]
