"""PromptStore 的 PostgreSQL 实现（PromptMgr 组件）。

实现 domain/prompts/bundle.py 的 PromptStore 协议：每次生成调用实时读取\
启用中的覆盖段落（spec 裁决：每次用做 DB I/O，不做长缓存）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.models.prompt import PromptTemplate


class DbPromptStore:
    """按 (stage, node, version) 读取启用段落的覆盖层存储。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def load(self, stage: str, node: str, version: str) -> dict[str, str]:
        stmt = (
            select(PromptTemplate.section, PromptTemplate.body)
            .where(
                PromptTemplate.stage == stage,
                PromptTemplate.node == node,
                PromptTemplate.version == version,
                PromptTemplate.enabled.is_(True),
            )
            .order_by(PromptTemplate.section)
        )
        async with self._factory() as session:
            rows = (await session.execute(stmt)).all()
        return {row.section: row.body for row in rows}


__all__ = ["DbPromptStore"]
