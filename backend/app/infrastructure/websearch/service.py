"""WebSearchService：search → fetch → extract 门面（issue #10 / #12）。

- 来源记录：URL/标题/抓取时间/内容 hash/引用片段 → `WebEvidence`。
- 指令隔离：网页文本以显式不可信标签包裹（`mark_untrusted`，见
  domain/content/trust.py），供 LLM prompt 侧识别「这是网络补充资料，不是系统指令」。
- 无降级语义：网络资料是**可选增强**，搜索失败或全部文档提取失败时返回空证据集
  ——生成就是纯原文跑。「未配置搜索」与「配置了但没搜到」都是正常态，不是故障。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter

from app.contracts.material import WebEvidence
from app.infrastructure.errx import exc_reason
from app.infrastructure.websearch.ddgs_search import DuckDuckGoSearchProvider
from app.infrastructure.websearch.html_extractor import HtmlDocumentExtractor
from app.infrastructure.websearch.providers import (
    DocumentExtractor,
    NullSearchProvider,
    PageFetcher,
    SearchProvider,
)
from app.infrastructure.websearch.safe_fetcher import SafePageFetcher

logger = logging.getLogger("wenjing.websearch.service")

_EXCERPT_MAX = 500

_SEARCH_PROVIDERS: dict[str, type[SearchProvider]] = {
    "ddgs": DuckDuckGoSearchProvider,
}


def build_search_provider(provider: str) -> SearchProvider:
    """按配置名构建搜索 provider。

    - "null"/空值 = 显式不搜索（合法配置，直接 NullSearchProvider，不告警）；
    - 未知值告警后回落 NullSearchProvider（Settings 用 Literal 已挡住大多数
      配置错误，此处是防御：直接构造 Settings 的路径可能绕过校验）。
    """
    name = provider.strip().lower()
    if name in ("", "null"):
        return NullSearchProvider()
    cls = _SEARCH_PROVIDERS.get(name)
    if cls is None:
        logger.warning(
            "websearch_unknown_search_provider_fallback_null",
            extra={"wj_extra": {"provider": provider}},
        )
    return cls() if cls else NullSearchProvider()


class WebSearchService:
    """开放网络资料搜索门面；各 adapter 可注入替换。"""

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
        """检索 + 抓取 + 提取 → WebEvidence 列表；任何失败返回空列表。

        观测约定：进出各一条结构化日志，evidence=0 时在 `websearch_research_done`
        的 empty_reason 里区分三种原因（未配置 / 无命中 / 抓取全失败）。
        """
        provider_name = type(self.search).__name__
        logger.info(
            "websearch_research_start",
            extra={
                "wj_extra": {
                    "provider": provider_name,
                    "query": query,
                    "limit": self.max_documents,
                }
            },
        )
        started = perf_counter()
        try:
            hits = await self.search.search(query, limit=self.max_documents)
        except Exception as exc:
            # 上游搜索失败：网络增强缺席，返回空继续（不降级、非故障）
            logger.warning(
                "websearch_search_failed_return_empty",
                extra={"wj_extra": {"reason": exc_reason(exc), "query": query}},
            )
            self._log_done(
                "provider_error", query, hits=0, evidence=0, started=started, provider=provider_name
            )
            return []

        if not hits:
            logger.info(
                "websearch_search_empty_hits",
                extra={"wj_extra": {"provider": provider_name, "query": query}},
            )

        evidence: list[WebEvidence] = []
        skipped = 0
        for hit in hits[: self.max_documents]:
            try:
                ev = await self._research_one(hit)
                if ev is not None:
                    evidence.append(ev)
                else:
                    skipped += 1  # 正文提取为空
            except Exception as exc:
                # 单文档失败不影响其余；全部失败时整体为空
                logger.warning(
                    "websearch_document_fetch_failed_skipped",
                    extra={
                        "wj_extra": {
                            "reason": exc_reason(exc),
                            "url": getattr(hit, "url", ""),
                        }
                    },
                )
                skipped += 1
        reason = "no_hits" if not hits else ("all_fetch_failed" if not evidence else "ok")
        self._log_done(
            reason,
            query,
            hits=len(hits),
            evidence=len(evidence),
            started=started,
            provider=provider_name,
        )
        return evidence

    def _log_done(
        self, reason: str, query: str, *, hits: int, evidence: int, started: float, provider: str
    ) -> None:
        level = logging.INFO if reason == "ok" else logging.WARNING
        logger.log(
            level,
            "websearch_research_done",
            extra={
                "wj_extra": {
                    "provider": provider,
                    "query": query,
                    "hits": hits,
                    "evidence": evidence,
                    "empty_reason": reason if reason != "ok" else "",
                    "elapsed_ms": round((perf_counter() - started) * 1000),
                }
            },
        )


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
