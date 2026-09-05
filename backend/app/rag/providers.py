"""RAG 三 adapter 契约（issue #10 验收标准 1）。

纯契约 + 数据结构，零基础设施依赖（不 import httpx/agents/llm）。
首个实现：
- SearchProvider → `NullSearchProvider`（默认空结果，触发降级；真实 provider 待 ADR 选型接入）
- PageFetcher → `app.rag.safe_fetcher.SafePageFetcher`
- DocumentExtractor → `app.rag.html_extractor.HtmlDocumentExtractor`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass
class SearchHit:
    """搜索 provider 返回的单条命中。"""

    url: str
    title: str = ""
    snippet: str = ""


@dataclass
class FetchedPage:
    """抓取结果（含安全元数据，供来源记录）。"""

    url: str
    final_url: str
    status_code: int
    content_type: str | None = None
    body_bytes: bytes = b""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""


@dataclass
class ExtractedDocument:
    """从网页提取的不可信文本（已清洗、已隔离指令内容）。"""

    url: str
    title: str
    text: str
    content_hash: str
    fetched_at: datetime
    untrusted: bool = True  # 网页文本永远标记为不可信（spec 决策）


@runtime_checkable
class SearchProvider(Protocol):
    """搜索 adapter：query → 命中列表。失败抛 SEARCH_UNAVAILABLE。"""

    async def search(self, query: str, *, limit: int = 5) -> list[SearchHit]: ...


@runtime_checkable
class PageFetcher(Protocol):
    """抓取 adapter：url → FetchedPage。SSRF/DNS 校验失败抛 SEARCH_BLOCKED_TARGET。"""

    async def fetch(self, url: str) -> FetchedPage: ...


@runtime_checkable
class DocumentExtractor(Protocol):
    """文档提取 adapter：FetchedPage → 清洗后的不可信文本。"""

    def extract(self, page: FetchedPage) -> ExtractedDocument: ...


class NullSearchProvider:
    """首个 SearchProvider 实现：始终返回空结果。

    用于 MVP「失败降级为纯原文」路径 —— 未配置真实搜索 provider 时，
    RAG 服务据此产出空证据集，不阻塞剧本生成。
    """

    async def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        return []
