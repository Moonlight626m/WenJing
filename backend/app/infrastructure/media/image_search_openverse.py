"""Openverse 开放版权图片检索 adapter（ADR-0005 §6，issue #44）。

- `GET {base}/images/?q=&page_size=`：匿名可用（限流），配置 token 后走 Bearer 提额。
- 候选携带许可元数据（license/creator/license_url/foreign_landing_url）。
- 逐条下载候选图片走 `SafeImageFetcher`（SSRF/超时/体积/content-type 防护）；
  单条失败跳过，不阻断整体检索。

任何检索层失败统一抛 `MEDIA_SEARCH_*`，由上层（SceneDesigner #47）降级为回退生成。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.domain.game.media import AssetCredit, ImageCandidate
from app.infrastructure.errx import Error, codes, new, wrap
from app.infrastructure.media.image_search_common import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_MAX_BYTES,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_USER_AGENT,
    as_int,
    build_image_fetcher,
)

OPENVERSE_BASE_URL = "https://api.openverse.org/v1"


class OpenverseImageSearch:
    """`ImageSearchPort` 的 Openverse 实现。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        token: str = "",
        base_url: str = OPENVERSE_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        validator: Callable[[str], None] | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(connect_timeout, read=read_timeout),
            headers={"User-Agent": user_agent},
        )
        self._fetcher = build_image_fetcher(
            client=self._client,
            validator=validator,
            max_bytes=max_bytes,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, *, query: str, limit: int = 4) -> list[ImageCandidate]:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            resp = await self._client.get(
                f"{self._base_url}/images/",
                params={"q": query, "page_size": limit},
                headers=headers,
            )
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise new(
                codes.MEDIA_SEARCH_TIMEOUT, extra={"url": f"{self._base_url}/images/"}
            ) from exc
        except httpx.HTTPError as exc:
            raise wrap(exc, codes.MEDIA_SEARCH_FAILED, extra={"reason": str(exc)}) from exc

        try:
            results = resp.json().get("results") or []
        except ValueError as exc:
            raise wrap(exc, codes.MEDIA_SEARCH_FAILED, extra={"reason": "invalid json"}) from exc

        candidates: list[ImageCandidate] = []
        for item in results[:limit]:
            candidate = await self._to_candidate(item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _to_candidate(self, item: dict) -> ImageCandidate | None:
        url = str(item.get("url") or item.get("thumbnail") or "")
        if not url:
            return None
        try:
            page = await self._fetcher.fetch(url)
        except Error:
            return None

        landing = str(item.get("foreign_landing_url") or url)
        license_name = " ".join(
            part
            for part in (str(item.get("license") or ""), str(item.get("license_version") or ""))
            if part
        ).upper()
        return ImageCandidate(
            image_bytes=page.body_bytes,
            content_type=page.content_type,
            source_url=landing,
            width=as_int(item.get("width")),
            height=as_int(item.get("height")),
            title=str(item.get("title") or ""),
            description=str(item.get("description") or ""),
            credit=AssetCredit(
                author=str(item.get("creator") or ""),
                license=license_name,
                source_url=landing,
                license_url=str(item.get("license_url") or ""),
            ),
        )


__all__ = ["OPENVERSE_BASE_URL", "OpenverseImageSearch"]
