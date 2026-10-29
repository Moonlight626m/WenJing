"""checkpointer 适配器：AsyncPostgresSaver 的连接池构造唯一入口。"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


def saver_pool(conninfo: str) -> AsyncConnectionPool:
    """为 AsyncPostgresSaver 建连接池；调用方负责 open/close 与 saver.setup()。

    autocommit 必须开：psycopg 默认事务语义下 setup() 的 CREATE INDEX
    CONCURRENTLY 直接炸（ActiveSqlTransaction）。langgraph 自带的
    from_conn_string 就是 autocommit=True，这里绕开它裸建池时不能丢掉这一条。
    """
    return AsyncConnectionPool(
        conninfo=conninfo, open=False, min_size=1, kwargs={"autocommit": True}
    )
