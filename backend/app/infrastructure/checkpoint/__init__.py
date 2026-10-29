"""LangGraph checkpointer 的 PostgreSQL 适配（ADR-0003 教师闸门）。

`saver_pool` 是 AsyncPostgresSaver + 连接池的唯一构造点：psycopg 连接默认
autocommit=False，而 `AsyncPostgresSaver.setup()` 里的 CREATE INDEX CONCURRENTLY
不能在事务块内执行——这条不变量只在这里说一次，composition 与测试都从这里拿。
"""

from app.infrastructure.checkpoint.pool import saver_pool

__all__ = ["saver_pool"]
