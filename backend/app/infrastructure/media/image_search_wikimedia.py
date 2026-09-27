"""Wikimedia Commons 开放版权图片检索 adapter（ADR-0005 §6，issue #44）。

- `commons.wikimedia.org/w/api.php`：`generator=search` 在 File 命名空间检索，
  `prop=imageinfo` 取 `url|size|extmetadata`（许可/作者/许可链接）。
- 优先下载缩放后的 `thumburl`，减少传输体积。
- 逐条下载走 `SafeImageFetcher`（SSRF/超时/体积/content-type 防护）；单条失败跳过。

Wikimedia 要求可识别的 User-Agent（`WENJING_MEDIA_IMAGE_SEARCH_USER_AGENT`）。
检索层失败统一抛 `MEDIA_SEARCH_*`，由上层（SceneDesigner #47）降级为回退生成。
"""

from __future__ import annotations

import html
import re
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

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
DEFAULT_THUMB_WIDTH = 1280

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: object) -> str:
    """去 HTML 标签并反转义实体（extmetadata 的 Artist/Credit 常含 <a>）。"""
    text = _TAG_RE.sub("", str(value or ""))
    return html.unescape(text).strip()


class WikimediaImageSearch:
    """`ImageSearchPort` 的 Wikimedia Commons 实现。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_url: str = WIKIMEDIA_API_URL,
        thumb_width: int = DEFAULT_THUMB_WIDTH,
        user_agent: str = DEFAULT_USER_AGENT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        validator: Callable[[str], None] | None = None,
    ) -> None:
        self._api_url = api_url
        self._thumb_width = thumb_width
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
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": str(self._thumb_width),
        }
        try:
            resp = await self._client.get(self._api_url, params=params)
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise new(codes.MEDIA_SEARCH_TIMEOUT, extra={"url": self._api_url}) from exc
        except httpx.HTTPError as exc:
            raise wrap(exc, codes.MEDIA_SEARCH_FAILED, extra={"reason": str(exc)}) from exc

        try:
            pages = (resp.json().get("query") or {}).get("pages") or []
        except ValueError as exc:
            raise wrap(exc, codes.MEDIA_SEARCH_FAILED, extra={"reason": "invalid json"}) from exc

        candidates: list[ImageCandidate] = []
        for page in pages[:limit]:
            candidate = await self._to_candidate(page)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _to_candidate(self, page: dict) -> ImageCandidate | None:
        infos = page.get("imageinfo") or []
        if not infos:
            return None
        info = infos[0]
        thumb_url = info.get("thumburl")
        url = str(thumb_url or info.get("url") or "")
        if not url:
            return None
        try:
            fetched = await self._fetcher.fetch(url)
        except Error:
            return None

        meta = info.get("extmetadata") or {}
        landing = str(info.get("descriptionurl") or info.get("url") or url)
        # 下载的是缩放图时，尺寸须取 thumbwidth/thumbheight，否则与字节不符。
        width = as_int(info.get("thumbwidth")) if thumb_url else as_int(info.get("width"))
        height = as_int(info.get("thumbheight")) if thumb_url else as_int(info.get("height"))
        return ImageCandidate(
            image_bytes=fetched.body_bytes,
            content_type=fetched.content_type,
            source_url=landing,
            width=width,
            height=height,
            title=_clean_text(page.get("title")).removeprefix("File:").replace("_", " "),
            description=_clean_text(_meta_value(meta, "ImageDescription")),
            credit=AssetCredit(
                author=_clean_text(_meta_value(meta, "Artist"))
                or _clean_text(_meta_value(meta, "Credit")),
                license=_clean_text(_meta_value(meta, "LicenseShortName")),
                source_url=landing,
                license_url=_clean_text(_meta_value(meta, "LicenseUrl")),
            ),
        )


def _meta_value(meta: dict, key: str) -> str:
    entry = meta.get(key)
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return ""


__all__ = ["WIKIMEDIA_API_URL", "WikimediaImageSearch"]
