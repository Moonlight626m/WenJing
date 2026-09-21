"""运营后台 REST 路由（issue #22 / ADR-0002 §5）：仅 `super_admin` 可访问。

- `GET /api/admin/scripts`：跨 org 剧本库列表（可 org/status 过滤）。
- `GET /api/admin/usage`：按 org/时间/用途聚合的 token 用量。
- `GET/PUT /api/admin/prompts`：prompt 覆盖层管理（PromptMgr 组件），
  更新即时生效。教师/学生访问一律 `AUTH_FORBIDDEN`（403）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.contracts.admin import (
    PromptEntry,
    PromptListResponse,
    PromptUpdateRequest,
    UsageAggregateResponse,
)
from app.contracts.enums import ScriptStatus, UsagePurpose, UserRole
from app.contracts.script_library import ScriptListResponse
from app.controllers.auth_deps import Principal, require_role
from app.infrastructure.db.session import SessionLocal
from app.services.admin import AdminService
from app.services.script_projection import script_summary

router = APIRouter(prefix="/api/admin", tags=["admin"])

_service: AdminService | None = None


def get_admin_service() -> AdminService:
    """进程级 AdminService 单例（只读）。"""
    global _service
    if _service is None:
        _service = AdminService(session_factory=SessionLocal)
    return _service


_Admin = Annotated[Principal, Depends(require_role(UserRole.SUPER_ADMIN))]


@router.get("/scripts", response_model=ScriptListResponse)
async def admin_list_scripts(
    principal: _Admin,
    service: Annotated[AdminService, Depends(get_admin_service)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[ScriptStatus | None, Query()] = None,
) -> ScriptListResponse:
    """剧本库列表（跨 org，只读）。"""
    rows = await service.list_scripts(org_id=org_id, status=status)
    return ScriptListResponse(items=[script_summary(r) for r in rows])


@router.get("/usage", response_model=UsageAggregateResponse)
async def admin_usage(
    principal: _Admin,
    service: Annotated[AdminService, Depends(get_admin_service)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    purpose: Annotated[UsagePurpose | None, Query()] = None,
) -> UsageAggregateResponse:
    """token 用量聚合（按 org/时间/用途过滤，只读）。"""
    items = await service.usage_aggregate(
        org_id=org_id, since=since, until=until, purpose=purpose
    )
    return UsageAggregateResponse(items=items, since=since, until=until)


def _prompt_entry(row) -> PromptEntry:  # noqa: ANN001 - ORM 行类型窄
    return PromptEntry(
        stage=row.stage,
        node=row.node,
        version=row.version,
        section=row.section,
        body=row.body,
        description=row.description,
        enabled=row.enabled,
        updated_at=row.updated_at,
    )


@router.get("/prompts", response_model=PromptListResponse)
async def admin_list_prompts(
    principal: _Admin,
    service: Annotated[AdminService, Depends(get_admin_service)],
    stage: Annotated[str | None, Query()] = None,
) -> PromptListResponse:
    """prompt 覆盖层列表（PromptMgr，可按 stage 过滤）。"""
    rows = await service.list_prompts(stage=stage)
    return PromptListResponse(items=[_prompt_entry(r) for r in rows])


@router.put("/prompts/{stage}/{node}/{version}/{section}", response_model=PromptEntry)
async def admin_update_prompt(
    principal: _Admin,
    service: Annotated[AdminService, Depends(get_admin_service)],
    stage: str,
    node: str,
    version: str,
    section: str,
    req: PromptUpdateRequest,
) -> PromptEntry:
    """更新 prompt 覆盖行：即时生效（下次生成调用读到新文案）。"""
    row = await service.upsert_prompt(
        stage=stage,
        node=node,
        version=version,
        section=section,
        body=req.body,
        description=req.description,
        enabled=req.enabled,
    )
    return _prompt_entry(row)


__all__ = ["router", "get_admin_service"]
