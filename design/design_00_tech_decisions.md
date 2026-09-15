# 文境 (Wenjing) — 技术设计决议（Brainstorm 输出）

> 本文件汇总 brainstorm 收敛后的技术架构决议（D1–D15）与需求基线（R1–R5），供模块设计与实现引用。
> 功能设计（核心概念、Agent 体系、交互模型、MVP 范围）详见 [`design.md`](design.md)（主索引）及五个子模块
> （[01 Agent 架构](design_01_agent_architecture.md) / [02 交互系统](design_02_interaction_system.md) /
> [03 游戏引擎](design_03_game_engine.md) / [04 数据持久化](design_04_data_persistence.md) /
> [05 前端架构](design_05_frontend_architecture.md)）。

## 架构边界

```
Frontend (Next.js + WebSocket client)
    │  REST + WebSocket (JSON)
    ▼
Backend (FastAPI, 单进程 asyncio)
    ├── Game Engine (LangGraph 状态机 + 8 步 phase cycle + 事件溯源)
    │     ├── Screenwriter Agent (LangChain; 素材收集/剧情设计/交互设计 sub-agent)
    │     ├── Verifier Agent (五维审核, 驳回重试 2 次, 降级)
    │     └── Character Agent Cluster (identity/memory/director 三层)
    └── Shared Services: LLM Service(单例, provider 可配置) | EventStore+Checkpoint | PostgreSQL
```

## 需求基线（R1–R5）

### R1 游戏流程
- R1.1 三阶段流程：Stage1 剧本创建（自动）→ Stage2 剧情还原 → Stage3 剧情续写。
- R1.2 Stage2 按"关键情节必须还原，细节可自由"推进；到达课文结局后经玩家确认进入 Stage3。
- R1.3 Stage3 目标导向自然收敛：每次续写设小目标，达成后询问玩家继续/结束。

### R2 Agent 体系
- R2.1 编剧 Agent 含素材收集/剧情设计/交互设计 3 sub-agent，输出剧本与剧情推进。
- R2.2 交互设计 sub-agent 采用"方向确认 + 行为选项两段式"（D5）。
- R2.3 验证 Agent 五维审核（设定/风格/人设/逻辑/交互质量），驳回重试 2 次（D4），LLM 失败降级。
- R2.4 角色 Agent 三层分离（identity/memory/director），MVP 无向量库。
- R2.5 LLM Service 单例共享、provider 可配置（D7），每轮每 Agent 一次 LLM 调用。

### R3 交互系统
- R3.1 三种交互模式动态切换 A（选项）/ B（自由输入）/ C（选项+fallback）。
- R3.2 WebSocket 实时通信 + 流式输出，消息协议见 `design_02`。
- R3.3 前端 Next.js，含叙事面板/输入区域/角色面板/回溯控制栏。

### R4 游戏引擎
- R4.1 asyncio 单进程事件循环 + LangGraph 状态机（D6/D13），8 步 phase cycle 编排。
- R4.2 事件溯源 + checkpoint（每 20 事件）持久化到 PostgreSQL（D10/D11）。
- R4.3 回溯 ≤100 步；会话存档/恢复（D15）。
- R4.4 后端 FastAPI，REST + WebSocket（D12）。

### R5 局外能力
- R5.1 MVP 提供回溯与会话存档/恢复。
- R5.2 MVP 不提供公开作品社区、复盘总结、TTS/ASR/图片生成（仅留接口）。
  （2026-09-15 ADR-0002 修订：教师剧本库 + 显式发布 + 公网可见已纳入范围，
  不再等同「不做分享」。）

## 关键技术决议（D1–D15）

> ⚠️ **2026-09-15 修订（ADR-0002）**：账号体系、教师/学生 RBAC、剧本复用与
> 「创作/游玩分离」已纳入范围。D13「单进程 asyncio、不引入 Redis/队列」依旧成立
> （backend 保持单 worker），但「单用户场景」假设已被取代；D15 的「剧本分享 defer」
> 由教师剧本库 + 显式发布取代。数据模型落点变更见 `design_04`（scripts/sessions/
> material 归属）与 ADR-0002。

| ID | 决策点 | 决议 |
|----|--------|------|
| D1 | 产品定位取向 | **教育主导，娱乐为辅**：验证严格，交互优先教学价值，可显示能力标签 |
| D2 | Stage2 还原标准 | **关键情节必须还原，细节可自由**：人物关系/主要矛盾/关键事件顺序严格，次要动作/对话可演绎 |
| D3 | Stage3 续写轮次 | **目标导向的自然收敛**：为每次续写设小目标，达成后询问继续/结束 |
| D4 | 验证驳回重试 | **2 次**，仍失败则记录并降级 |
| D5 | 交互产物下发方式 | **方向确认 + 行为选项两段式**：编剧确认当前矛盾/关键处境→角色 Agent 提具体行为→玩家以选项为主 |
| D6 | Agent 框架 | **LangChain + LangGraph**：LangGraph 管状态机与 sub-agent 编排，Agent 内部用 LangChain |
| D7 | LLM 模式 | **单例共享 + 可配置 provider**（OpenAI/DeepSeek/Qwen 等经配置切换） |
| D8 | 记忆系统 | **MVP 无向量库，双层记忆起步**（working_memory+personal_log+plot_context+relationship_map），RAG defer |
| D9 | 前端框架 | **Next.js**（zustand/react-markdown/react-use-websocket） |
| D10 | 数据库 | **PostgreSQL**（JSONB 存事件溯源 payload） |
| D11 | 状态持久化 | **事件溯源 + checkpoint 快照**（每 20 事件） |
| D12 | API 风格 | **REST + WebSocket**（MCP 留作未来加分项） |
| D13 | 部署/并发 | **单进程 asyncio + 事件循环**（FastAPI，不引入 Redis/队列） |
| D14 | Stage2→Stage3 切换 | **引擎自动判断 + 玩家确认** |
| D15 | 局外功能 | **MVP 含回溯(≤100 步)+会话存档/恢复**；剧本分享与复盘 defer |

> 各决议在子模块中的落点：D1–D5 见 `design_01/02`；D6/D13 见 `design_03`；D10/D11/D15 见 `design_04`；D9/D12 见 `design_05`。
> 实现级参数（验证五维阈值、checkpoint 间隔、工作记忆窗口、提案重试次数等）见 `design_03` §6 `EngineConfig`。

## 编排数据流（方向确认两段式，D5）

```
编剧/交互设计确认「当前矛盾/关键处境」(方向)
    → 广播给角色 Agent
    → 角色 Agent 按人设提出具体行为提议（并行, 每轮一次 LLM）
    → 验证 Agent 审核（并行, 驳回重试 2 次）
    → 交互设计 sub-agent 筛选打包为玩家选项/自由输入（模式 A/B/C）
    → 玩家操作 → 引擎记录事件 → 角色反应 → 剧情推进 → Stage 检测
```

## 兼容性与迁移

- 与 `design_01/02/03` 保持一致，本决议只收敛未决项（D1–D15），不改动既有协议与类结构。
- 新增决议不破坏 `design_03` 的 `EngineConfig` 默认值（checkpoint=20, max_rollback=100, retries=2）。

## 权衡说明

- LangGraph 带来的抽象 vs 编排便利：状态机/分支/并行由框架托管，Agent 内部保持轻量。
- 无向量库：单课文单会话场景下双层记忆 + plot_context 足够；Stage3 长期续写时再引入 RAG。
- 单进程 asyncio：实现最简可靠；多人/社区 defer 后再评估消息队列。
  （2026-09-15 ADR-0002：已引入多用户账号；生成任务不落库，故 backend 维持
  单 worker/单实例；「多副本扩展」仍是 defer 触发点。）