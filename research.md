# 文境 (Wenjing) — 项目调研报告

> 目标：调研 GitHub 上 AI 剧本杀 / 多智能体角色扮演类项目，为"文境"架构设计提供参考。

---

## 一、发现的项目总览

| 项目 | Stars | 语言 | 核心框架 | 特点 |
|------|-------|------|----------|------|
| **jubensha-ai** (JianWang97) | 124 | Python | FastAPI + LangChain + Next.js | 最完整的 AI 剧本杀实现，中文优先 |
| **PLAYER\*** (alickzhu) | 51 | Python | transformers + faiss | 学术界 MMG 框架，有双语数据集 WellPlay |
| **detective-agentic-mysteries** (suuus) | 2 | TypeScript | Copilot SDK + Express + Phaser | 9+ Agent 的复杂编排，Director 模式 |
| **llm-detective** (akankshacore) | 0 | Python | LangChain + Streamlit + Bedrock | 简单清晰，单 LLM 扮演所有角色 |
| **Clue-Board-Game** (nmadhire-agents) | — | Python | CrewAI + Gemini | 六 Agent 遵循桌游规则，Deterministic Notebook |
| **murder-mystery-mcp** (DigitalBoopLtd) | 0 | Python | MCP Server + OpenAI | Oracle 架构（真相层与玩家层分离） |
| **ai-murder-mystery-hackathon** (ironman5366) | — | Python/TS | Anthropic + React + Docker | 含 critique-revision 提示机制 |

---

## 二、重点项目深度分析

### 2.1 jubensha-ai (最直接参考)

**仓库**: https://github.com/JianWang97/jubensha-ai  
**Stars**: 124 | **技术栈**: Python 3.13+, FastAPI, LangChain, WebSocket, PostgreSQL, Next.js 15

```
backend/src/
├── agents/
│   ├── character_agent.py          # 核心角色 Agent（三层分离架构）
│   ├── character_agent_manager.py  # Agent 管理器（广播机制）
│   ├── character_identity.py       # 身份层 -> 稳定 system prompt
│   ├── character_memory.py         # 记忆层 -> working memory + personal log
│   ├── gm_agent.py                 # GM Agent -> 动态规划阶段流程
│   └── phase_director.py           # 阶段指令层 -> 无状态任务构建
├── core/
│   ├── game_engine.py              # 游戏引擎主模块
│   ├── evidence_manager.py         # 证据管理
│   ├── voting_manager.py           # 投票管理
│   ├── conversation_flow_controller.py # 对话流控制
│   └── websocket_server.py         # WebSocket 实时通信
└── services/
    ├── llm_service.py              # LLM 服务抽象
    ├── base_tts.py / tts_service.py # TTS 语音合成
    ├── image_generation_service.py # 文生图
    ├── script_editor_service.py    # AI 剧本编辑
    └── script_generation_service.py # AI 剧本生成
```

**核心架构模式 —— 三层分离 CharacterAgent**:

```
┌─────────────────────────────────────────────────┐
│              CharacterAgent                      │
│                                                   │
│  Layer 1 — identity (CharacterIdentity)           │
│    · 稳定 system prompt，全剧不变                  │
│    · 只包含"我是谁"（背景/秘密/性格）               │
│                                                   │
│  Layer 2 — memory (CharacterMemory)               │
│    · working_memory: 最近 N 条公开对话              │
│    · personal_log: 私有事件日志                     │
│    · suspicion_map: 对其他角色的怀疑度               │
│                                                   │
│  Layer 3 — director (PhaseDirector)               │
│    · 无状态，根据 phase 动态构建 user message       │
│    · 将"现在要做什么"与"我是谁"解耦                  │
└─────────────────────────────────────────────────┘
```

**GM Agent 动态规划**:
- 接收剧本数据（角色数、证据量、场景数）
- 优先用 LLM 生成阶段计划（JSON 格式输出阶段序列）
- 失败时回退到规则化默认计划
- 切换阶段时生成 GM 旁白公告

**游戏流程**:
1. 背景介绍 → 2. 自我介绍 → 3. 搜证(1~2轮) → 4. 调查 → 5. 讨论 → 6. 投票 → 7. 真相揭晓

**关键设计决策**:
- `asyncio` 异步架构，单进程 Event Loop 驱动
- LLM 服务单例共享，避免连接池膨胀
- 对话流控制器避免同一角色连续发言
- 搜证阶段用 `EvidenceManager` 按地点管理
- TTS 异步任务不阻塞游戏流程

---

### 2.2 PLAYER* (学术界参考)

**仓库**: https://github.com/alickzhu/PLAYER  
**论文**: arXiv:2404.17662

核心贡献：
1. **WellPlay 数据集**：中英双语，包含完整剧本杀剧本
2. **Sensor-based Agent Architecture**：Agent 通过传感器感知环境信息
3. 多人推理对话推理评估基准

**与文境的关系**：
- 其传感器架构可参考用于"验证 Agent"的设计
- WellPlay 数据集可作为评估基准
- 中文剧本杀流程设计值得借鉴

---

### 2.3 detective-agentic-mysteries (编排模式参考)

**仓库**: https://github.com/suus/detective-agentic-mysteries

**关键模式**：
```
┌─────────────────────────────────────────────────┐
│                  Express Server                  │
│              (Orchestration Layer)                │
│                                                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐│
│  │ NPC 1   │ │ NPC 2   │ │ NPC 3   │ │NPC ...  ││
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘│
│       └───────────┬┴───────────┘              │    │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Director │  │Forensics │  │ Narrator │       │
│  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────┘
```

**Agent 通信模式**：
1. **Tool-mediated**: Agent 通过工具修改共享状态，其他 Agent 通过工具读取
2. **onPostToolUse Hooks**: 工具调用后自动触发副作用（广播、情感传播）
3. **Server-orchestrated**: 服务端编排 Agent 间对话
4. **Fire-and-forget**: 异步广播（流言传播、玩家画像、矛盾检测）

**对文境的启示**：
- Director Agent 模式：类似文境中的"编剧 Agent"
- onPostToolUse 模式：Agent 行动后自动触发验证/广播
- 健康检查 + 自动恢复：生产级多 Agent 系统的必备能力

---

## 三、技术选型图谱

### 3.1 Agent 框架

| 方案 | 适用场景 | 代表项目 |
|------|----------|----------|
| **LangChain** | 灵活的 Chain 构建，丰富的生态 | llm-detective, jubensha-ai |
| **LangGraph** | 有状态图 workflow，复杂分支 | — |
| **CrewAI** | 多 Agent 编排，预设角色模式 | Clue-Board-Game |
| **AutoGen** | Microsoft 多 Agent 对话 | — |
| **自制 + Base LLM** | 最大灵活度，无框架 overhead | PLAYER*, detective-agentic |

**建议**：文境已确定使用 LangChain。推荐配合 **LangGraph** 处理阶段状态机（Stage1/Stage2/Stage3 的复杂状态转换）。

### 3.2 通信层

| 方案 | 优势 |
|------|------|
| **WebSocket** | 实时双向通信，标准选择 |
| **Server-Sent Events** | 单向流式推送，更轻量 |
| **gRPC** | 高性能内部通信，跨语言 |

**建议**：WebSocket（与 jubensha-ai 一致）用于前端实时同步。

### 3.3 记忆系统

| 层级 | 实现方案 | 用途 |
|------|----------|------|
| 短期记忆 | sliding window (deque) | 最近 N 轮对话 |
| 长期记忆 | 向量数据库 (Chroma/Pinecone) | 检索相关历史 |
| 结构化记忆 | 关系图 (Neo4j) | 角色关系、怀疑度 |
| 持久化记忆 | PostgreSQL | 游戏状态持久化 |

**建议**：初期使用 jubensha-ai 风格的双层记忆（working_memory + personal_log），后续引入向量数据库支持长期记忆检索。怀疑度用 `suspicion_map` 即可。

### 3.4 游戏阶段状态机

```
                    ┌──────────┐
                    │ Stage 1  │  剧本创建（Agent 生成剧本）
                    │ Script   │
                    │ Creation │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │ Stage 2  │  剧情还原（低自由度，按课文推进）
                    │ Plot     │
                    │ Reenact  │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │ Stage 3  │  剧情续写（高自由度，多 Agent 涌现）
                    │ Extended │
                    │ Writing  │
                    └──────────┘
```

**建议**：使用 LangGraph 的 StateGraph 实现阶段状态机，每个 Stage 是一个 Subgraph，内部包含多个 Phase Node。

---

## 四、与文境的差异分析

| 维度 | 现有项目（剧本杀） | 文境（课文演绎） |
|------|-------------------|-----------------|
| **剧本来源** | AI 随机生成 | 课文导入 + AI 补充 |
| **自由度** | 开放搜索推凶 | Stage2 低自由度还原 → Stage3 高自由度续写 |
| **目标** | 找出凶手 | 情景演绎 + 续写 |
| **玩家角色** | 侦探/嫌疑人 | 课文中任一角色 |
| **Agent 职责** | 扮演嫌疑人 | 编剧 + 角色 + 验证 |
| **验证需求** | 无 | 编剧产出需符合作品设定 |
| **知识来源** | 孤立剧本 | 课文 + 网络解读 + 教案 |

---

## 五、核心参考结论

1. **架构参考首选 jubensha-ai**：其三层 Agent 分离（identity/memory/director）、GM Agent 动态规划、WebSocket 实时同步、完整 Stage 流程，与文境需求最匹配。

2. **需要差异化的设计**：
   - **编剧 Agent**（文境独有）：需要素材收集 sub-agent + 交互设计 sub-agent
   - **验证 Agent**（文境独有）：验证剧本是否符合作品设定/风格/人设
   - **两阶段 Agent Group 切换**：Stage2（低自由度）vs Stage3（高自由度）可能需要不同配置的 Agent
   - **课文作为"剧本"**：剧本生成逻辑从 AI 自由创造变为基于课文的改编和补充

3. **关键取舍点**（已收敛，决议见 [`design/design_00_tech_decisions.md`](design/design_00_tech_decisions.md) D6–D13）：
   - 上下文窗口 vs RAG 记忆
   - 单 LLM 共享 vs 每 Agent 独立 LLM
   - 确定性阶段流 vs LLM 动态规划
   - Web 前端 (Next.js) vs 其他方案
