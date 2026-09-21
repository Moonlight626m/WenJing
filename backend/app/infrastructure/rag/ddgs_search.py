"""DuckDuckGoSearchProvider：基于 ddgs 的真实网络搜索 adapter（无需 API key）。

- ddgs 是同步库，用 `asyncio.to_thread` 执行避免阻塞事件循环；
- 任何失败统一抛 SEARCH_UNAVAILABLE，由 RagService 按既有约定降级为纯原文；
- 命中 URL 之后由 SafePageFetcher 做同样的 SSRF/DNS 安全校验，本模块不做二次校验。
"""

from __future__ import annotations

import asyncio
from typing import Any

from ddgs import DDGS

from app.infrastructure.errx import codes, wrap
from app.infrastructure.rag.providers import SearchHit

DEFAULT_SEARCH_TIMEOUT = 15


class DuckDuckGoSearchProvider:
    """SearchProvider 协议的 ddgs 实现（开放网络，免费无 key）。"""

    def __init__(self, *, timeout: int = DEFAULT_SEARCH_TIMEOUT) -> None:
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        try:
            raw = await asyncio.to_thread(self._search_sync, query, limit)
        except Exception as exc:
            raise wrap(exc, codes.SEARCH_UNAVAILABLE, extra={"query": query}) from exc
        return [
            SearchHit(
                url=str(item["href"]),
                title=str(item.get("title") or ""),
                snippet=str(item.get("body") or ""),
            )
            for item in raw
            if item.get("href")
        ]

    def _search_sync(self, query: str, limit: int) -> list[dict[str, Any]]:
        with DDGS(timeout=self._timeout) as ddgs:
            return list(ddgs.text(query, max_results=limit))
