# Agent 记忆开源框架调研：可参考的框架清单与选型判断

> 调研日期：2026-11-15
> 调研方式：**一手来源**——GitHub API 元数据（`gh api repos/...`，同日抓取）、各项目 README、
> 官方文档站、arXiv 摘要页；未读到的内容明确标注「未核实」。
> **结论可能过期、非规格**：这是调研快照，不构成本项目架构决策；若要采纳，先写 Issue / ADR。
> 与 `docs/research/agent-memory-architecture-survey.md`（2026-11-09）的关系：那篇按
> 「并发场景下的方案模式」分类（事件溯源 / bi-temporal KG / 分页内存 / actor / CRDT 等 A–I 类），
> 本篇按「**具体框架 / 库 / 项目**」盘点，重点补它的 §3、§5 没有展开的工程细节。
> 模式层面的论述不重复，需要时交叉引用其小节名。

## 0. 结论（先看这段）

1. **Hindsight 已核实**：它是 `vectorize-io/hindsight`（MIT，61,118 stars，2026-11-14 仍有提交），
   既是开源仓库、也有 SaaS（Hindsight Cloud），背后有论文 arXiv:2512.12818。
   记忆模型是「世界事实 / 经验 / 观察 / 心理模型」四类 + `retain / recall / reflect` 三操作，
   以 **bank** 为隔离单位（一个 bank = 一个用户/agent/项目的「大脑」）。它不是同名不同物；
   另有 `lihan0705/hindsight-lite` 等第三方轻量复刻，本调研采信官方仓库。
2. **这一批框架可以分成四层，不要混为一谈**：
   - **权威层**：事件流 / 数据库（WenJing 已有，不需要换）；
   - **派生记忆层**：从对话或事件里抽取事实、图谱、摘要，可重建（本篇大多数框架在这一层）；
   - **运行期窗口**：每轮 prompt 里放什么（Letta 的 core blocks、LlamaIndex 的 token 预算、AG2 的 working.md）；
   - **托管服务**：把上面几层打包成 API（Hindsight Cloud、Supermemory、Zep Cloud、Redis Agent Memory）。
3. **没有一款能直接接进 WenJing**。原因不是它们不好，而是它们的默认假设与本项目相反：
   它们大多假设「记忆是权威、可被 agent 自行改写、按用户全局共享、需要独立服务」；
   WenJing 假设「事件是唯一权威、记忆是可重建的有界窗口、按角色×分支×事件归属、单进程单写者」。
4. **最适合文境的是 LangGraph / LangMem 的结构设计**（不是它的自动抽取）：
   `checkpointer` 当快照缓存、`Store` 用 namespace 编码 `(session, branch, character)`、
   热路径只读、整理放后台。它把「会话状态」与「跨会话长期记忆」分开的姿势，和本项目的
   事件流 / 快照 / 角色记忆三层几乎一一对应。详见 §8.4。
5. **记忆模型最值得抄的是 Hindsight 的「证据 + 预计算页」**：observation 保留原文引用与证据数，
   mental model 把「一个常问问题的答案」预计算成可直接读的页；这正好是 WenJing
   `view_my_memory` 想要的「有界读取窗口」。但 Hindsight 是独立服务、`retain` 走 LLM 抽取，
   只能借模型、不能借部署。
6. **明确不建议抄**：
   - 用户画像式全局记忆（Mem0 / Supermemory / Memobase / Memori 的默认姿势）——与「角色限知」冲突；
   - 让 agent 自行改写记忆（Letta 的 memory tools、A-MEM 的 memory evolution）——破坏可回放；
   - 需要 Neo4j / FalkorDB / Redis / Qdrant 常驻服务的方案（Graphiti、MemOS、Memary、Motorhead）；
   - 在命令热路径里同步跑 LLM 抽取 / 建图（Mem0、Hindsight retain、MIRIX、Cognee）；
   - 把向量库或图数据库当唯一权威。

---

## 1. 核实口径与仓库元数据

下表全部来自 2026-11-15 的 `gh api repos/OWNER/REPO`，stars 为当时快照；`pushed` 是默认分支
最近一次推送时间，用来判断活跃度，不代表发布质量。

| 项目 | 仓库 | Stars | License | 最近推送 | 活跃度判断 |
|---|---|---:|---|---|---|
| Hindsight | `vectorize-io/hindsight` | 61,118 | MIT | 2026-11-14 | 活跃 |
| Graphiti | `getzep/graphiti` | 32,814 | Apache-2.0 | 2026-11-15 | 活跃 |
| Zep（平台/示例） | `getzep/zep` | 5,007 | Apache-2.0 | 2026-11-13 | 活跃 |
| Mem0 | `mem0ai/mem0` | 68,997 | Apache-2.0 | 2026-11-06 | 活跃 |
| Letta（原 MemGPT） | `letta-ai/letta` | 25,445 | Apache-2.0 | 2026-10-18 | 活跃 |
| MemOS | `MemTensor/MemOS` | 12,403 | Apache-2.0 | 2026-11-11 | 活跃 |
| Cognee | `topoteretes/cognee` | 33,323 | Apache-2.0 | 2026-11-14 | 活跃 |
| MIRIX | `Mirix-AI/MIRIX` | 3,464 | Apache-2.0 | 2026-11-11 | 活跃 |
| MemoryOS | `BAI-LAB/MemoryOS` | 1,622 | Apache-2.0 | 2026-07-07 | 维护中 |
| Memobase | `memodb-io/memobase` | 2,958 | Apache-2.0 | 2026-01-11 | 近 10 个月无推送 |
| Supermemory | `supermemoryai/supermemory` | 31,628 | MIT | 2026-11-13 | 活跃 |
| MemU | `NevaMind-AI/memU` | 14,622 | Apache-2.0（`LICENSE.txt`） | 2026-11-14 | 活跃 |
| Memori | `MemoriLabs/Memori`（原 `GibsonAI/memori`） | 17,584 | Apache-2.0（`LICENSE`） | 2026-10-03 | 活跃 |
| Memary | `kingjulio8238/Memary` | 2,663 | MIT | 2024-10-22 | 基本停更 |
| Motorhead | `getmetal/motorhead` | 917 | Apache-2.0 | 2025-07-22 | 基本停更 |
| Redis Agent Memory | `redis/agent-memory-server` | 326 | Apache-2.0（`LICENSE`） | 2026-09-18 | 研究工件 |
| Basic Memory | `basicmachines-co/basic-memory` | 4,578 | AGPL-3.0 | 2026-11-15 | 活跃 |
| mcp-memory-service | `doobidoo/mcp-memory-service` | 2,127 | Apache-2.0 | 2026-11-15 | 活跃 |
| LangGraph | `langchain-ai/langgraph` | 44,981 | MIT | 2026-11-15 | 活跃 |
| LangMem | `langchain-ai/langmem` | 1,769 | MIT | 2026-11-13 | 活跃 |
| LlamaIndex | `run-llama/llama_index` | 52,907 | MIT | 2026-11-14 | 活跃 |
| AutoGen | `microsoft/autogen` | 61,834 | 仓库 LICENSE 为 CC-BY-4.0 | 2026-11-12 | 活跃 |
| AG2 | `ag2ai/ag2` | 5,067 | Apache-2.0 | 2026-11-14 | 活跃 |
| CrewAI | `crewAIInc/crewAI` | 60,926 | MIT | 2026-11-15 | 活跃 |
| OpenAI Agents SDK | `openai/openai-agents-python` | 30,689 | MIT | 2026-11-15 | 活跃 |
| Google ADK | `google/adk-python` | 22,224 | Apache-2.0 | 2026-11-14 | 活跃 |
| Generative Agents | `joonspk-research/generative_agents` | 22,382 | Apache-2.0 | 2024-08-05 | 论文参考实现 |
| Voyager | `MineDojo/Voyager` | 7,325 | MIT | 2024-04-03 | 论文参考实现 |
| Reflexion | `noahshinn/reflexion` | 3,426 | MIT | 2025-01-14 | 论文参考实现 |
| A-MEM | `agiresearch/A-mem` | 1,215 | MIT | 2025-12-12 | 研究实现 |
| HippoRAG | `OSU-NLP-Group/HippoRAG` | 4,123 | MIT | 2026-10-06 | 活跃（研究） |
| GraphRAG | `microsoft/graphrag` | 36,649 | MIT | 2026-11-09 | **维护模式** |
| AgentSociety | `tsinghua-fib-lab/AgentSociety` | 1,402 | Apache-2.0 | 2026-11-13 | 活跃 |
| NovelClaw | `iLearn-Lab/NovelClaw` | 375 | MIT | 2026-10-12 | 活跃（小项目） |
| Quilltale | `Aeesh/Quilltale` | 13 | 无 LICENSE | 2026-09-16 | 个人项目 |
| OpenGameAgent | `EricSun0218/OpenGameAgent` | 61 | MIT | 2026-11-13 | 活跃（小项目） |
| Memorix | `AVIDS2/memorix` | 935 | Apache-2.0 | 2026-11-11 | 活跃 |
| Memoripy | `caspianmoon/memoripy` | 691 | Apache-2.0 | 2026-08-17 | 活跃 |
| CortexDB | `liliang-cn/cortexdb` | 511 | MIT | 2026-11-15 | 活跃 |
| pgvector | `pgvector/pgvector` | 23,681 | PostgreSQL License（GitHub 识别为 NOASSERTION） | 2026-11-14 | 活跃 |
| sqlite-vec | `asg017/sqlite-vec` | 8,264 | Apache-2.0 | 2026-05-18 | 维护中 |
| Chroma | `chroma-core/chroma` | 29,688 | Apache-2.0 | 2026-11-13 | 活跃 |
| Qdrant | `qdrant/qdrant` | 35,563 | Apache-2.0 | 2026-11-14 | 活跃 |

> AutoGen 的仓库 LICENSE 是 CC-BY-4.0，但源文件头常见 MIT 声明；若真要复用代码，需逐文件核对，
> 不要只看仓库 badge。`pgvector` 的 PostgreSQL License 允许自由使用与分发。

---

## 2. 先厘清：这些框架在「记忆栈」里的位置

沿用已有调研 §1 的四分法，把本篇的框架放进去：

| 层 | 回答的问题 | 权威性 | 本篇涉及 |
|---|---|---|---|
| **世界状态** | 现在世界是什么样 | 强一致、可回溯 | WenJing 事件流；Convex/AI Town（已有调研 §3.E） |
| **角色记忆** | 这个角色知道/记得什么 | 按视角、可重建 | Letta blocks、Generative Agents memory stream、Quilltale NPC memory |
| **派生检索索引** | 给 cue 捞相关历史 | 最终一致、可重建 | Graphiti、Hindsight recall、HippoRAG、GraphRAG、pgvector |
| **运行期上下文** | 这轮 prompt 放什么 | 有界、可裁剪 | LlamaIndex token 预算、AG2 working.md、LangGraph checkpointer |

**关键判断**：绝大多数「记忆框架」只解决第三、四层，却默认自己拥有第一、二层的权威。
WenJing 的接入点应该只在第三、四层；第一、二层继续由事件流承担。

---

## 3. 通用记忆层与服务

### 3.1 Hindsight（`vectorize-io/hindsight`）

**定位**：agent memory system，强调「让 agent 学习」而不只是「记住对话」；有 OSS 服务端、
Python/Node/Go 客户端、MCP、60+ 集成，以及托管版 Hindsight Cloud。

**记忆模型**（README「Memory Types」）：

| 类型 | 内容 | 例子 |
|---|---|---|
| World facts | 关于世界的事实 | “The stove gets hot” |
| Experiences | agent 自己的经历 | “I touched the stove and it really hurt” |
| Observations | 从多条记忆 consolidate 出的、带证据的信念 | 去重后的稳定判断 |
| Mental models / Pages | 对一个常问问题的「常驻答案」 | “What are this user's preferences?” |

**读写路径**：

- `retain`：**用 LLM 抽取**事实、时间、实体、关系，再归一化成实体、时间序列、稀疏/稠密向量与索引
  （README「Retain」）。
- `recall`：并行跑四种检索——语义向量、BM25 关键词、图（实体/时间/因果）、时间范围过滤，
  再用 reciprocal rank fusion + cross-encoder rerank 合并、按 token 预算裁剪（README「Recall」）。
- `reflect`：对记忆做更深的推理，形成新连接或回答需要「想一下」的问题。
- **后台 consolidation**：把相关事实合并成 observation，保留原文引用与 proof count，
  新证据只「refine」不覆盖（README「Observations」）。
- **Mental model / Page**：问题定义一次，后台持续重写答案；读取是**纯数据库读**，不走检索、不调 LLM
  （README「Mental Models & Pages」）。

**隔离**：**bank** 是隔离单位，一个 bank = 一个用户/agent/项目，明确「no cross-bank leakage」；
bank 可带 disposition traits（怀疑、字面、共情）影响 reflect（README「Memory Banks」）。

**存储**：PostgreSQL + pgvector（或 Oracle 23ai）；本地开发可用 `pg0`——一个内嵌 PostgreSQL
单二进制，无需外部服务；生产要求 PG 15+ / pgvector 0.5+（[storage 文档](https://hindsight.vectorize.io/developer/storage)）。

**并发**：文档只声明 PostgreSQL 提供「ACID transactions across all data types」，
**没有**描述隔离级别、锁、或并发写冲突解决；这一点标注「未核实」，不要假设它替你做单写者。

**论文**：[arXiv:2512.12818](https://arxiv.org/abs/2512.12818)（“Hindsight is 20/20: Building Agent
Memory that Retains, Recalls, and Reflects”）。摘要给出的四类网络是 world facts、agent experiences、
synthesized entity summaries、evolving beliefs；报告 LongMemEval 91.4%、LoCoMo 89.61%（20B 开源模型）。

**对文境**：**部分可借鉴**。值得抄的是「observation 带证据 + mental model 预计算成可直接读的页」，
这正好对应「有界读取窗口 + 可解释」；不值得抄的是独立服务、`retain` 走 LLM、bank 只按 agent 隔离
（没有 branch / viewer 维度）。

### 3.2 Graphiti / Zep（`getzep/graphiti`、`getzep/zep`）

**定位**：Graphiti 是开源「temporal context graph」框架；Zep 是商业平台，Graphiti 是 Zep 内部的
图构建引擎（README「Graphiti and Zep」明确区分：Graphiti 是框架，Zep 是托管 context layer）。

**记忆模型**：

- 图由 **entities + facts/relationships（边，带 validity window）+ episodes（原始输入）** 组成
  （README「What is a Context Graph?」）。
- 事实变化时**旧事实 invalidated，不删除**；可查「现在为真」或「某时刻为真」（README「Why Graphiti?」）。
- 每个实体/关系都能 trace 回产生它的 episode，即 **provenance**。
- 检索是 hybrid：语义 embedding + BM25 + 图遍历；增量构图，不需整图重算。

**存储**：README 当前列出的后端是 Neo4j 5.26 / FalkorDB 1.1.2 / Amazon Neptune（+ OpenSearch），
未列 Kuzu。源码里 `add_episode(group_id=...)` 是显式参数，`group_id` 用于图内分区
（[`graphiti.py`](https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py)）。

**并发**：README「Graphiti's ingestion pipelines are designed for high concurrency」，但默认
`SEMAPHORE_LIMIT` 设得低，目的是避免 LLM provider 429；这是**限流**，不是写冲突解决。

**论文**：[arXiv:2501.13956](https://arxiv.org/abs/2501.13956)（Zep / Graphiti，DMR 94.8% vs
MemGPT 93.4%，LongMemEval 最高 +18.5%、延迟降 90%）。

**对文境**：**部分可借鉴**。「事实带 validity window、失效不删除」可以用普通 PG 表实现，
不需要图数据库；图数据库服务本身与「单进程、不引入额外服务」冲突。

### 3.3 Mem0（`mem0ai/mem0`）

**定位**：生产向的「memory layer」，有 OSS、Cloud、自托管 server、CLI、agent skills。

**记忆模型（2026-04 新算法，README）**：

- **Single-pass ADD-only extraction**：一次 LLM 调用抽取，**没有 UPDATE/DELETE**；记忆只累积、不覆盖。
- Agent-generated facts 与用户事实同等权重。
- Entity linking：抽取实体、embedding、跨记忆链接以提升检索。
- Multi-signal retrieval：semantic + BM25 + entity matching 并行打分后融合。

官方文档进一步说明：默认**存抽取后的事实，不存逐字 transcript**；自动抽取路径是 additive，
需要纠正时用显式 `update` / `delete`；存储分三块——SQL database（事实与元数据的 source of truth）、
vector database（embedding）、entity store（实体）；**Graph Memory 是 Platform-only，OSS 没有图记忆**，
OSS 检索只做 entity-overlap boosting（[memory-types 文档](https://docs.mem0.ai/core-concepts/memory-types)）。

**论文**：[arXiv:2504.19413](https://arxiv.org/abs/2504.19413)。注意论文描述的是较早的
extract–consolidate–retrieve + graph 变体，与 2026-04 的 ADD-only 算法已有差异，引用时要区分版本。

**对文境**：**不适合**。默认单位是「用户级全局记忆池」，抽取发生在写入路径且依赖 LLM，
没有 branch / viewer 概念；「ADD-only」虽然对可回放友好，但它不解决「谁在何时可见」。

### 3.4 Letta / MemGPT（`letta-ai/letta`）

**定位**：stateful agent 平台（原 MemGPT），强调 agent 自己管理记忆。

**记忆模型**（[memory 文档](https://docs.letta.com/guides/agents/memory)）：

- **Memory blocks / core memory**：可编辑文本块，**pinned 到 system prompt**，由 agent 通过
  memory tools 或开发者通过 API 修改；block 可 attach 到多个 agent（shared blocks）。
- **Archival memory**：语义可检索的长期事实库，**不占 context**，只能通过工具按需查询；
  agent 用 `archival_memory_insert` / `archival_memory_search`，开发者可用 SDK 增删改查；
  文档称「unlimited storage」「no practical size limits」，且 agent 不能轻易修改/删除
  （[archival 文档](https://docs.letta.com/guides/agents/archival-memory)）。
- 所有状态（记忆、消息、推理、工具调用）都在数据库里，evict 出 context 后仍可检索。
- **Dreaming / sleep-time**：后台 subagent 定期回顾最近对话、consolidate 经验、更新记忆；
  新版用 **MemFS**——一个 git-backed memory filesystem，agent 决定把 lesson 放哪并 commit
  （[sleep-time 文档](https://docs.letta.com/guides/agents/sleep-time-agents)）。

**并发**：conversations 是同一 agent 的独立消息线程，可并发；文档没有描述 block 级锁或版本冲突。

**对文境**：**部分可借鉴**。core blocks（有界、常驻）+ archival（按需检索）的分层是对的；
但「agent 自行改写记忆」与「事件是权威、回放要确定」直接冲突，且它是独立服务。

### 3.5 MemOS（`MemTensor/MemOS`）

**定位**：Memory Operating System，统一 store / retrieve / manage；有 Cloud API、自托管服务、
插件（OpenClaw / Hermes / DeepSeek Harness）。

**记忆模型**：以 **MemCube** 为组织单位，记忆是「graph-structured」，可 inspect、可编辑，
不是黑盒 embedding store；统一 API 支持 add / retrieve / edit / delete（README「Key Features」）。
自托管需要 **Neo4j + Qdrant** 常驻（README「Self-Host the MemOS Service」）。

**对文境**：**不适合**。Neo4j + Qdrant 两套服务，运维成本远超 2–6 个角色的收益；
「可编辑图」对调试友好，但不是事件派生。

### 3.6 Cognee（`topoteretes/cognee`）

**定位**：开源 AI memory platform，把文档、代码、对话转成自托管知识图谱 + 向量。

**记忆模型**：四操作 `remember / recall / improve / forget`；文本 → 实体、关系、可检索 chunk；
代码 → 符号/依赖图；**session distillation** 把会话里被接受的经验并入永久图（README「How Cognee works」）。
检索时选 graph / vector / code context，并允许应用 inspect 检索证据。

**存储**：传统上需要图库 + 向量库 + Redis + 关系库；**自 1.0 起可在单个 Postgres 上跑**
关系 + PGVector + graph，但 README 明确这是 **demo feature**，生产版是授权产品
（README「Run the Whole Memory Layer on Postgres」）。

**论文**：[arXiv:2505.24478](https://arxiv.org/abs/2505.24478)（Cognee 的 KG/LLM 接口超参优化）。

**对文境**：**部分可借鉴**。「单 PG 同时承担关系 + 向量 + 图」的方向与 WenJing「能用一个 PG 就别开第二个存储」
一致，可关注其 demo 实现；`forget` 的显式删除语义也值得借鉴。但生产版授权、抽取依赖 LLM。

### 3.7 MIRIX（`Mirix-AI/MIRIX`）

**定位**：多 agent 记忆系统，论文 + 开源实现；个人助理场景（屏幕活动追踪、截图理解）。

**记忆模型**（[arXiv:2507.07957](https://arxiv.org/abs/2507.07957)）：**六类记忆**——
Core、Episodic、Semantic、Procedural、Resource、Knowledge Vault，由多 agent 框架动态协调
更新与检索。仓库里对应 `resource_memory_agent` / `semantic_memory_agent` / `episodic_memory_agent` /
`procedural_memory_agent`（README「Quick Start」）。

**存储**：Postgres；可选 **Neo4j provenance hypergraph**——实体是 anchor，事实是 n-ary frame，
每条 frame 引用它来自的记忆行；开启图记忆后，episodic/semantic 检索走图（README「Graph Memory」）。
**Auto-Dream**：显式 consolidation endpoint，合并重复、处理 stale/conflict，再写回（README「Auto-Dream」）。

**指标**：论文称 ScreenshotVQA 比 RAG baseline 高 35%、存储降 99.9%；LoCoMo 85.4%。

**对文境**：**部分可借鉴**。六类记忆的分类可以映射到角色记忆（episodic=经历、semantic=知道的事实、
procedural=行为模式、resource=可引用素材），但多 agent 路由 + Neo4j 对 2–6 角色过重。

### 3.8 MemoryOS（`BAI-LAB/MemoryOS`）

**定位**：OS 隐喻的分层记忆；论文 EMNLP 2025 Oral。

**记忆模型**（[arXiv:2506.06326](https://arxiv.org/abs/2506.06326)）：三级存储
**short-term / mid-term / long-term personal memory**，四个模块 Storage / Updating / Retrieval / Generation；
short→mid 按「对话链 FIFO」，mid→long 用「segmented page organization」；long-term 含
**user profile + user knowledge + assistant knowledge**。

仓库实现里可配 `short_term_capacity`（默认 7）、`mid_term_heat_threshold`、
`long_term_knowledge_capacity`（默认 100）、embedding model；支持 ChromaDB 与 MCP
（README「How It Works」「MemoryOS_Chromadb」）。

**对文境**：**部分可借鉴**。分层 + 阈值触发的更新策略，与 WenJing「有界窗口 + trim」同源；
但它的中心是「单个 user 的画像」，不是「多个角色各自的限知记忆」。

### 3.9 Memobase（`memodb-io/memobase`）

**定位**：**user profile-based** 长期记忆，面向聊天机器人 / 虚拟伴侣 / 教育工具。

**记忆模型**：

- 每个用户有一个**结构化 profile**（topic / sub_topic / content）和一条 **event timeline**；
  profile 是「已学到的稳定信息」，event 用来回答时间相关问题（README「Core Features」）。
- **不在 hot path 做记忆化**：新 blob 先进 per-user buffer，buffer 超过约 1024 tokens 或 idle 1 小时
  才 flush；也可手动 `flush(sync=True)`（README「Why need a flush?」）。
- 在线读取只做少量 SQL，声称 <100ms；处理后默认删除原始 blob，只保留相关记忆。
- 技术栈：FastAPI + Postgres + Redis，全 docker 化。

**活跃度**：2026-01-11 后无推送，近 10 个月停滞，需谨慎。

**对文境**：**不适合**。全局 user profile 与「角色只能看自己视角」冲突；PG + Redis 也是额外服务。
可借鉴的是「buffer + 异步 flush」的成本结构。

### 3.10 Supermemory（`supermemoryai/supermemory`）

**定位**：Memory API + app，强调「一个 API 给 agent 记忆、RAG、user profiles、connectors」；
有 Cloud 和 self-host。

**记忆模型**：自动从对话抽取事实、建 user profile、处理知识更新与矛盾、让过期信息失效；
profile 分 `static`（长期事实）与 `dynamic`（近期上下文），`recall` 返回相关记忆 + profile 摘要，
`context` 在会话开始时注入完整 profile（README「User profiles」「What your AI gets」）。

**对文境**：**不适合**。典型的「用户画像 + 云 API」抽象，与限知、分支、单写者三件事都冲突；
self-host 也只是把同样的全局画像搬到本地。

### 3.11 MemU（`NevaMind-AI/memU`）

**定位**：轻量、agent-driven 的「个人记忆，存成 wiki」；跨会话/agent/设备共享，自动从 agent history
蒸馏可复用 skill；核心记忆逻辑约 500 行（README「Personal memory, stored as Wiki」）。

**记忆模型**：记忆是**可读写的 wiki 文件** + 检索命中（hit 含 text、source description、track、path、
score、时间戳）；自动 skill extraction 把 agent history 变成可复用 skill（README「Automatic skill extraction」）。

**存储**：`MEMU_DB` 配 SQLite（默认，**single writer**，brute-force cosine）或 Postgres（pgvector，
concurrent access、large stores）（README「Storage backends」）。

**对文境**：**部分可借鉴**。「记忆是 inspectable 文件 + SQLite 单写者」与 WenJing 的实例目录
（`events.jsonl` + `memory/<character>.json`）结构同构；但它的 scope 是「个人」，没有 branch / viewer，
且 skill extraction 依赖 LLM。

### 3.12 Memori（`MemoriLabs/Memori`，原 `GibsonAI/memori`）

**定位**：agent-native memory infrastructure，把 agent execution / conversation 转成结构化持久状态；
支持 managed cloud、single-tenant、VPC、on-prem。

**记忆模型**：以 **entity / process / session** 三元归属——entity 是「人/地点/物」，
process 是「agent / LLM 交互 / 程序」，session 是当前交互；默认自动设置 session，也可显式
`setSession` / `new_session`（README「Session Management」）。提供 `memori_recall` /
`memori_recall_summary` 工具；支持 BYODB（SQLite / Postgres / MySQL / TiDB）。
LoCoMo 87% overall，平均 721 tokens/query（README「LoCoMo Benchmark」）。

**对文境**：**部分可借鉴**。`entity × process × session` 的归属模型很接近「角色 × 会话」，
但缺 branch 维度，且抽取/召回仍依赖 LLM。BYODB 的姿态值得学——不要绑定自有存储。

### 3.13 Memary / Motorhead / Redis Agent Memory

- **Memary**（MIT，2024-10 停更）：知识图谱 + memory module，Neo4j / FalkorDB，支持
  「多图」——不同 graph id 对应不同 agent 的记忆与知识上下文；检索是递归的：先找 query 的
  关键实体，再取深度 2 的子图，多实体时做 multi-hop join（README「Knowledge Graphs」）。
  **对文境**：不适合——图数据库 + 停更；「多图 = 多 agent」的思路与「按角色隔离」相通。
- **Motorhead**（Apache-2.0，2025-07 停更）：Redis-backed memory server；当消息超过
  `window_size` 时，把 `window_size / 2` 条消息做增量摘要，后续摘要继续增量叠加
  （README「Why use Motorhead?」）。**对文境**：部分可借鉴「增量摘要」作为派生缓存，
  但 Redis 是额外服务，且它只做对话摘要。
- **Redis Agent Memory**（Apache-2.0，研究工件）：两层——**session memory**（活跃会话状态，可配 TTL）
  + **long-term memory**（抽取事实 + 向量）；新事件进 session 后**后台**抽取并提升到长期记忆，
  不拖慢在线 loop（README「How it works」）。开源 V0 是研究基础，当前产品是 Redis Iris 托管服务。
  **对文境**：不适合托管；「session 热层 + TTL + 后台提升」的成本结构可借。

### 3.14 Basic Memory / mcp-memory-service

- **Basic Memory**（AGPL-3.0，4.5k stars，活跃）：**Markdown 文件即记忆**，人和 AI 双向读写同一批
  文件；observations + wikilinks 组成知识图谱；本地默认 **SQLite 索引**（可选 Postgres），
  「just files plus a local SQLite index, no servers required」；支持 MCP、语义检索、reindex
  （README「Your AI never forgets again」「Basic Memory supports SQLite…」）。
  **对文境**：部分可借鉴——「文件是权威/可读、索引是派生、可 reindex」与 WenJing 的
  `MemoryStore` 设计同源；但 AGPL-3.0 有传染性，且它是单用户知识库，没有 branch / viewer。
- **mcp-memory-service**（Apache-2.0，活跃）：自托管 memory backend，REST + MCP + OAuth + CLI + dashboard；
  存 decisions、共享 causal knowledge graph（typed edges: causes / fixes / contradicts）；
  `X-Agent-ID` header 按 agent 身份打标并限定检索；`conversation_id` 绕过 dedup；
  后台 consolidation（clustering / compression / association discovery），
  heuristic contradiction detection 可把旧记忆标为 superseded；后端可选 SQLite（local、single-user）、
  Cloudflare、Milvus（README「Why Agents Need This」「Features」）。
  **对文境**：部分可借鉴——`X-Agent-ID` 的「按 agent 限定检索」与「按 viewer 投影」相通；
  但「shared memory across all agents」的默认姿势与限知冲突。

### 3.15 2025–2026 新出现、定位与文境相近的项目

> 这一组不是「记忆基础设施」，而是「游戏 / 叙事 / 角色」域内直接相关的实现，参考价值在**领域建模**，
> 不在通用记忆层。

- **NovelClaw**（`iLearn-Lab/NovelClaw`，MIT，375 stars，活跃）：dynamic-memory-first 的长篇
  小说写作工作区；有 sessions、storyboards、manuscript surfaces、character/world views、
  **editable memory banks**，强调「memory-aware drafting」与跨章节连续性（README「Overview」）。
  **对文境**：部分可借鉴——同属「长篇叙事 + 角色/世界状态 + 可编辑记忆库」，
  但它是写作工作流（人审、章节），不是实时多角色游戏；它的「memory bank 可 inspect/编辑」
  对教师端审核有启发。
- **Quilltale**（`Aeesh/Quilltale`，**无 LICENSE**，13 stars，个人项目）：persistent AI RPG；
  **结构化世界模型**（Python dataclass，locations/items/NPCs/exits 都是显式字段，不放在 LLM context 里）；
  **validated transitions**（AI 提状态变更 → JSON → 先校验再应用，非法变更被拒绝）；
  **per-NPC episodic memory**（每条含 turn number、description、emotional tone、significance 1–3，
  每轮把当前地点 NPC 的「最显著」记忆注入 context）；World Snapshot 面板展示当前世界真相
  （README「How it is built」）。
  **对文境**：**概念上最接近**——「世界状态显式建模 + 变更先校验 + 角色各自的情景记忆 + 按显著性检索」
  几乎就是 WenJing 想要的运行时形态。但它无 LICENSE（不能抄代码，只能借思想）、无 branch、
  无多会话持久化（作者自己列为下一步）。
- **OpenGameAgent**（`EricSun0218/OpenGameAgent`，MIT，61 stars，活跃）：TypeScript runtime，
  面向 AI-native game characters/worlds，提供 durable state、reliable actions、memory、tools，
  接 Unity / Godot / Unreal（README）。**对文境**：部分可借鉴——「游戏角色运行时 + durable state + memory」
  的工程切分；但小项目，未见生产验证。

补充两个「工程上值得看、但非游戏域」的新项目：

- **Memoripy**（Apache-2.0，691 stars，活跃）：**bitemporal records + immutable versions**、
  evidence/receipts、retrieval 多路 union + RRF、scope isolation、**forget 记为 versioned deletion**
  （README「Agent memory with receipts」）。**对文境**：部分可借鉴——「证据 + 不可变版本 + 版本化删除」
  与事件溯源同源；但它是自带存储的库。
- **CortexDB**（MIT，511 stars，活跃）：**一个 SQLite 文件**装下向量 + FTS5 + RDF 知识图谱 +
  `as_of` 时间查询；新记忆可把旧记忆标为 **superseded**（保留但不作为当前召回）；
  90 秒 idle 后自动蒸馏会话（README「What's inside」）。**对文境**：部分可借鉴——
  「单文件本地存储 + as_of + superseded」很适合单机实例；但 Go 实现、自有 ontology，接入成本高。

---

## 4. 框架内建记忆

### 4.1 LangGraph / LangMem（`langchain-ai/langgraph`、`langchain-ai/langmem`）

**LangGraph 的两层**（[memory 文档](https://docs.langchain.com/oss/python/langgraph/memory)）：

- **Short-term memory = thread 内的 graph state + checkpointer**：状态持久化到 DB，可按 thread 恢复；
  每次 invoke / step 更新，step 开始时读取；长历史靠删除/遗忘旧消息管理。
- **Long-term memory = 跨 thread 的 Store**：记忆是 **JSON document**，组织在自定义 **namespace**
  （类似文件夹）+ **key**（类似文件名）下；支持 content filter 的跨 namespace 搜索。
- **Memory 类型**：semantic（事实，profile 或 collection）、episodic（经历，常用 few-shot）、
  procedural（规则，常通过改 prompt 而非改权重）。
- **Hot path vs background**：热路径写入实时但增加延迟；后台写入不阻塞主流程，但要决定频率。

**LangMem**：提供 memory tools（`create_manage_memory_tool` / `create_search_memory_tool`）+
**background memory manager**（自动抽取、consolidate、更新）；原生接 LangGraph `BaseStore`，
生产建议 `AsyncPostgresStore` 而非 `InMemoryStore`（README「Key features」）。

**并发**：文档**没有**描述 long-term store 的锁 / 冲突解决 / 并发写保证；不能假设它替你做串行化。

**对文境**：**结构上最贴合**。`checkpointer` ≈ WenJing 的命令快照缓存；`Store` 的 namespace
可以编码 `(session_id, branch_id, character)`；hot path / background 分离 ≈「命令只读、整理放后台」。
但它本身不是事件派生，**必须由 WenJing 自己保证 Store 可从事件重建**。

### 4.2 LlamaIndex（`run-llama/llama_index`）

**记忆模型**（[memory 文档](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/)）：

- `Memory` 类 = **short-term message buffer** + 可选 **long-term memory blocks**。
- short-term 是 FIFO 消息队列，默认 `token_limit=30,000`，`chat_history_token_ratio=0.7`，
  `token_flush_size=3,000`；超过比例后把最老的、装得进 flush_size 的消息 flush 给每个 block。
- 内置 blocks：`StaticMemoryBlock`（固定信息）、`FactExtractionMemoryBlock`（LLM 抽事实，有
  `max_facts`，超了做摘要）、`VectorMemoryBlock`（向量库批量存取）；每个 block 有 `priority`，
  `priority=0` 永远保留，其余按优先级截断。
- 读取时 short-term + long-term 合并；超限按 priority 截断；默认存 **in-memory SQLite**，
  可换远程 async DB 或实现 `AsyncDBChatStore`。
- 旧的 `ChatMemoryBuffer` / `ChatSummaryMemoryBuffer` / `VectorMemory` / `SimpleComposableMemory`
  仍在但已标 deprecated。

**对文境**：**部分可借鉴**。token 预算 + 比例触发 flush + block priority 的窗口管理很成熟，
可直接借「有界窗口 + 超限截断」的工程细节；但它的 block 是 prompt 拼装层，不是权威。

### 4.3 AutoGen / AG2

**AutoGen**（`microsoft/autogen`，[memory 文档](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html)）：

- `Memory` protocol 五个方法：`query` / `update_context` / `add` / `clear` / `close`。
- `ListMemory`：按时间顺序保存，最直接、可调试；运行时 agent 发 `MemoryQueryEvent`，
  `update_context` 把检索结果注入 `model_context`，格式化成
  “Relevant memory content (in chronological order): …”。
- `MemoryContent` 有 `content` / `mime_type` / `metadata`。
- 向量实现：`ChromaDBVectorMemory`（collection、persistence_path、k、score_threshold）、
  `RedisMemory`；也有 `Mem0Memory` 集成。

**AG2**（`ag2ai/ag2`，2026 版源码与旧文档已不同）：当前代码里是 **KnowledgeStore + policies**：

- `MemoryKnowledgeStore`：内存 dict，路径即 key，写入用 `asyncio.Lock` 串行
  （[`ag2/knowledge/memory.py`](https://github.com/ag2ai/ag2/blob/main/ag2/knowledge/memory.py)）。
- `WorkingMemoryPolicy`：把 `/memory/working.md` 注入 system prompt，作为 agent 的持久工作状态
  （[`working_memory.py`](https://github.com/ag2ai/ag2/blob/main/ag2/policies/working_memory.py)）。
- `EpisodicMemoryPolicy`：读 `/memory/conversations/` 最近 `max_episodes=5` 条会话摘要，
  拼成 “## Past Conversations” 注入
  （[`episodic_memory.py`](https://github.com/ag2ai/ag2/blob/main/ag2/policies/episodic_memory.py)）。

**对文境**：**部分可借鉴**。AG2 的 `working.md + 最近 5 条会话摘要 + asyncio.Lock` 与
WenJing 的 `working_memory / personal_log / rejected` 有界窗口几乎同构，是「最小可用实现」的好参照；
但它没有 branch / event 归属，摘要依赖 LLM。

### 4.4 CrewAI（`crewAIInc/crewAI`）

**记忆模型**（[memory 文档](https://docs.crewai.com/en/concepts/memory)）：

- 已从旧的 short-term / long-term / entity / external 四类，统一成一个 `Memory` 类：
  `remember` / `recall` / `forget` / `extract_memories` / `tree` / `info`。
- **Hierarchical scopes**（类似文件系统，如 `/project/alpha`、`/agent/researcher`）；
  `memory.scope(...)` 限定子树，slices 可组合多个 scope（可只读）。
- **LLM-assisted encoding**：LLM 推断 scope、categories、importance；相似记录可能触发
  `keep` / `update` / `delete` / `insert_new`；`remember_many()` 非阻塞、批内 dedup。
- 检索打分：`composite = semantic_weight * similarity + recency_weight * decay + importance_weight * importance`；
  `recall()` 支持浅层向量与深层 LLM 辅助检索；读屏障保证 pending writes 先落盘。
- 默认存储 **LanceDB**（`./.crewai/memory`），可自定义 `StorageBackend`。

**对文境**：**部分可借鉴**。层级 scope 可以映射 `session / branch / character`，
composite 打分（相似度 + 时近 + 重要度）也适合角色记忆；但 LLM 推断 scope/importance
发生在写入路径，且默认 LanceDB 是额外存储。

### 4.5 OpenAI Agents SDK Sessions（`openai/openai-agents-python`）

**模型**（[sessions 文档](https://openai.github.io/openai-agents-python/sessions/)）：

- Session 存「与 session ID 绑定的对话历史」；runner 在 run 前取历史、run 后把新 item 写回。
- 协议方法：`get_items` / `add_items` / `pop_item` / `clear_session`。
- 实现：`SQLiteSession`（内存或文件）、`RedisSession`（跨 worker 共享）、`SQLAlchemySession`
  （生产已有 DB）、`OpenAIConversationsSession`（OpenAI 托管历史）。
- `SessionSettings(limit=N)` 只取最近 N 条；`session_input_callback` 可在模型调用前裁剪/重排，
  但只持久化新 turn。
- **信任边界**：SQLiteSession 不做完整性/认证，「does not authenticate stored rows or detect external
  edits, deletions, reordering, or replay」；session ID 不认证用户。

**对文境**：**部分可借鉴**。它把「会话历史」做成简单、可替换的存储接口，适合作为
「命令历史 / 对话窗口」的参照；但没有抽取、没有 branch、没有 viewer。

### 4.6 Google ADK（`google/adk-python`）

**模型**（[memory 文档](https://adk.dev/sessions/memory/)）：

- **SessionService** = 单次对话的 event history + 临时 state，是「short-term memory」。
- **MemoryService** = 跨会话的可搜索长期记忆；接口有 `add_session_to_memory`、
  `add_events_to_memory`、`add_memory`、`search_memory`。
- 实现：
  - `InMemoryMemoryService`：存**完整对话**、关键词匹配、重启即丢（原型用）。
  - `VertexAiMemoryBankService`：托管、LLM 抽取并 consolidate、语义检索、支持 `enable_consolidation`。
  - `VertexAiRagMemoryService`：把完整 transcript 存 Knowledge Engine，按向量检索。
- **Scope**：按 `app_name` + `user_id` 分区；`session_id` 是 provenance，不是检索边界。

**对文境**：**部分可借鉴**。「session 短 / memory 长」的分离与 WenJing 一致；
但它的 memory 是 user 级共享，与「角色限知」冲突；InMemory 的「存全文 + 关键词」过于简单。

---

## 5. 学术与仿真实现

### 5.1 Generative Agents（`joonspk-research/generative_agents`）

**模型**（[arXiv:2304.03442](https://arxiv.org/abs/2304.03442)）：

- **Memory stream**：用自然语言记录 agent 的全部经历（observation）。
- **Reflection**：把记忆综合成更高层的反思。
- **Retrieval**：按 **recency / importance / relevance** 三项打分动态召回，用于规划行为。
- 25 个 agent 的小镇涌现出传播邀请、约会、协调赴约等行为；消融显示 observation / planning /
  reflection 都关键。

**对文境**：**部分可借鉴（角色记忆模型最贴近）**。「memory stream + reflection + 三因子检索」
可以直接映射为「角色经历流 + 定期摘要 + 按重要性/时近性/相关性取最近 N 条」；
但它是单机仿真，不解决并发、分支、可见性。

### 5.2 Voyager / Reflexion

- **Voyager**（[arXiv:2305.16291](https://arxiv.org/abs/2305.16291)，MIT，2024-04 停更）：
  **ever-growing skill library of executable code**，把复杂行为存成可检索、可组合的 skill；
  新世界可复用旧 skill（README）。**对文境**：部分可借鉴——「procedural memory」可以做成
  「角色行为模式 / 已验证的互动脚本」库，但不要引入代码执行。
- **Reflexion**（[arXiv:2303.11366](https://arxiv.org/abs/2303.11366)，MIT，2025-01）：
  用语言化的自我反思（verbal reinforcement）替代梯度更新；`use_memory` 可持久化 self-reflection
  （README）。**对文境**：部分可借鉴——`rejected` 列表可以扩展成「被驳回提议 + 原因」的反思记忆；
  但反思会改变后续行为，需确保它不影响历史回放。

### 5.3 A-MEM（`agiresearch/A-mem`）

**模型**（[arXiv:2502.12110](https://arxiv.org/abs/2502.12110)）：借 Zettelkasten，
每条记忆生成含上下文/关键词/标签的结构化笔记；新记忆到来时主动找关联建链；
**memory evolution**——新记忆可触发对旧记忆上下文与属性的更新（README/论文）。

**对文境**：**不适合当权威**。「新记忆反向改写旧记忆」与「事件不可变、可回放」直接冲突；
可借鉴的只是「每条记忆带结构化属性（上下文/关键词/标签）」的存储格式。

### 5.4 HippoRAG / GraphRAG

- **HippoRAG**（MIT，活跃）：受人类长期记忆启发的 RAG，KG + **Personalized PageRank** 做多跳检索；
  HippoRAG 2（[arXiv:2502.14802](https://arxiv.org/abs/2502.14802)）强调 associativity / sense-making；
  原始论文 [arXiv:2405.14831](https://arxiv.org/abs/2405.14831)。**对文境**：只作派生检索索引，
  不能当权威；PPR 对「角色关系网」的多跳召回有参考价值。
- **GraphRAG**（MIT，36.6k stars，**维护模式**）：静态文档 → 实体/关系图 + 社区摘要；
  indexing 成本高（README 明确警告）。**对文境**：不适合运行时；若要做「课文/剧本素材的离线分析」
  可以看，但不要放进命令热路径。

### 5.5 AgentSociety（`tsinghua-fib-lab/AgentSociety`）

tick 驱动的社科仿真平台（Ray + 每 tick 重建）；本仓库已有专门调研
`docs/research/agentsociety-architecture-study.md`，结论是「与本项目命令驱动、2–6 角色、单 worker
的假设相反，不建议整体参考」。本篇不重复。

---

## 6. 存储底座（只在与记忆设计相关时提）

| 底座 | 仓库 | 许可 | 适用判断 |
|---|---|---|---|
| pgvector | `pgvector/pgvector` | PostgreSQL License | **首选派生索引**：WenJing 已有 PG，加扩展即可；不引入新服务 |
| sqlite-vec | `asg017/sqlite-vec` | Apache-2.0 | 单机实例的轻量向量索引；与 `events.jsonl` 同目录可接受 |
| Chroma | `chroma-core/chroma` | Apache-2.0 | 适合原型；生产多一个服务，不优先 |
| Qdrant | `qdrant/qdrant` | Apache-2.0 | 大规模向量检索；对 2–6 角色过重 |

共同原则：**它们都只是「可丢弃、可重建」的派生索引**，不能表达「撤回 / 回溯 / 可见性 / 时间有效性」；
不要反过来从索引推导游戏状态（已有调研 §2.1 已论证）。

---

## 7. 对比矩阵

| 框架 | 记忆单位 | 抽取时机 | 检索方式 | 存储 | 并发/一致性语义 | 许可 |
|---|---|---|---|---|---|---|
| Hindsight | world fact / experience / observation / mental model；bank 隔离 | 写入时 LLM 抽取；后台 consolidate | 语义 + BM25 + 图 + 时间，RRF + rerank | PG + pgvector / Oracle；可内嵌 pg0 | 只声明 ACID，未文档化锁/隔离 | MIT |
| Graphiti | entity + 带 validity window 的 fact 边 + episode | 写入时增量构图 | 语义 + BM25 + 图遍历 | Neo4j / FalkorDB / Neptune | `SEMAPHORE_LIMIT` 限流；无写冲突方案 | Apache-2.0 |
| Mem0 | 抽取后的事实 + entity | 写入时单次 LLM（ADD-only） | 语义 + BM25 + entity | SQL + vector + entity store | 未文档化 | Apache-2.0 |
| Letta | core memory block / archival passage / message | agent 主动工具调用 + 后台 dreaming | block 常驻；archival 语义检索 | DB-backed（含 pgvector 语义，文档未点名） | conversation 并发；无 block 锁 | Apache-2.0 |
| MemOS | MemCube / graph | 写入时 | 图 + 向量 | Neo4j + Qdrant | 未文档化 | Apache-2.0 |
| Cognee | 实体/关系图 + chunk | 写入时（可本地 GLiNER） | graph / vector / code | 图库 + 向量库 + PG（单 PG 为 demo） | 未文档化 | Apache-2.0 |
| MIRIX | 六类记忆（core/episodic/semantic/procedural/resource/vault） | 多 agent 协调 + Auto-Dream | 按类型路由；可选图检索 | Postgres + 可选 Neo4j | 未文档化 | Apache-2.0 |
| MemoryOS | short / mid / long-term；profile + knowledge | 容量/热度阈值触发 | 多源检索 | 本地文件 + ChromaDB 可选 | 未文档化 | Apache-2.0 |
| Memobase | user profile + event timeline | buffer 异步 flush | profile 直读 + event 检索 | PG + Redis | 未文档化 | Apache-2.0 |
| Supermemory | 抽取事实 + static/dynamic profile | 写入时自动抽取 | recall + context | 托管 / self-host | 由服务决定 | MIT |
| MemU | wiki 文件 + skill | 自动 skill extraction | 语义 + 关键词 | SQLite（单写者）/ PG pgvector | SQLite 单写者；PG 并发 | Apache-2.0 |
| Memori | entity / process / session | 后台捕获 | recall + summary | BYODB（SQLite/PG/MySQL/TiDB） | 未文档化 | Apache-2.0 |
| Basic Memory | Markdown note + observation + wikilink | 人/AI 显式写 + 自动索引 | FTS + 向量 | Markdown + SQLite 索引（可选 PG） | 单用户；sync 语义 | AGPL-3.0 |
| mcp-memory-service | observation + causal KG | 显式存 + 后台 consolidate | 语义 + 关键词 + tag | SQLite / Cloudflare / Milvus | 未文档化 | Apache-2.0 |
| LangGraph/LangMem | JSON doc（namespace + key）/ thread checkpoint | 热路径工具或后台 manager | `get` / `search` + content filter | 任意 BaseStore（生产 PG） | **未文档化** | MIT |
| LlamaIndex | FIFO message + memory blocks | token 超限 flush | 向量 / 事实 / 静态 | 默认内存 SQLite，可换 DB | 未文档化 | MIT |
| AutoGen | MemoryContent（text/mime/metadata） | 显式 add | 向量 / 列表 | Chroma / Redis | 未文档化 | CC-BY-4.0（仓库） |
| AG2 | KnowledgeStore 路径 + working.md + 会话摘要 | 显式写 + policy 注入 | 读最近 N 条 | 内存 dict（可扩展） | `asyncio.Lock` 串行写 | Apache-2.0 |
| CrewAI | 统一 Memory + 层级 scope | LLM 推断 scope/importance | 向量 + composite 打分 | LanceDB 默认 | 读屏障；未文档化锁 | MIT |
| OpenAI Sessions | 对话 item 列表 | 每 run 后写回 | 按 session 取最近 N 条 | SQLite / Redis / SQLAlchemy | 无完整性/认证保证 | MIT |
| Google ADK | session event / memory entry | session 结束或显式 add | 关键词 / 语义 | 内存 / Vertex Memory Bank / RAG | 未文档化 | Apache-2.0 |
| Generative Agents | memory stream 条目 + reflection | 观察时写；定期 reflect | recency + importance + relevance | 本地 JSON / 内存 | 单机仿真，无并发语义 | Apache-2.0 |
| A-MEM | Zettelkasten note + links | 写入时建链 + 改写旧记忆 | 向量 + 链接 | 向量库 | 未文档化 | MIT |
| HippoRAG | KG + passage | 离线/增量索引 | PPR + 向量 | 向量库 + 图 | 未文档化 | MIT |
| Quilltale | world state + per-NPC episodic entry | 每轮显式写 | 按 NPC 地点 + significance | 内存/文件（无多会话） | 单机，无并发语义 | 无 LICENSE |

---

## 8. 哪一款最适合文境

### 8.1 文境的四条硬约束（落到代码）

1. **事件是唯一权威，记忆是可重建的派生**：
   `CharacterMemory.trim()` 的注释写明「事件流才是全量权威；快照/进程内记忆只是读取窗口」
   （`backend/app/domain/agents/character.py`）；`FileMemoryStore` 的 docstring 写明
   `events.jsonl` 是追加权威，`memory/<character>.json` 只是派生缓存
   （`backend/app/infrastructure/memory_store.py`）。
2. **角色记忆是有界读取窗口（最近 10 条）+ 限知视角**：
   `working_memory` / `personal_log` / `rejected` 由 `CHARACTER_MEMORY_LIMIT` 截断；
   `plot_entries_for(viewer)` 是叙事摘要的唯一读取口，按事件参与者投影
   （`backend/app/domain/game/game_runtime.py`）。
3. **单进程单 worker + 进程内会话写锁 + 版本 CAS**：
   `SessionApplication._lock_for` 把「恢复 → LLM → 提交」与命令外事件串行化；
   `session_store.restore` 用 `with_for_update`、`commit` 用 version CAS；
   `MemoryStore` 用 `instance.lock` 做单写者。
4. **记忆条目按「角色 × 分支 × 事件」归属，跨会话隔离**：
   事件流有 `branch_id` / `event_id`；实例目录按 `session_id` 隔离；
   角色记忆从 `proposal` / `character_speech` / `character_created` 折叠重建。

这四条合起来意味着：**任何把记忆变成第二权威、把写入放到命令热路径、或需要多写者共识的框架，
都不能直接接**。

### 8.2 逐款判断

| 框架 | 判断 | 一句话理由 |
|---|---|---|
| **LangGraph / LangMem** | **可用（结构最贴合）** | checkpointer=快照缓存、Store namespace 可编码 `(session, branch, character)`、热/后台分离；但 Store 必须由事件重建，不能当权威 |
| Hindsight | 部分可借鉴 | observation 带证据 + mental model 预计算页，正好是有界读取窗口；但独立服务 + retain 走 LLM |
| Graphiti / Zep | 部分可借鉴 | validity window + 失效不删除，可用普通 PG 表实现；图数据库服务不适合 |
| Mem0 | 不适合 | 用户级全局记忆池 + 写入时 LLM 抽取，无 branch/viewer |
| Letta | 部分可借鉴 | core blocks + archival 分层好；agent 自改记忆破坏回放，且是独立服务 |
| MemOS | 不适合 | Neo4j + Qdrant 两套常驻服务 |
| Cognee | 部分可借鉴 | 单 PG 跑关系+向量+图值得看；生产版授权、抽取依赖 LLM |
| MIRIX | 部分可借鉴 | 六类记忆可映射角色记忆；多 agent + Neo4j 过重 |
| MemoryOS | 部分可借鉴 | 短/中/长分层 + 阈值更新可借；用户画像中心不适合多角色 |
| Memobase | 不适合 | 全局 user profile 与限知冲突；PG + Redis 额外服务 |
| Supermemory | 不适合 | 云托管 + 用户画像，三条约束全冲突 |
| MemU | 部分可借鉴 | wiki 文件 + SQLite 单写者与实例目录同构；个人 scope、无 branch |
| Memori | 部分可借鉴 | entity×process×session 归属接近「角色×会话」；无 branch，抽取依赖 LLM |
| Memary | 不适合 | 图数据库 + 停更 |
| Motorhead | 部分可借鉴 | 增量摘要窗口可作派生缓存；Redis 额外服务 |
| Redis Agent Memory | 不适合 | 托管服务；但「session TTL + 后台提升」可借 |
| Basic Memory | 部分可借鉴 | Markdown + SQLite 索引、可 reindex，与文件派生同源；AGPL + 单用户 |
| mcp-memory-service | 部分可借鉴 | `X-Agent-ID` 按 agent 限定检索；共享池与限知冲突 |
| LlamaIndex Memory | 部分可借鉴 | token 预算 + flush 到 blocks 的窗口管理很成熟 |
| AutoGen | 部分可借鉴 | Memory 协议简单可插拔；无归属/分支 |
| AG2 | 部分可借鉴 | working.md + 最近 5 条摘要 + asyncio.Lock，与有界窗口同构 |
| CrewAI | 部分可借鉴 | 层级 scope 可映射 session/branch/character；LLM 编码写入 |
| OpenAI Sessions | 部分可借鉴 | 简单 conversation store + 本地 SQLite；无抽取/分支 |
| Google ADK | 部分可借鉴 | session/memory 分层；user 级共享与限知冲突 |
| Generative Agents | 部分可借鉴（角色模型最贴近） | memory stream + reflection + recency/importance/relevance；无并发/分支 |
| Voyager | 部分可借鉴 | skill library 可做 procedural memory；不要引入代码执行 |
| Reflexion | 部分可借鉴 | 自我反思记忆可扩展 `rejected`；会改行为，需隔离 |
| A-MEM | 不适合 | memory evolution 改写旧记忆，破坏可回放 |
| HippoRAG / GraphRAG | 不适合 | 纯检索索引；GraphRAG 已维护模式 |
| AgentSociety | 不适合 | tick 驱动仿真，已有调研明确不整体参考 |
| NovelClaw | 部分可借鉴 | 同域长期叙事 + 可编辑记忆库；写作工作流非实时游戏 |
| Quilltale | 部分可借鉴（概念最接近） | 结构化世界模型 + 校验转移 + per-NPC 情景记忆；无 LICENSE、无分支/多会话 |
| OpenGameAgent | 部分可借鉴 | 游戏角色运行时 + durable state + memory；小项目 |
| Memoripy | 部分可借鉴 | bitemporal + 不可变版本 + 版本化删除；自带存储的库 |
| CortexDB | 部分可借鉴 | 单 SQLite 文件 + `as_of` + superseded；Go / 自有 ontology |

### 8.3 与「限知 + 分支 + 单写者」直接冲突的抽象

| 抽象 | 代表 | 为什么冲突 |
|---|---|---|
| **用户画像 / 全局 profile** | Memobase、Supermemory、Mem0 的 user memory、Memori 的 entity 级记忆 | 画像默认「所有会话共享一份」，而 WenJing 的角色记忆必须按 `viewer` 与 `branch` 隔离；一个角色在 A 分支知道的事，不能在 B 分支出现 |
| **全局共享记忆池** | mcp-memory-service 的 shared memory、Letta 的 shared blocks、ADK 的 user 级 MemoryService | 共享池会让「不在场的角色」读到不该知道的叙事摘要，破坏限知 |
| **云托管记忆 API** | Hindsight Cloud、Supermemory、Zep Cloud、Redis Agent Memory | 世界状态/可见性/回溯是游戏核心语义，外包后无法保证与事件流一致；也违反单机部署前提 |
| **agent 自改记忆** | Letta memory tools、A-MEM memory evolution、MIRIX Auto-Dream 的部分路径 | 记忆变成第二权威，回放不确定；回溯后无法解释「为什么当时知道」 |
| **写入时 LLM 抽取/建图** | Mem0、Hindsight retain、Cognee、MIRIX、CrewAI encoding | 把 LLM 延迟和成本放大到每条命令；且抽取结果不可确定性重放 |
| **多写者共识 / 额外服务** | Graphiti（图库）、MemOS（Neo4j+Qdrant）、Memary（Neo4j/FalkorDB）、Motorhead（Redis） | 与「单进程单 worker + 进程内锁」前提冲突；运维成本远超 2–6 个角色 |

### 8.4 排序结论：如果只抄一款设计，抄哪款、抄哪部分

**抄 LangGraph / LangMem 的结构，不抄它的自动抽取。**

具体抄三件事：

1. **`checkpointer` = 快照缓存**：WenJing 的每分支 20 个命令快照已经是这个角色；把「快照只是缓存、
   删了只增加重放量」写成与 LangGraph 一样的显式契约。
2. **`Store` 的 namespace = 归属键**：用 `(session_id, branch_id, character)` 作为 namespace，
   key 用 `event_id`；Store 里的内容**全部从事件流重建**，不反向写回事件流。
   这正好补上 WenJing 目前「记忆在进程内 + 文件缓存」缺少的「按分支/角色可检索」能力。
3. **热路径只读、整理放后台**：命令路径只读已派生的窗口；摘要/去重/索引更新放到命令收尾或
   后台任务，和 LangMem 的 hot path vs background 同构。

**不要抄**：

- LangMem 的 `create_manage_memory_tool` 式「agent 自己决定存什么」——它会让记忆脱离事件派生；
- `AsyncPostgresStore` 的默认「可变 JSON doc」当权威——Store 必须可丢弃、可重建；
- 任何把抽取放在 `SessionApplication._lock_for` 内的做法。

**次选（如果只抄记忆模型，不抄结构）**：

- **Hindsight**：抄「observation 带原文引用 + proof count」「mental model 预计算成可直接读的页」。
  这两条能直接改善 `view_my_memory` 的可解释性与读取成本，且不需要引入它的服务。
- **Generative Agents**：抄「recency / importance / relevance 三因子召回」，作为角色记忆
  在 10 条窗口之外的**可选**检索策略；必须叠加 viewer / branch 过滤。
- **AG2**：抄「`working.md` + 最近 N 条会话摘要 + `asyncio.Lock`」的最小实现，
  如果不想引入 LangGraph Store 的抽象，这是最轻的落地形态。

**一句话排序**：结构抄 LangGraph/LangMem，记忆模型抄 Hindsight，角色召回抄 Generative Agents；
三者的共同前提都是「只做派生层，权威仍在事件流」。

### 8.5 如果要拼一个最小方案（不引入新服务）

1. **权威不变**：事件流 + `session_store` 行锁/CAS + `instance.lock`。
2. **派生表留在 PG**（或实例目录 JSON）：
   - `character_memory(session_id, branch_id, character, event_id, kind, text, importance, created_at)`；
   - `plot_digest(session_id, branch_id, viewer, event_id, summary, present)`；
   - 两者都由事件流重建，删表不影响状态。
3. **读取口唯一**：`view_my_memory` / `plot_entries_for(viewer)` 只读派生表，按
   `(branch_id, viewer)` 过滤，取最近 N 条；可选叠加 recency/importance 打分。
4. **后台整理**：命令收尾异步刷新派生表；失败只记日志，不回滚命令。
5. **语义召回（可选）**：pgvector 存 `event_id + embedding`，只作为候选集，最终仍按
   `(branch_id, viewer)` 过滤；索引可丢弃、可重建。

这套方案不需要 Hindsight/Graphiti/Mem0 的任何服务，只借了它们的**模型**。

---

## 9. 参考来源（本轮实际抓取，2026-11-15）

**仓库与文档**

- Hindsight：<https://github.com/vectorize-io/hindsight>；storage 文档
  <https://hindsight.vectorize.io/developer/storage>；论文 <https://arxiv.org/abs/2512.12818>
- Graphiti：<https://github.com/getzep/graphiti>；`group_id` 源码
  <https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py>
- Mem0：<https://github.com/mem0ai/mem0>；memory types
  <https://docs.mem0.ai/core-concepts/memory-types>；论文 <https://arxiv.org/abs/2504.19413>
- Letta：<https://github.com/letta-ai/letta>；memory
  <https://docs.letta.com/guides/agents/memory>；archival
  <https://docs.letta.com/guides/agents/archival-memory>；sleep-time
  <https://docs.letta.com/guides/agents/sleep-time-agents>
- MemOS：<https://github.com/MemTensor/MemOS>
- Cognee：<https://github.com/topoteretes/cognee>；论文 <https://arxiv.org/abs/2505.24478>
- MIRIX：<https://github.com/Mirix-AI/MIRIX>；论文 <https://arxiv.org/abs/2507.07957>
- MemoryOS：<https://github.com/BAI-LAB/MemoryOS>；论文 <https://arxiv.org/abs/2506.06326>
- Memobase：<https://github.com/memodb-io/memobase>
- Supermemory：<https://github.com/supermemoryai/supermemory>
- MemU：<https://github.com/NevaMind-AI/memU>
- Memori：<https://github.com/MemoriLabs/Memori>
- Memary：<https://github.com/kingjulio8238/Memary>
- Motorhead：<https://github.com/getmetal/motorhead>
- Redis Agent Memory：<https://github.com/redis/agent-memory-server>
- Basic Memory：<https://github.com/basicmachines-co/basic-memory>
- mcp-memory-service：<https://github.com/doobidoo/mcp-memory-service>
- LangGraph memory：<https://docs.langchain.com/oss/python/langgraph/memory>
- LangMem：<https://github.com/langchain-ai/langmem>
- LlamaIndex memory：
  <https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/>
- AutoGen memory：
  <https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html>
- AG2 memory 源码：<https://github.com/ag2ai/ag2/blob/main/ag2/knowledge/memory.py>、
  <https://github.com/ag2ai/ag2/blob/main/ag2/policies/working_memory.py>、
  <https://github.com/ag2ai/ag2/blob/main/ag2/policies/episodic_memory.py>
- CrewAI memory：<https://docs.crewai.com/en/concepts/memory>
- OpenAI Agents SDK sessions：<https://openai.github.io/openai-agents-python/sessions/>
- Google ADK memory：<https://adk.dev/sessions/memory/>
- Generative Agents：<https://github.com/joonspk-research/generative_agents>；论文
  <https://arxiv.org/abs/2304.03442>
- Voyager：<https://github.com/MineDojo/Voyager>；论文 <https://arxiv.org/abs/2305.16291>
- Reflexion：<https://github.com/noahshinn/reflexion>；论文 <https://arxiv.org/abs/2303.11366>
- A-MEM：<https://github.com/agiresearch/A-mem>；论文 <https://arxiv.org/abs/2502.12110>
- HippoRAG：<https://github.com/OSU-NLP-Group/HippoRAG>；论文
  <https://arxiv.org/abs/2502.14802>、<https://arxiv.org/abs/2405.14831>
- GraphRAG：<https://github.com/microsoft/graphrag>
- AgentSociety：<https://github.com/tsinghua-fib-lab/AgentSociety>；本仓库
  `docs/research/agentsociety-architecture-study.md`
- NovelClaw：<https://github.com/iLearn-Lab/NovelClaw>
- Quilltale：<https://github.com/Aeesh/Quilltale>
- OpenGameAgent：<https://github.com/EricSun0218/OpenGameAgent>
- Memoripy：<https://github.com/caspianmoon/memoripy>
- CortexDB：<https://github.com/liliang-cn/cortexdb>
- pgvector：<https://github.com/pgvector/pgvector>
- sqlite-vec：<https://github.com/asg017/sqlite-vec>
- Chroma：<https://github.com/chroma-core/chroma>
- Qdrant：<https://github.com/qdrant/qdrant>

**评测基准**

- LoCoMo：<https://arxiv.org/abs/2402.17753>
- LongMemEval：<https://arxiv.org/abs/2410.10813>

**本仓库交叉引用**

- `docs/research/agent-memory-architecture-survey.md`（并发方案模式 A–I）
- `docs/research/agentsociety-architecture-study.md`
- `docs/archive/handoffs/2026-11-memory-phase1.md`（角色记忆 Phase 1 实现）
- `backend/app/domain/agents/character.py`（`CharacterMemory` 有界窗口）
- `backend/app/infrastructure/memory_store.py`（实例目录 / 单写者 / 派生缓存）
- `backend/app/services/session_store.py`（行锁 + CAS）

---

## 10. 调研局限

1. **未做源码级行为验证**：除 AG2 的 memory 源码、Graphiti 的 `group_id` 签名、本仓库自身代码外，
   其余框架的「并发语义」均来自文档；文档没写的，我标了「未核实」，不代表它们一定没有锁/事务。
2. **benchmark 数字不可横比**：Hindsight、MIRIX、MemoryOS、Mem0、Memori、Zep 的分数来自各自论文/README，
   数据集版本、backbone、检索配置不同；Redis README 自己也提醒「分数不是永恒排名」。
3. **Hindsight 的论文与仓库版本可能不一致**：论文描述四类网络与三操作，README 增加了
   observations / mental models / decision models / pages 等工程概念；以 README 为准理解当前实现。
4. **部分项目已停更或进入维护模式**：Memary（2024-10）、Motorhead（2025-07）、GraphRAG（维护模式）、
   Memobase（2026-01 后无推送）；它们的架构仍有参考价值，但不要作为依赖。
5. **Quilltale 无 LICENSE**：只能读思想，不能复制代码；这是它排在「概念最接近」而非「可直接参考实现」
   的原因。
6. **未覆盖**：国内闭源/商业记忆服务、部分 2026 年下半年新项目（GitHub 搜索只按 stars 取前若干）、
   以及 MCP 生态里大量小型 memory server；本篇是「有代表性的清单」，不是穷举。
7. **若推进到 Issue/ADR，建议补三项验证**：
   ① 在 PG 上建「角色×分支×事件」派生表，验证删表可从事件流重建；
   ② 用事件流回放做「记忆一致性」测试（同一分支 → 同一可见叙事）；
   ③ 评估 pgvector 召回是否真的优于「最近 N 条 + 重要度」的确定性窗口。
