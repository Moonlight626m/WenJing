"""运营后台应用服务（issue #22 / ADR-0002 §5）。

- 只读部分：跨 org 剧本库列表 + 按 org/时间/用途聚合的 token 用量；
- prompt 管理（PromptMgr 组件）：覆盖层读写，更新即时生效（下次生成调用）。
访问控制由路由层的 `super_admin` 角色门负责。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.admin import UsageAggregateRow
from app.contracts.enums import ScriptStatus, UsagePurpose
from app.infrastructure.errx import codes, new
from app.infrastructure.models.llm_usage import LlmUsage
from app.infrastructure.models.prompt import PromptTemplate
from app.infrastructure.models.script import Script as ScriptRecord


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


    async def list_prompts(self, *, stage: str | None = None) -> list[PromptTemplate]:
        """prompt 覆盖层列表：按 stage/节点/版本/段落排序。"""
        stmt = select(PromptTemplate).order_by(
            PromptTemplate.stage,
            PromptTemplate.node,
            PromptTemplate.version,
            PromptTemplate.section,
        )
        if stage is not None:
            stmt = stmt.where(PromptTemplate.stage == stage)
        async with self._factory() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return list(rows)

    async def upsert_prompt(
        self,
        *,
        stage: str,
        node: str,
        version: str,
        section: str,
        body: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> PromptTemplate:
        """更新或创建一条覆盖行；更新即时生效（下次生成调用读到）。

        PATCH 语义：只写入请求中显式提供的字段——未提供的字段（含
        description/enabled）保持原值，不做静默重置。新建行必须携带 body。
        """
        async with self._factory() as s:
            existing = (
                await s.execute(
                    select(PromptTemplate).where(
                        PromptTemplate.stage == stage,
                        PromptTemplate.node == node,
                        PromptTemplate.version == version,
                        PromptTemplate.section == section,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                if body is None:
                    raise new(
                        codes.PRT_MALFORMED_MESSAGE,
                        extra={
                            "reason": "prompt row not found; body is required to create",
                            "key": f"{stage}/{node}/{version}/{section}",
                        },
                    )
                row = PromptTemplate(
                    stage=stage,
                    node=node,
                    version=version,
                    section=section,
                    body=body,
                    description=description,
                    enabled=True if enabled is None else enabled,
                )
                s.add(row)
                await s.commit()
                return row

            if body is not None:
                existing.body = body
            if description is not None:
                existing.description = description
            if enabled is not None:
                existing.enabled = enabled
            await s.commit()
            return existing


__all__ = ["AdminService"]
