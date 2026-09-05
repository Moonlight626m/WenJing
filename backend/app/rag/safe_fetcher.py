"""SafePageFetcher：带安全边界的开放网络抓取（issue #10 验收标准 1/2/3/4）。

- 仅 http/https；请求前解析 DNS 并拒绝 loopback/private/link-local/metadata；
  每次重定向跳转前重新做完整校验（`validate_target`）。
- 连接/读取超时、响应体大小上限、并发信号量、content-type 白名单。
- 记录来源：URL / 最终 URL / content-type / 抓取时间 / 内容 hash。
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from app.errx import codes, new, wrap
from app.rag.network import validate_target
from app.rag.providers import FetchedPage

ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 10.0
DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_CONCURRENCY = 4


class SafePageFetcher:
    """PageFetcher 首个实现（httpx）。可注入 client/校验函数便于测试。"""

    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        concurrency: int = DEFAULT_CONCURRENCY,
        client: httpx.AsyncClient | None = None,
        validator: Callable[[str], None] | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_body_bytes = max_body_bytes
        self._max_redirects = max_redirects
        self._semaphore = asyncio.Semaphore(concurrency)
        self._validator = validator or validate_target
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(connect_timeout, read=read_timeout),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SafePageFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def fetch(self, url: str) -> FetchedPage:
        async with self._semaphore:
            return await self._fetch_with_redirects(url, self._max_redirects)

    async def _fetch_with_redirects(self, url: str, redirects_left: int) -> FetchedPage:
        # 每次跳转前都做完整校验（scheme + DNS + 封禁网段）
        try:
            self._validator(url)
        except ValueError as exc:
            raise new(codes.SEARCH_BLOCKED_TARGET, extra={"reason": str(exc)}) from exc

        try:
            resp = await self._client.get(url)
        except httpx.TimeoutException as exc:
            raise new(codes.SEARCH_TIMEOUT, extra={"url": url}) from exc
        except httpx.HTTPError as exc:
            raise wrap(exc, codes.SEARCH_UNAVAILABLE, extra={"url": url}) from exc

        if resp.is_redirect:
            location = resp.headers.get("location")
            if not location or redirects_left <= 0:
                raise new(
                    codes.SEARCH_UNAVAILABLE,
                    extra={"reason": "too many redirects or missing location"},
                )
            next_url = urljoin(str(resp.url), location)
            # 释放当前响应后递归跳转（下一跳重新校验目标）
            return await self._fetch_with_redirects(next_url, redirects_left - 1)

        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            raise new(
                codes.SEARCH_UNAVAILABLE,
                extra={"reason": f"content-type not allowed: {content_type}"},
            )

        body = resp.content
        if len(body) > self._max_body_bytes:
            raise new(
                codes.SEARCH_UNAVAILABLE,
                extra={"reason": "body too large"},
            )

        return FetchedPage(
            url=url,
            final_url=str(resp.url),
            status_code=resp.status_code,
            content_type=content_type,
            body_bytes=body,
            fetched_at=datetime.now(UTC),
            content_hash=hashlib.sha256(body).hexdigest(),
        )
