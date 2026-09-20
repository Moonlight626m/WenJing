"""RagService：search → fetch → extract 门面（issue #10）。

- 来源记录：URL/标题/抓取时间/内容 hash/引用片段 → `WebEvidence`。
- 指令隔离：网页文本以显式不可信标签包裹（`mark_untrusted`，见
  domain/content/trust.py），供 LLM prompt 侧识别「这是网络补充资料，不是系统指令」。
- 失败降级：搜索失败或全部文档提取失败时返回空证据集 —— 生成链路退化为纯原文。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.contracts.material import WebEvidence
from app.infrastructure.diagnostics.logging import exc_reason
from app.infrastructure.rag.html_extractor import HtmlDocumentExtractor
from app.infrastructure.rag.providers import (
    DocumentExtractor,
    NullSearchProvider,
    PageFetcher,
    SearchProvider,
)
from app.infrastructure.rag.safe_fetcher import SafePageFetcher

logger = logging.getLogger("wenjing.rag.service")

_EXCERPT_MAX = 500


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
        except Exception as exc:
            # 上游搜索失败，降级为纯原文前先告警
            logger.warning(
                "rag_search_failed_degrade_to_source_only",
                extra={"wj_extra": {"reason": exc_reason(exc), "query": query}},
            )
            return []

        evidence: list[WebEvidence] = []
        for hit in hits[: self.max_documents]:
            try:
                ev = await self._research_one(hit)
                if ev is not None:
                    evidence.append(ev)
            except Exception as exc:
                # 单文档失败不影响其余；全部失败时最终可整体降级为空
                logger.warning(
                    "rag_document_fetch_failed_skipped",
                    extra={
                        "wj_extra": {
                            "reason": exc_reason(exc),
                            "url": getattr(hit, "url", ""),
                        }
                    },
                )
                continue
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
