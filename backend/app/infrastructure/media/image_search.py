"""`ImageSearchPort` 工厂：按配置选择检索 provider（ADR-0005 §6，issue #44）。

- `null`：不检索，始终空候选（安全降级）。
- `openverse` / `wikimedia`：开放版权图库 adapter。

provider 取值由 `Settings` 的 Literal 约束，非法值启动即报错（不静默回落）。
"""

from __future__ import annotations

from app.domain.game.media import ImageSearchPort
from app.infrastructure.config import Settings
from app.infrastructure.errx import codes, new
from app.infrastructure.media.image_search_openverse import OpenverseImageSearch
from app.infrastructure.media.image_search_wikimedia import WikimediaImageSearch
from app.infrastructure.media.null import NullImageSearch


def build_image_search(settings: Settings) -> ImageSearchPort:
    """按 `media_image_search_provider` 构建检索端口。"""
    provider = settings.media_image_search_provider
    if provider == "null":
        return NullImageSearch()
    if provider == "openverse":
        return OpenverseImageSearch(
            token=settings.media_image_search_openverse_token,
            user_agent=settings.media_image_search_user_agent,
            connect_timeout=settings.media_image_search_connect_timeout,
            read_timeout=settings.media_image_search_read_timeout,
            max_bytes=settings.media_image_search_max_bytes,
        )
    if provider == "wikimedia":
        return WikimediaImageSearch(
            user_agent=settings.media_image_search_user_agent,
            connect_timeout=settings.media_image_search_connect_timeout,
            read_timeout=settings.media_image_search_read_timeout,
            max_bytes=settings.media_image_search_max_bytes,
        )
    raise new(codes.CFG_UNKNOWN_MEDIA_PROVIDER, extra={"provider": provider})


__all__ = ["build_image_search"]
