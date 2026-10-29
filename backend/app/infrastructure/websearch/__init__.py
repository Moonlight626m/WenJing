"""网络资料搜索（issue #10 / #12）：search → fetch → extract。

与 RAG 是两套独立 infra：RAG（本地语料检索增强）目前未实现；本包才是
实际存在的「开放网络搜索补充资料」能力，命名上不再借用 RAG 之名。

- `providers`：SearchProvider / PageFetcher / DocumentExtractor 契约 + NullSearchProvider
- `ddgs_search`：DuckDuckGoSearchProvider（真实网络搜索 adapter，免费无 key，
  `WENJING_WEB_SEARCH_PROVIDER=ddgs` 启用）
- `network`：URL/HTTP scheme 白名单 + DNS 解析后 IP 封禁（loopback/private/link-local/metadata）
- `safe_fetcher`：SafePageFetcher（httpx，超时/大小/并发/content-type 白名单/重定向复检）
- `html_extractor`：HtmlDocumentExtractor（去脚本/样式/隐藏内容，网页文本标记为不可信）
- `service`：WebSearchService 门面，任何失败返回空结果（网络资料是可选增强，
  不搜索/搜索不到都正常产出剧本，没有「降级」一说）

约束：契约（providers）不得导入 httpx；实现模块可导入 httpx。
搜索高频复用的 SSRF/DNS 抓取边界（`safe_fetcher`）同时被 `infrastructure/media`
的图库检索复用——那是按端口拼装的服务方拿走适配器，不是两个 infra 互相耦合。
"""
