# 需求确认与技术栈选型 Brainstorm（文境 Wenjing）

## Goal

基于 `idea.md`、`design/*.md`、`research.md`、`feedback.md` 的既有内容（注：`idea.md`/`feedback.md` 已在本次收敛后删除，内容精炼至 design/*.md 与本 PRD），通过 brainstorm 收敛"文境"的整体需求、交互形式、框架与技术栈，产出可落地的 MVP 范围与架构决议，作为后续开发（design_03~05、实现）的输入。

## Background（已确认事实）

- **产品定位**：面向学生（中学生为主，小学高年级/高中生为辅）的语文课文情景演绎 + multi-agent 角色扮演平台。
- **价值目标**：吸引学生玩 + 锻炼语文素养/创新/应试能力（主要矛盾判断、人物形象分析等）。
- **三阶段流程**：
  - Stage1 剧本创建：导入课文 → 素材收集（背景/时代/人物/情节/主题）→ 剧情设计（场景序列/角色设定表）→ 验证 → 初始化角色。
  - Stage2 剧情还原：低自由度，按课文情节线性推进，Galgame 式选项为主。
  - Stage3 剧情续写：高自由度，沿用设定与角色做同人续写，玩家以原角色主视角。
- **Agent 体系**（design_01）：编剧 Agent（素材收集/剧情设计/交互设计 3 sub-agent）+ 验证 Agent（五维审核）+ 角色 Agent（identity/memory/director 三层）+ Player Proxy；LLM Service 单例共享，每轮每 Agent 一次 LLM。
- **交互模型**（design_02）：三模式动态切换 A(选项)/B(自由输入)/C(选项+fallback)；WebSocket JSON 消息协议（后→前 5 种、前→后 3 种）；流式输出。
- **游戏引擎**（design_03）：asyncio 单进程事件循环；状态机；7 步 phase cycle；事件溯源 + checkpoint + 回溯。
- **MVP 范围**（design.md §6）已大体界定；TTS/ASR/图片生成仅留接口。
- **用户反馈**（原 feedback.md，已删除）：infra 已有云服务器；关键在游戏形式与实现逻辑；重点关注交互产物下发与 Stage3 自由互动形式。

## Key Decisions（D1–D15，均已收敛）

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
| D15 | 局外功能 | **MVP 含回溯(≤100步)+会话存档/恢复**；剧本分享与复盘 defer |

## Requirements

### R1 游戏流程
- R1.1 支持三阶段流程：Stage1 剧本创建（自动）→ Stage2 剧情还原 → Stage3 剧情续写。
- R1.2 Stage2 按"关键情节必须还原，细节可自由"标准推进；到达课文结局后经玩家确认进入 Stage3。
- R1.3 Stage3 目标导向自然收敛：每次续写设小目标，达成后询问玩家继续/结束。

### R2 Agent 体系
- R2.1 编剧 Agent 含素材收集/剧情设计/交互设计 3 sub-agent，输出剧本与剧情推进。
- R2.2 交互设计 sub-agent 采用"方向确认 + 行为选项两段式"（D5），向角色 Agent 下发当前矛盾/关键处境，收集其行为提议并包装为玩家选项。
- R2.3 验证 Agent 五维审核（设定/风格/人设/逻辑/交互质量），驳回重试 2 次（D4），LLM 失败降级。
- R2.4 角色 Agent 三层分离（identity/memory/director），记忆含 working_memory+personal_log+relationship_map+plot_context，MVP 无向量库（D8）。
- R2.5 LLM Service 单例共享、可配置 provider（D7），每轮每 Agent 一次 LLM 调用。

### R3 交互系统
- R3.1 三种交互模式动态切换：A 选项 / B 自由输入 / C 选项+fallback。
- R3.2 WebSocket 实时通信 + 流式输出，消息协议按 design_02 定义。
- R3.3 前端 Next.js，含叙事面板/输入区域/角色面板/回溯控制栏。

### R4 游戏引擎
- R4.1 asyncio 单进程事件循环 + LangGraph 状态机（D6/D13），7 步 phase cycle 编排。
- R4.2 事件溯源 + checkpoint（每 20 事件）持久化到 PostgreSQL（D10/D11）。
- R4.3 回溯 ≤100 步（Stage2 类进度条、Stage3 类 revert）；会话存档/恢复（D15）。
- R4.4 后端 FastAPI，REST + WebSocket（D12）。

### R5 局外能力
- R5.1 MVP 提供回溯与会话存档/恢复。
- R5.2 MVP 不提供剧本分享/社区、复盘总结、TTS/ASR/图片生成（仅留接口）。

## Out of Scope（MVP）

- 剧本编辑器
- 角色切换/多人联机
- TTS/ASR/图片生成（仅留接口）
- 多结局分支树、作品市场/分享社区
- RAG/向量库长期记忆、角色关系图存储（Neo4j）
- 复盘总结（教育学习总结）
- 难度分级自适应

## Acceptance Criteria

- [ ] A1 决策清单 D1..D15 全部收敛并记录决议，无阻塞性未决问题
- [ ] A2 Requirements R1–R5 覆盖产品定位下的核心功能，且 MVP 范围（In/Out of Scope）明确
- [ ] A3 技术栈决议（D6–D13）可落地：LangChain+LangGraph / FastAPI / Next.js / PostgreSQL / WebSocket
- [ ] A4 后续设计文档（design_03~05 及实现）可直接引用本 PRD 作为需求输入

## Notes

- 本任务为规划类（brainstorm），产出为决议文档，不直接写业务代码。
- 原 feedback.md 中 Feedback02 为空，仅 Feedback01 有内容。
- 待决议项如"验证五维评分的阈值""checkpoint 间隔""工作记忆窗口大小"等实现级参数留给 design_03 及实现阶段确定。
