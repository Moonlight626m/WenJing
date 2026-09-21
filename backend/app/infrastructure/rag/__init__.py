"""安全开放网络 RAG（issue #10）。

search → fetch → extract 三 adapter，带 SSRF/DNS 防护、重定向复检、
响应限制与清洗、来源记录与失败降级：

- `providers`：SearchProvider / PageFetcher / DocumentExtractor 契约 + NullSearchProvider
- `ddgs_search`：DuckDuckGoSearchProvider（真实网络搜索 adapter，免费无 key，
  `WENJING_RAG_SEARCH_PROVIDER=ddgs` 启用）
- `network`：URL/HTTP scheme 白名单 + DNS 解析后 IP 封禁（loopback/private/link-local/metadata）
- `safe_fetcher`：SafePageFetcher（httpx，超时/大小/并发/content-type 白名单/重定向复检）
- `html_extractor`：HtmlDocumentExtractor（去脚本/样式/隐藏内容，网页文本标记为不可信）
- `service`：RagService 门面，失败降级为纯原文（返回空证据集）

约束：契约（providers）不得导入 httpx；实现模块可导入 httpx。
"""
