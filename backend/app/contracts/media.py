"""媒体契约（ADR-0005 §3，issue #42）。

- `AssetUrlResponse`：鉴权端点 `GET /api/assets/{id}/url` 的响应——短时效预签名 URL。
  契约保持 URL-free 的投影（`AssetRef`）不受影响；URL 只在物化响应里出现。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.contracts.base import VersionedContract


class AssetUrlResponse(VersionedContract):
    """资产预签名 URL 物化响应。"""

    asset_id: uuid.UUID
    url: str
    expires_at: datetime


__all__ = ["AssetUrlResponse"]
