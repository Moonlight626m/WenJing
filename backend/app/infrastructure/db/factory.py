"""数据库工具：引擎接持久化工厂。

- 正式建库路径只有 Alembic 迁移（`make migrate`）；此前的 `init_db()`/create_all
  已按 issue #4 验收标准移除。
- `build_runtime_with_db()`：构造接持久化的 command/step `GameRuntime`（issue #7），
  把落库回调挂到 `PersistentEventStore`。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import app.infrastructure.models  # noqa: F401  # 注册 ORM 元数据到 Base.metadata
from app.domain.game.game_runtime import GameRuntime
from app.domain.game.types import Script
from app.infrastructure.db.event_store import PersistentEventStore
from app.infrastructure.db.session import SessionLocal


def make_db_flush(
    event_store: PersistentEventStore, session_id: str
) -> Callable[[], Awaitable[None]]:
    """返回落库回调：把待落库事件写入 DB 并提交。"""

    async def _flush() -> None:
        async with SessionLocal() as session:
            await event_store.flush(session, session_id)

    return _flush


def build_runtime_with_db(
    *,
    session_id: str,
    script: Script,
    llm: object,
    config=None,
) -> tuple[GameRuntime, PersistentEventStore]:
    """构造运行时并挂接持久化事件存储（每个稳定交互点后落库）。"""
    store = PersistentEventStore()
    runtime = GameRuntime(
        session_id=session_id,
        script=script,
        llm=llm,  # type: ignore[arg-type]
        config=config,
        event_store=store,
        on_flush=make_db_flush(store, session_id),
    )
    return runtime, store
