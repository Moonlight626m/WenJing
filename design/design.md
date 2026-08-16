# 文境 (Wenjing) — 功能设计

> 基于调研结论和 feedback 讨论，汇总游戏形式、交互逻辑、Agent 职责。
> 本文档作为主索引，各子模块详见对应文件。

---

## 文档索引

| 文件 | 内容 | 状态 |
|------|------|------|
| `design.md` | **当前** — 核心概念、全景、MVP Scope、技术栈决议、待讨论事项 | 稳定 |
| `design_01_agent_architecture.md` | Agent 体系：编剧/验证/角色 Agent 三层分离设计 | 稳定 |
| `design_02_interaction_system.md` | 交互系统：消息协议、前端界面、交互流程、WebSocket 管理 | 稳定 |
| `design_03_game_engine.md` | 游戏引擎：状态机、事件循环、Agent 编排、回溯实现 | 稳定 |
| `design_04_data_persistence.md` | 数据持久化：事件溯源、checkpoint、PostgreSQL、会话存档 | 稳定 |
| `design_05_frontend_architecture.md` | 前端架构：Next.js、状态管理、WebSocket 消息流 | 稳定 |

> 技术选型决议（D1–D15）见 `.trellis/tasks/08-16-brainstorm-requirements-techstack/prd.md`。

---

## 一、核心概念

| 概念 | 说明 |
|------|------|
| **课文** | 输入素材，语文课文（戏剧/小说/叙事文），作为剧本改编的基底 |
| **剧本** | 编剧 Agent 基于课文生成的完整可玩剧本（含角色设定、场景、事件序列） |
| **剧情还原 (Stage2)** | 低自由度阶段，按课文原情节推进，做 Galgame 式选项互动 |
| **剧情续写 (Stage3)** | 高自由度阶段，沿用课文设定和角色，做同人续写 |
| **玩家** | 扮演课文中某一主角，其他角色由 AI Agent 扮演 |

---

## 二、架构全景

```
┌──────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
│  叙事面板  |  输入区域  |  角色面板  |  回溯控制栏            │
└──────────────────────────┬───────────────────────────────────┘
                           │ WebSocket (JSON)
┌──────────────────────────▼───────────────────────────────────┐
│                    Game Engine (编排层)                       │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐   │
│  │  编剧 Agent  │  │  验证 Agent  │  │ 角色 Agent Cluster │   │
│  │  · 素材收集  │  │  · 五维审核  │  │  · identity 层    │   │
│  │  · 剧情设计  │  │  · 驳回重试  │  │  · memory 层      │   │
│  │  · 交互设计  │  │  · 降级策略  │  │  · director 层    │   │
│  └─────────────┘  └─────────────┘  └────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────┐        │
│  │              Shared Services Layer                │        │
│  │   LLM Service | Event Store | RAG (后续)          │        │
│  └──────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────┘
```

**设计原则**：
- Agent 间不直接通信，通过 Game Engine 事件总线中转
- 所有 Agent 共享 LLM Service 单例
- 每轮对话每个 Agent 只调一次 LLM
- 验证 Agent 异步化，不阻塞主流程

---

## 三、Agent 全景

| Agent | 职责 | Sub-agents | 详见 |
|-------|------|-----------|------|
| **编剧 Agent** | 剧本创建 + 剧情推进 | 素材收集、剧情设计、交互设计 | `design_01_agent_architecture.md` |
| **验证 Agent** | 质量门禁，五维审核 | — | 同上 |
| **角色 Agent** | 角色扮演，三层分离 | identity/memory/director | 同上 |
| **Player Proxy** | 封装玩家输入为结构化消息 | — | 同上 |

---

## 四、交互模型

三种交互模式动态切换（详见 `design_02_interaction_system.md`）：

| 模式 | 名称 | 驱动方 | 适用场景 |
|------|------|--------|----------|
| A | Galgame 选项 | Agent 驱动 | 角色提议丰富，剧情可控时 |
| B | 自由输入 | 玩家驱动 | 僵局时，放权给玩家 |
| C | 混合模式 | 动态切换 | 正常 Stage3 流程 |

前后端通信：WebSocket，8 种消息类型（后→前 5 + 前→后 3），流式输出。

---

## 五、阶段流程

```
Stage 1: 剧本创建（系统自动，玩家不参与）
    │  课文导入 → 素材收集 → 剧本生成 → 验证 → 初始化
    │
    ▼
Stage 2: 剧情还原（低自由度，线性推进）
    │  按课文情节 → 角色提议 → 验证 → 交互 → 推进
    │  （直到到达课文结局）
    │
    ▼
Stage 3: 剧情续写（高自由度，模式 A/B/C 切换）
    │  设定内自由发挥 → 动态交互 → 直到玩家退出
```

---

## 六、MVP Scope

### MVP 包含

| 模块 | 说明 |
|------|------|
| Stage 1 | 剧本创建（AI 自动生成 + 验证，无编辑器） |
| Stage 2 | 剧情还原（线性推进，模式 A/B 交替） |
| Stage 3 | 简单续写（有限轮次，1-2 个场景分支） |
| 交互 | Web 前端 + WebSocket，打字 input，流式 output |
| 玩家 | 固定扮演一个主角 |
| 回溯 | 简单快照回退（≤100 步） |
| Agent | 编剧 Agent（含子 Agent）、验证 Agent、角色 Agent × N |
| TTS/ASR | 仅留接口，不做实现 |

### MVP 不包含

| 模块 | 原因 |
|------|------|
| 剧本编辑器 | 复杂度高，后续迭代 |
| 角色切换 | 复杂度高，影响沉浸感 |
| TTS/ASR 语音 | 有接口即可，后续加分项 |
| 图片生成 | 同理，留接口 |
| 多结局分支树 | 远超 MVP 范围 |
| 多人联机 | 单玩家 + 多 Agent |
| 作品市场/分享社区 | dev 阶段不考虑 |
| 难度分级自适应 | 先做默认难度 |

---

## 七、技术栈决议

> 来自需求收敛（brainstorm，D6–D13），作为实现选型基线。

| 维度 | 决议 |
|------|------|
| Agent 框架 | LangChain + LangGraph（LangGraph 管 Stage/phase 状态机与 sub-agent 编排；Agent 内部用 LangChain） |
| 后端 | FastAPI，REST + WebSocket，单进程 asyncio 事件循环，无 Redis/消息队列 |
| LLM | LLM Service 单例共享 + 信号量限并发 + provider 配置切换（OpenAI/DeepSeek/Qwen…） |
| 前端 | Next.js + zustand + react-markdown + react-use-websocket |
| 数据库 | PostgreSQL（事件溯源 payload 用 JSONB） |
| 状态持久化 | 事件溯源 + checkpoint 快照（每 20 事件），回溯从最近快照重放（≤100 步） |
| 记忆系统 | 双层记忆起步（working_memory + personal_log + plot_context + relationship_map），MVP 无向量库 |

## 八、待讨论事项（已收敛）

> 经需求收敛（D1–D15）后，以下产品级事项均已决议，详见 `.trellis/tasks/08-16-brainstorm-requirements-techstack/prd.md`。

| 事项 | 决议 |
|------|------|
| 产品定位 | 教育主导，娱乐为辅 |
| Stage2 课文情节还原标准 | 关键情节必须还原，细节可自由 |
| Stage3 续写轮次 | 目标导向的自然收敛 |
| 验证 Agent 驳回重试次数 | 2 次 |
| 交互产物下发方式 | 方向确认 + 行为选项两段式 |
| Stage2→Stage3 切换 | 引擎自动判断 + 玩家确认 |
| 局外功能范围 | MVP 含回溯(≤100步) + 会话存档/恢复；复盘 defer |

> 实现级参数（验证维度阈值、工作记忆窗口、checkpoint 间隔等）在实现阶段确定。