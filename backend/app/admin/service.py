"""运营后台应用服务（issue #22 / ADR-0002 §5）。

**只读**：跨 org 剧本库列表 + 按 org/时间/用途聚合的 token 用量。
访问控制由路由层的 `super_admin` 角色门负责；本层不改变任何状态。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.admin import UsageAggregateRow
from app.contracts.enums import ScriptStatus, UsagePurpose
from app.models.llm_usage import LlmUsage
from app.models.script import Script as ScriptRecord


class AdminService:
    """运营后台唯一业务入口（REST 之下）。"""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def list_scripts(
        self,
        *,
        org_id: uuid.UUID | None = None,
        status: ScriptStatus | None = None,
        limit: int = 200,
    ) -> list[ScriptRecord]:
        """剧本库列表（跨 org）：按最近更新倒序，可选 org / 状态过滤。"""
        stmt = select(ScriptRecord)
        if org_id is not None:
            stmt = stmt.where(ScriptRecord.org_id == org_id)
        if status is not None:
            stmt = stmt.where(ScriptRecord.status == status.value)
        stmt = stmt.order_by(ScriptRecord.updated_at.desc()).limit(limit)
        async with self._factory() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return list(rows)

    async def usage_aggregate(
        self,
        *,
        org_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        purpose: UsagePurpose | None = None,
    ) -> list[UsageAggregateRow]:
        """按 (org, purpose) 聚合 token 用量；支持 org / 时间窗 / 用途过滤。"""
        stmt = select(
            LlmUsage.org_id,
            LlmUsage.purpose,
            func.sum(LlmUsage.prompt_tokens).label("prompt_tokens"),
            func.sum(LlmUsage.completion_tokens).label("completion_tokens"),
            func.sum(LlmUsage.total_tokens).label("total_tokens"),
            func.count(LlmUsage.id).label("call_count"),
        )
        if org_id is not None:
            stmt = stmt.where(LlmUsage.org_id == org_id)
        if since is not None:
            stmt = stmt.where(LlmUsage.created_at >= since)
        if until is not None:
            stmt = stmt.where(LlmUsage.created_at <= until)
        if purpose is not None:
            stmt = stmt.where(LlmUsage.purpose == purpose.value)
        stmt = stmt.group_by(LlmUsage.org_id, LlmUsage.purpose).order_by(
            LlmUsage.org_id, LlmUsage.purpose
        )
        async with self._factory() as s:
            rows = (await s.execute(stmt)).all()
        return [
            UsageAggregateRow(
                org_id=row.org_id,
                purpose=UsagePurpose(row.purpose),
                prompt_tokens=int(row.prompt_tokens or 0),
                completion_tokens=int(row.completion_tokens or 0),
                total_tokens=int(row.total_tokens or 0),
                call_count=int(row.call_count or 0),
            )
            for row in rows
        ]


__all__ = ["AdminService"]
