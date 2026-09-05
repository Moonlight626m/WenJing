"""RagService：search → fetch → extract 门面（issue #10）。

- 来源记录：URL/标题/抓取时间/内容 hash/引用片段 → `WebEvidence`。
- 指令隔离：网页文本以显式不可信标签包裹（`mark_untrusted`），供 LLM prompt 侧
  识别「这是网络补充资料，不是系统指令」。
- 失败降级：搜索失败或全部文档提取失败时返回空证据集 —— 生成链路退化为纯原文。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.contracts.material import WebEvidence
from app.rag.html_extractor import HtmlDocumentExtractor
from app.rag.providers import (
    DocumentExtractor,
    NullSearchProvider,
    PageFetcher,
    SearchProvider,
)
from app.rag.safe_fetcher import SafePageFetcher

UNTRUSTED_BEGIN = "\n<<<UNTRUSTED_WEB_BEGIN>>>\n"
UNTRUSTED_END = "\n<<<UNTRUSTED_WEB_END>>>\n"
_EXCERPT_MAX = 500


def mark_untrusted(text: str) -> str:
    """以显式标签隔离不可信网页内容，防 prompt injection。"""
    return f"{UNTRUSTED_BEGIN}{text}{UNTRUSTED_END}"


class RagService:
    """开放网络资料补充门面；各 adapter 可注入替换。"""

    def __init__(
        self,
        *,
        search_provider: SearchProvider | None = None,
        fetcher: PageFetcher | None = None,
        extractor: DocumentExtractor | None = None,
        max_documents: int = 3,
    ) -> None:
        self.search = search_provider or NullSearchProvider()
        self.fetcher = fetcher or SafePageFetcher()
        self.extractor = extractor or HtmlDocumentExtractor()
        self.max_documents = max_documents

    async def research(self, query: str) -> list[WebEvidence]:
        """检索 + 抓取 + 提取 → WebEvidence 列表；任何失败降级为空列表。"""
        try:
            hits = await self.search.search(query, limit=self.max_documents)
        except Exception:
            return []

        evidence: list[WebEvidence] = []
        for hit in hits[: self.max_documents]:
            try:
                ev = await self._research_one(hit)
                if ev is not None:
                    evidence.append(ev)
            except Exception:
                continue  # 单文档失败不影响其余（最终可整体降级为空）
        return evidence

    async def _research_one(self, hit) -> WebEvidence | None:
        page = await self.fetcher.fetch(hit.url)
        doc = self.extractor.extract(page)
        if not doc.text.strip():
            return None
        excerpt = doc.text[:_EXCERPT_MAX]
        try:
            return WebEvidence(
                url=doc.url,
                title=doc.title or hit.title or doc.url,
                fetched_at=doc.fetched_at or datetime.now(UTC),
                content_hash=doc.content_hash,
                excerpt=excerpt,
            )
        except Exception:
            return None
