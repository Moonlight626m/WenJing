"""数据库工具：建表 + 引擎接持久化工厂。

- `init_db()`：按 ORM 元数据在目标 Postgres 建表（幂等，速度开发用；正式走 Alembic）。
- `build_engine_with_db()`：构造接持久化的 `GameEngine`，把落库回调挂到
  `PersistentEventStore`。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import app.models  # noqa: F401  # 注册 ORM 元数据到 Base.metadata
from app.core.game_engine import GameEngine
from app.core.types import Script
from app.db.event_store import PersistentEventStore
from app.db.session import Base, SessionLocal


async def init_db() -> None:
    """按 ORM 元数据在目标数据库建表（幂等，供开发；正式迁移走 Alembic）。"""
    from app.db.session import create_engine

    engine = create_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


def make_db_flush(
    event_store: PersistentEventStore, session_id: str
) -> Callable[[], Awaitable[None]]:
    """返回落库回调：把待落库事件写入 DB 并提交。"""

    async def _flush() -> None:
        async with SessionLocal() as session:
            await event_store.flush(session, session_id)

    return _flush


def build_engine_with_db(
    *,
    session_id: str,
    script: Script,
    llm: object,
    config=None,
    enable_logging: bool = True,
) -> tuple[GameEngine, PersistentEventStore]:
    """构造引擎并挂接持久化事件存储（每轮 phase 结束后落库）。"""
    store = PersistentEventStore()
    engine = GameEngine(
        session_id=session_id,
        script=script,
        llm=llm,
        config=config,
        enable_logging=enable_logging,
        event_store=store,
        on_flush=make_db_flush(store, session_id),
    )
    return engine, store
