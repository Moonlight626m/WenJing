"""资产 REST 路由（ADR-0005 §3，issue #42）。

薄协议层：鉴权 → 委托 `AssetAccessService` → 契约响应。URL 物化只在经授权后发生；
投影层（RuntimeState/ScriptPackage）始终 URL-free。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.composition import get_container
from app.contracts.enums import UserRole
from app.contracts.media import AssetUrlResponse
from app.controllers.auth_deps import Principal, require_role

router = APIRouter(prefix="/api", tags=["assets"])

_Viewer = Annotated[
    Principal,
    Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
]


@router.get("/assets/{asset_id}/url", response_model=AssetUrlResponse)
async def asset_url(asset_id: uuid.UUID, principal: _Viewer) -> AssetUrlResponse:
    """校验 actor 归属后签发短时效预签名 URL。"""
    result = await get_container().asset_access.url_for(principal.actor, asset_id)
    return AssetUrlResponse(
        asset_id=result.asset_id, url=result.url, expires_at=result.expires_at
    )
