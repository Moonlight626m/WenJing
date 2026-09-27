"""开放版权图库检索共用工具（ADR-0005 §6，issue #44）。

- 复用 RAG 的安全抓取器 `SafePageFetcher`（SSRF/DNS 校验、逐跳重定向复核、
  超时、content-type 白名单、响应体上限），仅替换 content-type 白名单与错误码段；
  不再另写一套抓取循环。
- 检索/下载失败统一抛 `MEDIA_SEARCH_*`，由上层（SceneDesigner #47）降级为回退生成。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.infrastructure.errx import codes
from app.infrastructure.rag.safe_fetcher import SafePageFetcher

ALLOWED_IMAGE_TYPES = (
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
)

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_USER_AGENT = "Wenjing/1.0 media-search"


def build_image_fetcher(
    *,
    client: httpx.AsyncClient,
    validator: Callable[[str], None] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SafePageFetcher:
    """构建按图片规则收敛的抓取器：仅图片 content-type、错误码归 MEDIA_SEARCH_*。"""
    return SafePageFetcher(
        client=client,
        validator=validator,
        max_body_bytes=max_bytes,
        allowed_content_types=ALLOWED_IMAGE_TYPES,
        require_content_type=True,
        unavailable_code=codes.MEDIA_SEARCH_FAILED,
        blocked_code=codes.MEDIA_SEARCH_BLOCKED,
        timeout_code=codes.MEDIA_SEARCH_TIMEOUT,
    )


def as_int(value: object) -> int:
    """宽松地把 provider 返回的尺寸/数值转为 int；无法解析按 0（缺省）。"""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


__all__ = [
    "ALLOWED_IMAGE_TYPES",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_USER_AGENT",
    "as_int",
    "build_image_fetcher",
]
