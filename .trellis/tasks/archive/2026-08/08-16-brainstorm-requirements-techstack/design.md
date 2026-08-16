# 技术设计决议（Brainstorm 输出）

> 本文件汇总 brainstorm 收敛后的技术架构决议，供后续 design_03~05 与实现引用。
> 需求侧详见同目录 `prd.md`（D1–D15）。

## 架构边界

```
Frontend (Next.js + WebSocket client)
    │  REST + WebSocket (JSON)
    ▼
Backend (FastAPI, 单进程 asyncio)
    ├── Game Engine (LangGraph 状态机 + 7步 phase cycle + 事件溯源)
    │     ├── Screenwriter Agent (LangChain; 素材收集/剧情设计/交互设计 sub-agent)
    │     ├── Verifier Agent (五维审核, 驳回重试2次, 降级)
    │     └── Character Agent Cluster (identity/memory/director 三层)
    └── Shared Services: LLM Service(单例, provider 可配置) | EventStore+Checkpoint | PostgreSQL
```

## 关键技术决议

| 维度 | 决议 |
|------|------|
| Agent 框架 | LangChain + LangGraph（LangGraph 管 Stage/phase 状态机与 sub-agent 编排；Agent 内部逻辑用 LangChain） |
| LLM | LLM Service 单例共享 + 信号量限并发 + provider 配置切换（OpenAI/DeepSeek/Qwen…） |
| 后端 | FastAPI，REST + WebSocket，单进程 asyncio 事件循环，无 Redis/消息队列 |
| 前端 | Next.js + zustand + react-markdown + react-use-websocket |
| 数据库 | PostgreSQL（事件溯源 payload 用 JSONB） |
| 持久化 | 事件溯源 + checkpoint（每 20 事件快照），回溯从最近快照重放（≤100 步） |
| 记忆 | working_memory(50) + personal_log + relationship_map + plot_context；MVP 无向量库 |

## 编排数据流（方向确认两段式，D5）

```
编剧/交互设计确认「当前矛盾/关键处境」(方向)
    → 广播给角色 Agent
    → 角色 Agent 按人设提出具体行为提议（并行, 每轮一次 LLM）
    → 验证 Agent 审核（并行, 驳回重试2次）
    → 交互设计 sub-agent 筛选打包为玩家选项/自由输入（模式 A/B/C）
    → 玩家操作 → 引擎记录事件 → 角色反应 → 剧情推进 → Stage 检测
```

## 兼容性与迁移

- 与现有 design_01/02/03 保持一致，本 PRD 只收敛未决项（D1–D15），不改动既有协议与类结构。
- 新增决策不破坏 design_03 的 EngineConfig 默认值（checkpoint=20, max_rollback=100, retries=2）。

## 权衡说明

- LangGraph 带来的抽象 vs 编排便利：状态机/分支/并行由框架托管，Agent 内部保持轻量。
- 无向量库：单课文单会话场景下双层记忆 + plot_context 足够；Stage3 长期续写时再引入 RAG。
- 单进程 asyncio：单用户场景最简单可靠；多人/社区 defer 后再评估消息队列。
