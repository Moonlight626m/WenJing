# 多 Agent + 世界环境下的游戏记忆系统：并发场景方案调研

> 调研日期：2026-11-09
> 调研方式：**一手来源**（arXiv 摘要页、项目官方 README / 文档）。原计划用 Exa MCP 的
> `web_search_exa` 做广搜，但该 team 额度已耗尽（所有 exa 工具返回
> `402 You have exceeded your credits limit`），故改为直接抓取已知的一手页面；
> 每一条结论都标注来源，未读到原文的只作方向性描述。
> **结论可能过期、非规格**：这是调研快照，不构成本项目架构决策；若要采纳，先写 ADR / Issue。

## 0. 结论（先看这段）

针对「多 agent 团队实例 + 世界 env、后端并发、游戏记忆系统」，本轮的判断是：

1. **「向量库」和「文件系统」都不是并发场景下的记忆权威，只是派生的检索/草稿层。**
   Claude Code / Codex 这类 coding harness 的记忆本质是「工作目录里的文件 + 提示词里塞
   CLAUDE.md/AGENTS.md」，它假设**单 agent、单写者、以仓库为边界**；一旦变成多 agent 共享
   世界、多请求并发，文件与向量索引都缺少事务、版本、可见性和冲突语义。
2. **真正可作为权威的是「只追加的事件日志 + 可重建的派生投影」**（事件溯源）。
   这正好是 WenJing 现有的形态（`EventStore.active_events()` / `branch_path()`、
   `session_store` 的行锁 + CAS）。**不要为了「上记忆系统」把权威从事件流挪走。**
3. **值得借鉴的成熟模式有四类**，按与本项目的相关度排序：
   - **时序知识图谱（bi-temporal KG）**：Zep/Graphiti、Cognee——解决「事实随时间变化、要能
     按 as-of 时间查询、冲突不删除只失效」，适合做**派生语义索引**，不适合当唯一权威。
   - **分层 / 分页内存（OS 隐喻）**：MemGPT/Letta、MemoryOS——把「上下文窗口」当 RAM，把
     长期记忆当磁盘，靠换入换出和后台固化控制成本。与 WenJing 现有的「有界读取窗口」同源。
   - **Agentic 自组织笔记**：A-MEM（Zettelkasten 动态索引/链接/记忆演化）、Mem0（抽取-合并-
     检索）、LangMem（热路径工具 + 后台整理）——强调「写入时整理」而不是「查询时硬检索」。
   - **单写者 / 事务型后端**：Actor 模型、按 session 分片、Convex 式的 OCC/MVCC、Postgres
     行锁——这是**并发正确性**的答案，和「记忆用什么存储」是正交的两件事。
4. **对本项目（WenJing）的具体建议：短期不引入外部记忆服务。**
   - 继续用事件流做权威，角色记忆（`CharacterMemory`）保持「有界读取窗口 + 可重建」；
   - `plot_entries_for(viewer)` 这种「共享事件、按可见性投影」已经是多 agent 记忆的正确姿势，
     应推广而不是换成全局广播；
   - 若将来确实需要语义召回，再加一个**可丢弃、可重建**的派生索引（PG 表 / pgvector / 图表），
     由事件流喂数据，绝不反过来从索引推导游戏状态；
   - 并发继续坚持「单 worker + 每 session 串行 + 行锁/CAS」；要扩多副本，先做 **session 粘性
     路由**或 **数据库级互斥**，不要直接多 worker 共享内存状态。

**明确不建议抄的**：
- 把 vector DB 当 source of truth（无法表达「撤回/回溯/可见性/时间有效性」）；
- 每个 agent 一个独立数据库/知识图谱来存「共享世界」——共享世界必须单一权威；
- 在命令热路径里同步跑 LLM 记忆抽取/建图（会把命令延迟和成本放大一个量级）；
- 直接引入 Neo4j/FalkorDB 只为 2–6 个角色的记忆（运维成本远超收益）。

---

## 1. 问题到底难在哪：把「状态」「记忆」「检索」拆开

并发场景下的「游戏记忆系统」经常被混为一谈，其实是四个不同的问题：

| 概念 | 回答的问题 | 权威性要求 | 典型载体 |
|---|---|---|---|
| **世界状态（world state）** | 现在世界是什么样（时间、地点、角色位置、目标） | 强一致、可回溯 | 事件流 / 事务数据库 |
| **角色记忆（agent memory）** | 这个角色「知道」什么、记得什么 | 每个角色视角不同、可重建 | 事件投影 / 有界窗口 |
| **派生检索索引（recall index）** | 给一段 cue，快速捞出相关历史 | 可最终一致、可重建 | 向量库 / KG / 倒排 |
| **运行期上下文（working context）** | 这一轮 prompt 里放什么 | 有界、可裁剪 | 内存 / 提示词拼装 |

关键判断：**只有前两者需要「权威」，后两者天然是派生/易失的。**
Zep/Graphiti 把「episode（原始输入）」明确标为 ground truth，所有派生事实都能追溯回
episode（Graphiti README）；Redis Agent Memory 也是「session 记忆（带 TTL）+ 长期事实（后台
抽取）」两层。这与「事件是权威、快照只是缓存」是同一个思想。

并发下真正会出问题的是：
- 多个 agent 同时写同一份记忆 → 丢更新 / 覆盖；
- 共享世界与私有记忆混在一个可变 blob 里 → 回溯时无法只回退一方；
- 派生索引与权威不同步 → 角色「记错」且无法解释；
- 可见性没在读取口统一收口 → 私有信息泄漏给其他 agent / 玩家。

---

## 2. 基线方案为什么在并发下不够

### 2.1 向量数据库
- 优点：语义召回自然、接入简单、生态成熟（pgvector、Qdrant、Milvus 等）。
- 并发短板：
  - **不擅长表达「撤回/失效/时间有效性」**。一条记忆被回溯或剧情否定后，向量里仍可能被召回；
    只能靠删除/覆盖，无法回答「当时它是否成立」。
  - **不是状态权威**。向量只存「文本块 + embedding」，没有实体关系、没有可见性、没有版本。
  - **写入与索引更新有延迟**，且删除/更新往往是「软删 + 过滤」，多 agent 并发时容易读到旧值。
- 结论：适合做**派生 recall 层**，不适合做世界/角色记忆的权威。

### 2.2 文件系统（coding harness 方案）
Claude Code 的 `CLAUDE.md`、Codex 的 `AGENTS.md` 本质是：
- 以**工作目录**为作用域；
- **单 agent、单写者**，靠「读文件 → 改文件 → 下一轮再读」维持连续性；
- 没有事务、没有多写者冲突解决、没有按读者过滤的可见性；
- 上下文靠「把关键文件塞进 prompt」实现，规模一大就退化为检索问题。

它适合「一个 agent 维护一个代码库的长期约定」，不适合「多个 agent 共享一个并发世界」。
一旦多实例并发，文件要么加锁（退化成串行），要么接受 last-write-wins（记忆互相覆盖）。

### 2.3 结论
并发游戏记忆需要的是**「权威存储 + 派生索引 + 读时投影」**三件套，而不是「换一个更花哨的
数据库」。下面按这个框架盘点项目。

---

## 3. 现有项目与方案盘点

### A. 事件溯源 / 只追加日志（权威层）

代表：WenJing 现有实现；通用工程里的 Kafka/outbox、Temporal/DBOS 类 durable execution、
LangGraph 的 checkpointer/store。

要点：
- 事件是唯一权威，状态 = 对事件的折叠；回溯 = 换一条分支重放；
- 快照是缓存，删了只增加重放量、不改变结果；
- 并发写靠**单写者**（每 session 串行）或**乐观并发**（version/CAS）。

LangGraph 的记忆分层也可作参考：**短期记忆 = thread 内的 checkpoint（会话状态）**，
**长期记忆 = 跨 thread 的 store（按 namespace 组织，可配向量索引）**；生产用
`AsyncPostgresStore` 而非 `InMemoryStore`（LangMem README 明确说明）。
这印证了「权威在 DB/日志，向量只是 store 的可选索引」。

> 与 WenJing 的关系：**已经是这条路**。`session_store.restore` 用 `with_for_update` 锁会话行、
> `commit` 用 version 做 CAS；`CharacterMemory.trim()` 把记忆收口成有界窗口，注释里写明
> 「事件流才是全量权威」。这是本调研认为**最正确的基线**，不需要替换。

### B. 时序知识图谱（bi-temporal KG）

代表：**Zep / Graphiti**、**Cognee**、Microsoft **GraphRAG**、Mem0 的 graph 变体。

Zep/Graphiti（arXiv:2501.13956；Graphiti README）：
- 核心是「实体 + 带**有效期窗口**的事实边 + episode 溯源」；信息变化时**旧事实失效而不删除**，
  可查询「现在为真」或「某时刻为真」；
- 混合检索：语义 + 关键词（BM25）+ 图遍历；增量构图，不需要整图重算；
- 官方对比 GraphRAG：GraphRAG 偏静态文档批处理与社区摘要，Graphiti 偏动态、增量、亚秒级；
- 后端：Neo4j / FalkorDB / Amazon Neptune；**Kuzu 已弃用**（上游不再维护）；
- 并发注意：ingestion 默认 `SEMAPHORE_LIMIT=10` 限制并发以避 LLM 429；
  **参考实现 REST/MCP server 明确「无认证、无授权、无租户隔离」**，生产必须自己加鉴权与租户隔离；
- 论文指标：DMR 94.8% vs MemGPT 93.4%；LongMemEval 上最高 +18.5% 准确率、延迟降 90%。

Cognee（README；arXiv:2505.24478）：
- `remember / recall / improve / forget` 四操作；文本/代码/会话进图 + 向量；
- 强调「session 蒸馏」：会话里的经验经审核后进永久图；
- 支持单 Postgres 跑「关系 + PGVector + 图」的 demo（生产版为授权产品）；
- 多租户：API 默认 multi-tenant，需鉴权。

适用判断：
- **适合**：事实会随时间变化、需要「谁在何时知道什么」、需要解释链（provenance）。
- **不适合**：当作世界状态唯一权威（图数据库的事务/回溯语义不如事件流直观）；2–6 个角色
  的场景引入图数据库是过度设计。
- **可借鉴**：即使不上图数据库，也可以借用「事实带 validity window + 失效不删除」的数据建模，
  用普通表实现。

### C. 分层 / 分页内存（OS 隐喻）

代表：**MemGPT / Letta**（arXiv:2310.08560）、**MemoryOS**（arXiv:2506.06326）。

MemGPT：
- 把上下文窗口当「RAM」，把外部存储当「磁盘」，通过**虚拟上下文管理**在层间搬数据；
- 用**中断（interrupts）**在 agent 与用户间切换控制流；
- 关键思想：**内存管理是 agent 的显式动作**，而不是被动截断。

MemoryOS：
- 三级存储：**短期 / 中期 / 长期个人记忆**；
- 短期→中期按「对话链 FIFO」更新，中期→长期用「分段页」组织；
- LoCoMo 上相对基线 F1 +49.11%、BLEU-1 +46.18%（GPT-4o-mini）。

适用判断：
- 与 WenJing 的「有界读取窗口 + 快照」高度同构；真正可借鉴的是**分层更新策略**（何时固化、
  何时丢弃），而不是照搬「让 LLM 自己调内存工具」。
- 风险：让 agent 自主管理内存会增加不确定性和 token 成本；游戏叙事更需要**确定性回放**。

### D. Agentic 自组织笔记

代表：**A-MEM**（arXiv:2502.12110，NeurIPS 2025）、**Mem0**（arXiv:2504.19413）、
**LangMem**。

A-MEM：
- 借 Zettelkasten：每条记忆生成含上下文/关键词/标签的结构化笔记；
- 新记忆到来时**主动找关联并建链**，还会**反向更新旧记忆**（memory evolution）；
- 优点：自适应、可解释的网络结构；缺点：写入成本高、更新会改历史（对游戏回放不友好）。

Mem0：
- 从对话中**抽取 → 合并 → 检索**显著信息；可选 graph memory；
- LOCOMO 上：LLM-as-Judge 相对 OpenAI 记忆 +26%，graph 版再高约 2%；
  p95 延迟降 91%、token 成本省 90%+；
- 定位是「生产可用的长期记忆层」，偏对话助手，不是并发世界模拟。

LangMem：
- 提供「任意存储都能用」的函数式原语；
- **热路径工具**（agent 在对话中主动存取）+ **后台记忆管理器**（自动抽取/合并/更新）；
- 原生接 LangGraph 的 `BaseStore`，生产用 `AsyncPostgresStore`。

适用判断：
- 「热路径」与「后台」分离是重要工程经验：**不要让记忆整理阻塞玩家命令**。
- 「新记忆反向改写旧记忆」要慎用：游戏有回溯/分支，改写历史会破坏可回放性。

### E. 统一事务型后端 / OCC-MVCC

代表：**Convex + AI Town**（a16z-infra/ai-town README）、Postgres 原生。

AI Town：
- 明确目标之一是「后端原生支持**共享全局状态、事务、模拟引擎**，可扩展到多人游戏」；
- 用 Convex：`query`/`mutation` 具备**可串行化隔离**，并通过
  **乐观多版本并发控制（OCC/MVCC）** 自动解决冲突；`action` 负责外部 API 副作用；
- 记忆检索也在同一后端（含 vector search），减少「状态库 / 向量库」双写不一致。

适用判断：
- 这是「用一个事务型后端同时承担状态 + 记忆 + 检索引擎」的思路，和 WenJing 用 Postgres 做
  权威一致；差别只是 Convex 把反应式查询/调度也包了。
- 对 WenJing 的启示：**能用一个 PG 解决就别开第二个存储**；派生索引也尽量留在 PG。

### F. Actor 模型 / 单写者

代表：Erlang/Akka、Microsoft Orleans、Dapr Actors（通用工程模式，本轮未逐页核验厂商细节）。

要点：
- 每个 agent（或每个 session）是一个 actor，**消息串行处理**，状态只在 actor 内可变；
- 跨 actor 共享状态通过消息/事件，而不是共享可变内存；
- 天然匹配「每 session 串行命令」；水平扩展靠 **actor 放置/粘性路由**。

与 WenJing 的关系：
- 现有「单 worker + 每 session 行锁 + 命令串行」等价于「进程内的 per-session actor」。
- 若将来多副本：把 `session_id` 做**一致性哈希/粘性路由**，或把锁从进程内升级为
  **PG advisory lock / 行锁**，即可保持同样的串行语义。**不要**让两个副本同时持有一个
  session 的运行时对象。

### G. CRDT / local-first

代表：**Automerge**（README）、Yjs、ElectricSQL 等。

要点：
- CRDT 让多个副本**无需协调即可合并**，Automerge 提供紧凑二进制格式与同步协议，
  目标是让 local-first 应用像关系库支持服务端那样简单；Automerge 3 约 10× 内存下降。
- 适合：**弱一致、可交换的共享编辑**（文档、白板、玩家协作编辑世界）。
- 不适合：**强叙事因果**（谁先说话、谁的目标先达成）和**权威回溯**——CRDT 的合并语义
  不保证「故事线只有一个版本」。

适用判断：
- 除非要做「多玩家实时共同编辑同一个世界」，否则不建议引入。游戏叙事更需要**单线权威 +
  显式分支**，而不是自动合并。

### H. 生成式社会仿真框架

代表：**Generative Agents**（arXiv:2304.03442）、**Concordia**、**AgentSociety**（本仓库
已有专门调研）、**Project Sid**（arXiv:2411.00114）、**AI Town**。

Generative Agents：
- **memory stream**：用自然语言记录全部经历；
- **reflection**：把记忆综合成更高层反思；
- **retrieval**：按 recency/importance/relevance 动态召回以规划行为；
- 25 个 agent 的小镇涌现出传播邀请、约会、协调赴约等行为；消融显示 observation/planning/
  reflection 都关键。
- 这是「记忆流 + 反思 + 检索」的经典范式，但它是**单机仿真**，不解决多租户并发。

Concordia（DeepMind）：
- 用**桌面角色扮演**的交互模式：一个 **Game Master** 实体模拟环境，玩家实体用自然语言
  描述意图，GM 翻译成结果；
- 实体由**组件**组成（指令、记忆、动作选择），引擎决定轮转/同时/异步行动；
- 记忆是组件之一，可替换。
- 启示：「世界环境」应是一个**可替换的裁决者**，agent 的记忆与世界的裁决解耦。

Project Sid（Altera）：
- **PIANO**（Parallel Information Aggregation via Neural Orchestration）架构，支持
  10–1000+ agent 在 Minecraft 中实时交互，同时维持多个输出流的一致性；
- 关注的是「大规模多 agent 的并行信息聚合与编排」。

AgentSociety（见 `docs/research/agentsociety-architecture-study.md`）：
- tick 驱动的社科仿真，Ray + 每 tick 重建；与本项目「命令驱动、2–6 角色、单 worker」假设相反，
  该调研已明确「不建议整体参考」。

适用判断：
- 这些框架解决的是「**仿真**」而非「**后端服务**」；可借鉴记忆模型（memory stream/reflection）
  与裁决者模式，但不要照搬它们的调度/重建机制。

### I. 托管记忆服务

代表：**Zep Cloud**、**Redis Agent Memory**（Redis Iris）、Supermemory / Memobase 等
（后两者本轮未核验）。

Redis Agent Memory（README）：
- **两层**：session memory（活跃会话状态，可配 TTL）+ long-term memory（抽取事实 + 向量）；
- 新事件进 session 后，**后台**抽取并提升到长期记忆，不拖慢在线 agent loop；
- 前身 V0 开源（本仓库即 `redis/agent-memory-server`），现在作为研究工件保留；
- 提供 LongMemEval 基准 harness，并强调「分数取决于版本/模型/检索配置，不是永恒排名」。

适用判断：
- 「session 热层 + 长期冷层 + 后台提升」是并发服务里最实用的成本结构。
- 但把记忆外包给第三方服务，会把**世界状态/可见性/回溯**这些游戏核心语义交给外部，
  通常不划算；可作为「纯对话型 agent」的选项。

---

## 4. 并发场景的关键设计点（跨方案）

| 并发风险 | 症状 | 推荐机制 | 代表实现 |
|---|---|---|---|
| 丢更新 / 覆盖 | 两个 agent 同时写记忆，后者覆盖前者 | 单写者（per-session 串行）或 OCC/CAS（version） | WenJing `session_store` 行锁 + version；Convex OCC |
| 共享 vs 私有混淆 | 回溯时无法只回退一方 | 共享世界与私有记忆**分开存**，都从同一事件流派生 | WenJing `RuntimeAssets.rebuild` + `CharacterMemory` |
| 派生索引不一致 | 角色「记错」、无法解释 | 索引可丢弃可重建；以 episode/事件为溯源 | Graphiti episodes；WenJing 快照缓存 |
| 可见性泄漏 | 私有信息进其他 agent prompt | **读取口统一收口**，按 viewer 投影 | WenJing `plot_entries_for(viewer)` |
| 时间/因果错乱 | 问到「当时是否成立」答错 | bi-temporal（valid/transaction time） | Zep/Graphiti |
| 写入成本爆炸 | 每次命令都建图/抽取，延迟飙升 | 热路径只追加；整理放后台 | Redis Agent Memory；LangMem background |
| 多租户串数据 | A 会话读到 B 会话记忆 | namespace/group_id + 鉴权 | Graphiti group_id（但参考 server 无鉴权）；Cognee 多租户 |
| 多副本状态分裂 | 两个 worker 各持一份运行时 | session 粘性路由 / DB 级互斥 / 单 worker | Actor 放置；WenJing 单 worker 约束 |
| 记忆投毒 / 注入 | 恶意内容长期留在记忆里 | 写入校验、来源标记、可删除、最小化 | Cognee `forget`；Graphiti provenance |

两条容易被忽视的不变量：
1. **「谁在说」与「谁可见」必须进入记忆模型**，而不是事后在 prompt 里过滤。WenJing 的
   `plot_entries_for(viewer)` 把「角色可见叙事摘要」做成唯一读取口，是正确方向。
2. **记忆的写入必须可被回溯撤销**。事件溯源天然满足；可变记忆 + 向量软删很难满足。

---

## 5. 方案对比矩阵

| 方案 | 并发正确性 | 时间/因果表达 | 语义召回 | 运维成本 | 可回溯 | 适合当权威 |
|---|---|---|---|---|---|---|
| 事件溯源 + 派生投影 | 高（单写者/CAS） | 高（事件序） | 需另加索引 | 低（PG 即可） | **强** | **是** |
| 时序知识图谱（Graphiti） | 中（需自己加锁/租户） | **高（bi-temporal）** | 高（混合检索） | 高（图库） | 中 | 否（宜作派生） |
| 分层内存（MemGPT/MemoryOS） | 中 | 中 | 中 | 中 | 弱 | 否（是运行期策略） |
| Agentic 笔记（A-MEM/Mem0） | 中 | 低-中 | 高 | 中 | 弱（会改写旧记忆） | 否 |
| 统一事务后端（Convex） | **高（OCC/MVCC）** | 中 | 内置 | 低-中 | 中 | 是 |
| Actor / 单写者 | **高** | 高（消息序） | 需另加 | 中 | 中 | 是 |
| CRDT / local-first | 高（最终一致） | 低 | 否 | 中 | 弱（合并） | 否（多写者场景例外） |
| 托管记忆服务 | 由服务商决定 | 中 | 高 | 低（外包） | 弱 | 否（游戏核心语义不适合外包） |

读法：**「并发正确性」和「记忆检索能力」是两条轴**。事件溯源在正确性/可回溯上最优，召回需要
外挂；知识图谱在时间表达与召回上最优，但正确性要自己补。两者是互补而非替代。

---

## 6. 对 WenJing 的落地建议

### 6.1 保持不变（现状是对的）
- **事件是权威**：世界状态、目标、资产、角色记忆都从 `active_events()` / `branch_path()` 派生；
  `RuntimeAssets.rebuild(store)` 不落库，快照只是缓存。
- **每 session 串行 + 行锁 + CAS**：`session_store.restore` 的 `with_for_update` 与 `commit`
  的 version 检查，等价于 per-session actor；单 worker 是当前正确性的一部分。
- **有界读取窗口**：`CharacterMemory.trim()` 把记忆收口到最近 N 条，避免快照 O(n²) 膨胀。
- **按 viewer 投影**：`plot_entries_for(viewer)` 是多 agent「共享但可分权」记忆的正确抽象。

### 6.2 若确实需要更强的「记忆能力」，按优先级分阶段
1. **先做事件流上的派生投影**（零新基础设施）：
   - 在 PG 里建「角色 × 事实」表，字段含 `valid_from/valid_to/source_event_id/viewer`；
   - 由事件流异步重建；查询走「当前有效 + 该 viewer 可见」；
   - 这就是「不引入图数据库的 bi-temporal」。
2. **再加语义召回**（可选）：
   - 用 pgvector 存 episode/事实的 embedding，作为 `recall` 的候选集；
   - **索引可丢弃**：重建脚本从事件流重算，验证「删索引不影响状态」。
3. **最后才考虑图数据库**（仅当出现「多跳关系/时间推理」真实需求）：
   - Graphiti 可复用其 bi-temporal 模型，但需自建鉴权、租户、以及和事件流的同步；
   - 不要把 Neo4j/FalkorDB 放进命令热路径；用 outbox + 后台 worker。
4. **记忆整理放后台**：
   - 吸收 Mem0/LangMem/Redis 的「热路径只写、后台抽取合并」；
   - 参照 AgentSociety 调研里「token 缓存命中率」的教训，记录记忆整理的成本。

### 6.3 若要水平扩展（多副本）
- 第一选择：**session 粘性路由**（同一 session 永远落同一 worker），保持进程内串行；
- 第二选择：把互斥下沉到 PG（行锁 / advisory lock），运行时对象按需加载；
- 同时把 WS outbox / 在途生成改成可跨进程（DB 表或消息队列），否则单 worker 约束仍成立。
- **不要**让两个副本共享「同一份可变世界状态」。

### 6.4 反模式清单
- ❌ 用向量库存世界状态或角色私有记忆的权威副本；
- ❌ 让多个 agent 各写一个独立的「共享世界」；
- ❌ 在命令请求内同步做 LLM 抽取/建图；
- ❌ 让记忆 summarization 反向改写历史事件；
- ❌ 把写-only 的全局广播（如 `plot_context`）直接暴露给所有 agent；
- ❌ 为 2–6 个角色上 Neo4j/FalkorDB（运维成本 >> 收益）。

---

## 7. 评测基准（供将来验证）

- **LoCoMo**（arXiv:2402.17753）：超长期对话（约 300 轮 / 35 会话）上的问答、事件摘要、
  多模态生成；长上下文与 RAG 仍显著落后人类。
- **LongMemEval**（arXiv:2410.10813，ICLR 2025）：五项长期记忆能力——信息抽取、跨会话推理、
  时间推理、知识更新、拒答；把设计拆成 **indexing / retrieval / reading** 三阶段，并提出
  会话分解、事实增强 key、时间感知 query 等优化。
- **DMR**：MemGPT 团队提出的 Deep Memory Retrieval，Zep 用它做过对比；注意它比
  LongMemEval 简单，厂商分数不可直接横比。
- 提醒：Redis README 明确说「分数取决于版本/模型/检索配置/数据划分，不是永恒排名」。
  游戏记忆更应自建**可回放的行为级**评测（同一事件流 → 同一可见叙事），而不是只看召回率。

---

## 8. 参考来源（本轮实际抓取）

- Zep 论文：<https://arxiv.org/abs/2501.13956>
- Graphiti README：<https://github.com/getzep/graphiti>
- Mem0 论文：<https://arxiv.org/abs/2504.19413>
- MemGPT 论文：<https://arxiv.org/abs/2310.08560>
- A-MEM 论文：<https://arxiv.org/abs/2502.12110>
- MemoryOS 论文：<https://arxiv.org/abs/2506.06326>
- Generative Agents 论文：<https://arxiv.org/abs/2304.03442>
- Agent 记忆综述：<https://arxiv.org/abs/2404.13501>
- Cognee README：<https://github.com/topoteretes/cognee>；
  Cognee 论文：<https://arxiv.org/abs/2505.24478>
- Redis Agent Memory README：<https://github.com/redis/agent-memory-server>
- LangMem README：<https://github.com/langchain-ai/langmem>
- Letta（原 MemGPT）：<https://github.com/letta-ai/letta>
- AI Town README：<https://github.com/a16z-infra/ai-town>
- Concordia README：<https://github.com/google-deepmind/concordia>
- Project Sid 论文：<https://arxiv.org/abs/2411.00114>
- Automerge README：<https://github.com/automerge/automerge>
- LoCoMo 论文：<https://arxiv.org/abs/2402.17753>
- LongMemEval 论文：<https://arxiv.org/abs/2410.10813>
- 本仓库已有：`docs/research/agentsociety-architecture-study.md`

---

## 9. 调研局限

- Exa MCP 额度耗尽，未能做「关键词广搜 + 结果排序」；因此可能漏掉 2026 年下半年新出的
  记忆项目（尤其国内/闭源产品）。上表是「按方案分类」，不是「穷举清单」。
- 未对任何项目做源码级核验（除本仓库自身）；论文数字均来自摘要页，未复现。
- Actor/Akka/Orleans/Temporal 等只作工程模式描述，未逐页核对当前版本细节。
- 若要推进到 ADR，建议补三项验证：①在 PG 上做「事实表 + 事件重建」原型；
  ②用事件流回放做记忆一致性测试；③评估 pgvector 召回质量是否值得引入。
