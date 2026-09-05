# ADR-0001 开放网络 RAG：搜索 provider 选型与降级策略

- 状态：已接受
- 日期：2026-09-05
- 关联 issue：#10 安全开放网络 RAG

## 背景

剧本生成（#11）需要「开放网络资料补充」，但网络内容不可信、可能含 prompt
injection，且 SSRF 是开放抓取的头号安全风险。需要为 search / fetch / extract
三 adapter 确定实现选型与失败时的降级策略。

## 决策

### 1. 三 adapter 契约分离

`SearchProvider` / `PageFetcher` / `DocumentExtractor` 以 Protocol 契约定义
（`app/rag/providers.py`），实现可替换。契约模块零基础设施依赖（不 import httpx）。

### 2. 首个搜索实现：NullSearchProvider（显式空结果）

MVP 不绑定任何真实搜索 API（避免引入第三方 key 与配额）。首个 `SearchProvider`
实现为 `NullSearchProvider`，恒定返回空结果 → 触发降级为纯原文。

候选真实 provider（后续 #12 接入时评估）：
- DuckDuckGo Lite（无需 key，HTML 结果，无官方 API）
- Bing Web Search API（有 key，结构化结果，配额清晰）
- Tavily（面向 RAG 的结构化结果，有 key）

选型原则：优先「官方 API + 结构化结果 + 明确配额」，其次「无 key 的 HTML 端点
+ 严格解析」。无论选谁，都必须经 `SafePageFetcher` 的 SSRF/DNS 边界。

### 3. 抓取安全边界（SafePageFetcher）

- 仅 http/https；请求前 DNS 解析并拒绝 loopback/private/link-local/metadata 网段；
  每次重定向跳转前重新完整校验。
- 连接/读取超时、响应体大小上限（5MB）、并发信号量（4）、content-type 白名单
  （text/html / xhtml+xml / text/plain）。
- 已知残余风险：DNS 校验与 httpx 实际连接之间存在理论上的 TOCTOU 窗口
  （DNS rebinding）。MVP 以「每次跳转复检 + 拒绝私有网段」缓解；后续如接入真实
  搜索，可改为自建 pin-to-IP transport 彻底关闭该窗口。

### 4. 不可信标记与指令隔离

网页文本永远标记 `untrusted=True`；进入 LLM prompt 时以
`<<<UNTRUSTED_WEB_BEGIN>>>/<<<UNTRUSTED_WEB_END>>>` 显式隔离（`mark_untrusted`）。
生成侧（#11）把网络内容作为「补充资料」而非「事实/指令」，Stage2 关键 beat 的
事实依据仍以原文 EvidenceRef 为准。

### 5. 降级策略：失败即退化为纯原文

任何一步失败（搜索不可用 / 目标被封禁 / 超时 / 超限 / 非白名单类型）都只影响
该文档；整体失败返回空证据集，生成链路退化为纯原文（`CONTENT_INSUFFICIENT_SOURCE`
之上仍可产出合法剧本）。网络资料是增强而非必要输入。

## 后果

- 正向：开放抓取有明确安全边界；不引入第三方搜索依赖即可交付 MVP；降级保证
  生成链路永远有确定性兜底。
- 负向：MVP 无真实网络增强（搜索结果恒为空）；DNS rebinding 有理论残余风险；
  网页解析为正则级（非 DOM 级），对复杂页面提取质量有限。
