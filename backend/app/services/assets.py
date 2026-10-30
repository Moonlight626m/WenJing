"""资产访问服务（ADR-0005 §3，issue #42）：鉴权 + 预签名 URL 物化。

投影层保持纯函数且 URL-free；预签名 URL 只在经授权的物化响应里出现。
授权按资产归属分派（ADR-0002 §3/§6）：
- 运行期资产（`session_id`）→ 仅会话 owner（`require_session_access`）；
- 生成期资产（`script_id`）→ 剧本可见性（`script_visible_to`：owner / 已发布且同 org/public）；
- 纯 org 资产 → 同 org 可读。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.access import Actor, require_session_access, script_visible_to
from app.domain.game.media import AssetRecord, AssetRepositoryPort, AssetStatus, ObjectStoragePort
from app.infrastructure.errx import codes, new
from app.infrastructure.models.script import Script
from app.infrastructure.models.session import Session


@dataclass(frozen=True)
class AssetUrl:
    """物化后的资产访问信息（应用层返回，controller 转契约）。"""

    asset_id: uuid.UUID
    url: str
    expires_at: datetime


class AssetAccessService:
    """按 actor 归属签发资产短时效预签名 URL。"""

    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        storage: ObjectStoragePort,
        session_factory: async_sessionmaker[AsyncSession],
        presign_ttl: int = 900,
    ) -> None:
        self._assets = assets
        self._storage = storage
        self._factory = session_factory
        self._ttl = presign_ttl

    async def url_for(self, actor: Actor, asset_id: uuid.UUID) -> AssetUrl:
        record = await self._assets.get_by_id(asset_id)
        if record is None:
            raise new(codes.MEDIA_ASSET_NOT_FOUND, extra={"asset_id": str(asset_id)})
        await self._authorize(actor, record)
        if record.status is not AssetStatus.READY:
            raise new(
                codes.MEDIA_ASSET_NOT_READY,
                extra={"asset_id": str(asset_id), "status": record.status.value},
            )
        url = await self._storage.presign(
            object_key=record.object_key, ttl_seconds=self._ttl
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl)
        return AssetUrl(asset_id=record.asset_id, url=url, expires_at=expires_at)

    async def _authorize(self, actor: Actor, record: AssetRecord) -> None:
        if record.session_id is not None:
            row = await self._load(Session, record.session_id)
            if row is None:
                raise new(
                    codes.MEDIA_ASSET_NOT_FOUND, extra={"asset_id": str(record.asset_id)}
                )
            require_session_access(actor, row)  # 非 owner 抛 403
            return
        if record.script_id is not None:
            row = await self._load(Script, record.script_id)
            if row is None:
                raise new(
                    codes.MEDIA_ASSET_NOT_FOUND, extra={"asset_id": str(record.asset_id)}
                )
            if not script_visible_to(actor, row):
                raise new(codes.AUTH_FORBIDDEN, extra={"reason": "script not visible"})
            return
        if record.org_id != actor.org_id:
            raise new(codes.AUTH_FORBIDDEN, extra={"reason": "asset org mismatch"})

    async def _load(self, model: Any, pk: Any) -> Any | None:
        async with self._factory() as session:
            return await session.get(model, pk)


__all__ = ["AssetAccessService", "AssetUrl"]
