# 文境 (Wenjing) — 模块设计：MVP 实现规划

> 本文档把 MVP 范围（`design.md` §六）与各模块设计（01–05）落到**可执行的分阶段实现步骤**，
> 并映射到当前骨架代码。作为从"scaffold"走向"可玩 MVP"的实施路线图与验收依据。
>
> 相关：需求基线 R1–R5（`design_00`）、Agent 体系（`design_01`）、交互协议（`design_02`）、
> 游戏引擎（`design_03`）、持久化（`design_04`）、前端架构（`design_05`）。

> **⚠️ 实施收敛（经由 grill 确定，覆盖原文竖切方案）**
> 后续实现改为**后端优先横切**路线，与原文"竖切"顺序不同，落地为：
> - 先纯后端把 **引擎 + Agent 编排 + 回溯 + 三阶段** 在内存里用 pytest 跑通，**前端整块后置**；
> - **砍掉 LangGraph**，状态机用纯枚举（`GameStateMachine`），8 步 phase cycle 纯 asyncio；
> - 剧本 **mock 最小集**（1 主角 + 2 配角 + 3 beat），**不测试 Stage1 剧本生成链路**；
> - **PostgreSQL 落库后置**，MVP 引擎阶段用内存事件流（EventStore）；
> - LLM 抽象为 `LLMService`，测试注入 `FakeLLMService`（确定性）；
> - 玩家操作由 pytest 注入的**脚本化决策回调**驱动，不做真实交互/CLI；
> - 引入横切 **errx 错误体系**（仿 Go errorx）与 **log/trace 日志**（标准库 logging，事件即日志）。
>
> **已实现**（本轮）：`app/errx/`、`core/logging_config`、`core/state_machine`、`core/event`、
> `core/game_engine`、`core/types`、`core/engine_config`、`agents/{llm_service,character,screenwriter,verifier}`；
> 测试 `tests/{conftest,test_errx,test_engine}.py` 全部通过（18 例）。
>
> **已实现**（本轮增量，非核心但使日常开发更省力）：
> - **多 provider LLM**：`agents/model_config.py` 抽象 `ModelConfig` + `ModelServiceFactory`，
>   已登记 OpenAI 与 DeepSeek（共用 OpenAI-compatible，仅 base_url/default_model 不同），
>   `Settings.llm_model_config()` 按 `WENJING_LLM_PROVIDER` 分发；新增错误码
>   `CFG_UNKNOWN_PROVIDER` / `LLM_UNKNOWN_MODEL`；测试 `tests/test_llm_config.py`（6 例）。
> - **DB 集成**：`app/models/` 落 design_04 的 `sessions`/`materials`/`scripts`/`events`/`snapshots`
>   五表 ORM；`db/event_store.py` 的 `PersistentEventStore`（内存 + 异步落库 flush/restore/truncate）；
>   `db/factory.py` 的 `init_db()` / `build_engine_with_db()`；引擎新增可选 `event_store`/`on_flush`
>   挂接点（默认不启用，核心链路零改动）。DB 集成测试 `tests/test_db_event_store.py`
>   在 Postgres 未连接时自动 skip（`make test` 无 DB 亦绿）。

---

## 一、MVP 定义回顾

### 1.1 一句话目标

> 玩家导入一篇课文 → 系统 A自动生成剧本 → 玩家扮演一个主角与他人 Agent（编剧/角色）按课文剧情演绎还原（Stage2）
> → 到达课文结局后进入同人续写（Stage3）→ 全程支持 ≤100 步回溯与会话存档/恢复。

### 1.2 MVP 边界（来自 `design.md` §六）

| 纳入 | 排除（后续迭代） |
|------|-----------------|
| Stage1 剧本自动创建+验证 | 剧本编辑器 |
| Stage2 剧情还原（模式 A/B 交替） | 角色切换 |
| Stage3 简单续写（有限轮次） | TTS/ASR、图片生成 |
| Web 前端 + WebSocket 流式交互 | 多结局分支树 |
| 固定扮演一个主角 | 多人联机 |
| 简单快照回溯（≤100 步） | 作品市场/分享社区 |
| 编剧/验证/角色 Agent | 难度分级自适应 |
| TTS/ASR 仅留接口 | — |

### 1.3 完成判据（Definition of Done）

当满足以下**全部**时可宣布 MVP 达成：

1. 导入课文后自动产出剧本并通过验证（Stage1 完成）。
2. 玩家选定主角，进入 Stage2，按"关键情节必须还原"推进至课文结局（D14：引擎自动判断 + 玩家确认）。
3. Stage3 续写目标导向自然收敛，可正常进入/退出。
4. 三种交互模式（A/B/C）可动态切换并正确渲染。
5. WebSocket 实时消息 + 流式输出端到端可用；断线可自动重连恢复。
6. 事件溯源 + checkpoint 落库，回溯 ≤100 步可用，会话可存档/恢复。
7. `make test` 与 `make lint` 全部通过。

---

## 二、实现阶段总览

按**竖切（vertical slice）**原则推进：每个阶段都打通一条从"可操作"到"可验证"的最小通路，而不是先完成某一大层。

```
Phase 0  数据与地基        模型/迁移/会话 → 每阶段的地基
Phase 1  会话与消息通道     创建会话 → WS 回显 → 前端消息流渲染（打通前后端）
Phase 2  Stage1 剧本链路    课文导入 → 素材收集 → 剧本生成 → 验证 → 角色初始化
Phase 3  Stage2 还原主循环  8 步 phase cycle + 模式 A/B
Phase 4  Stage3 续写与回溯  高自由度 + 快照回溯 + 存档/恢复
```

> 每阶段完成即可回归 `make test`；阶段间有黑盒验收点（见每阶段"验收"）。

---

## 三、Phase 0 — 数据与地基

**目标**：把 `design_04` 的表结构落到 Alembic 迁移与 SQLAlchemy 模型，作为 Stage1+ 的存储基础。
**对应骨架**：`backend/alembic/versions/0001_initial.py`（当前为空迁移）、`backend/app/db/`、`backend/app/config.py`。

| 任务 | 落点 | 参考 |
|------|------|------|
| T0.1 定义 ORM 模型：`Session`、`Script`、`Material`、`GameEvent`、`Snapshot` | `backend/app/models/`（新建） | `design_04` §二/三/四 |
| T0.2 生成真实迁移替换空迁移 | `backend/alembic/versions/` | `design_04` §七 |
| T0.3 接通 async session 工厂与依赖注入 | `backend/app/db/session.py` | — |
| T0.4 会话状态（`sessions.current_stage`）与引擎状态机映射 | `backend/app/core/` | `design_03` §二 |

**验收**：`make db-up && make migrate` 建表成功；`GET /health` 依赖 DB 可返回 ok。

---

## 四、Phase 1 — 会话与消息通道（前后端竖切）

**目标**：打通"创建会话 → 建立 WS → 后端推消息 → 前端渲染"的最小回路，把 `design_02` 消息协议落到代码。
**对应骨架**：`backend/app/api/routes.py`（`/api/sessions`、`/ws` 占位）、`frontend/src/lib/{api,ws}.ts`、`frontend/src/stores/{game,ws}Store.ts`。

| 任务 | 落点 | 参考 |
|------|------|------|
| T1.1 创建会话接真实 DB（生成 UUID session_id） | `POST /api/sessions` | `design_05` §六 |
| T1.2 新增 `GET /api/sessions/{id}` 状态查询 | 新端点 | `design_05` §六 |
| T1.3 WS 端点按 `session_id` 创建/恢复会话，回 `SessionInitMessage` | `/ws?session_id=` | `design_02` §5.1 |
| T1.4 后端消息 schema 从泛型 `dict` 收敛为类型化 `content`（narrative/speech/interaction 等五类） | `backend/app/schemas/messages.py` | `design_02` §2.2 |
| T1.5 前端 WS 客户端：连接/心跳/指数退避重连 | `frontend/src/lib/ws.ts` | `design_05` §4 |
| T1.6 前端消息分发：`wsStore` → `gameStore` → 叙事面板渲染 | `frontend/src/stores/*`、`components/narrative/` | `design_05` §3 |

**验收**：前端创建会话进入游戏页，能收到并渲染后端推来的 narrative/system 消息；断网重连后补发未确认消息。

---

## 五、Phase 2 — Stage1 剧本链路

**目标**：用 LLM 打通"课文 → 素材收集 → 剧本 → 验证 → 角色初始化"，产出 `design_01` 的 `ScriptOutput`。
**对应骨架**：`backend/app/agents/`（当前为空包）、`backend/app/core/game_engine.py`（待建）。

| 任务 | 落点 | 参考 |
|------|------|------|
| T2.1 LLM Service 单例（provider 可配置 + 信号量限并发） | `backend/app/agents/llm_service.py` | `design_01` §5 / `design_00` D7 |
| T2.2 素材收集 sub-agent（输入课文 → `MaterialCollectionOutput`） | 编剧 Agent 内 | `design_01` §2.3 |
| T2.3 剧情设计 sub-agent（→ `ScriptOutput`，JSON 结构化输出） | 编剧 Agent 内 | `design_01` §2.4 |
| T2.4 验证 Agent 五维审核剧本（驳回重试 2 次 + 降级） | `backend/app/agents/verifier.py` | `design_01` §3 |
| T2.5 角色 Agent 三层骨架（identity/memory/director）初始化 | `backend/app/agents/character.py` | `design_01` §4 |
| T2.6 状态机 Stage1 流程编排（`GameEngine._run_stage1`） | `backend/app/core/` | `design_03` §3.1 |

**验收**：导入《背影》等教材课文，日志/测试可见自动产出 `ScriptOutput`（含场景序列、角色设定表）并通过验证；角色 Agent 完成初始化。

---

## 六、Phase 3 — Stage2 还原主循环

**目标**：跑通 `design_03` §3.3 的 8 步 phase cycle，实现"关键情节还原 + 模式 A/B 交替"。
**对应骨架**：`backend/app/core/game_engine.py`（`_execute_phase_cycle`）。

| 任务 | 落点 | 参考 |
|------|------|------|
| T3.1 状态机 & InteractionPhase 枚举落地 | `backend/app/core/state_machine.py` | `design_03` §2 |
| T3.2 事件循环 8 步编排（advance→direction→proposal→verify→interaction→player→reaction→stage_check） | `GameEngine._execute_phase_cycle` | `design_03` §3.3 |
| T3.3 并行 Agent 调度器（信号量 + gather） | `AgentScheduler` | `design_03` §5 |
| T3.4 角色提议并行收集 + 验证驳回重试（≤2 次） | `_collect_character_proposals` / `_verify_proposals` | `design_03` §3.4 |
| T3.5 交互设计器：模式决策（A/B/C 规则）+ 交互点生成 | `InteractionDesigner` | `design_01` §2.5 |
| T3.6 前端三模式输入组件（Options / FreeInput + fallback） | `components/interaction/` | `design_02` §3.3 |
| T3.7 Stage2→Complete 检测 + 玩家确认进 Stage3 | `_check_stage_completion` | `design_00` D14 |

**验收**：Stage2 中玩家可通过选项/自由输入与角色互动，剧情按关键情节推进到课文结局；选项锻炼能力标签正确展示。

---

## 七、Phase 4 — Stage3 续写与回溯/存档

**目标**：高自由度续写 + 快照回溯 + 会话存档/恢复，收拢 MVP 全部局外能力。
**对应骨架**：`backend/app/core/`、`backend/app/db/`。

| 任务 | 落点 | 参考 |
|------|------|------|
| T4.1 Stage3 续写循环（目标导向收敛，模式 C 为主） | `GameEngine._run_stage3` | `design_03` §3.2 |
| T4.2 事件溯源落库（`GameEvent` → `events` 表） | EventStore 持久化 | `design_04` §2 |
| T4.3 checkpoint 快照（每 20 事件） | `CheckpointManager` | `design_04` §3 |
| T4.4 回溯执行（最近快照 + 重放 + 截断，≤100 步） | `_execute_rollback` | `design_03` §4.3 |
| T4.5 存档/恢复 REST（`POST save` / `load`） | 新端点 | `design_05` §六 |
| T4.6 前端回溯控制栏 + 存档按钮 | `components/layout/ControlBar.tsx`/Header | `design_02` §3.4 |

**验收**：Stage3 可自由续写并自然结束；回溯 ≤100 步正确回退且重做新选择可截断；会话保存后重连可恢复到断点。

---

## 八、任务与设计/骨架映射速查

| 实现产物 | 来源设计 | 当前骨架占位 |
|----------|----------|--------------|
| `GameEngine` | `design_03` | `app/core/game_engine.py`（已实现） |
| 编剧/验证/角色 Agent | `design_01` | `app/agents/`（已实现） |
| LLM Service | `design_01` §5 / D7 | `app/agents/llm_service.py`（接口 + 生产预留）；`model_config.py` 多 provider（OpenAI/DeepSeek，已实现） |
| 状态机 | `design_03` §2 | `app/core/state_machine.py`（枚举，砍 LangGraph） |
| 事件存储 | `design_03` §4 | `app/core/event.py`（内存，事件即日志） |
| 错误体系 | —（仿 Go errorx） | `app/errx/`（已实现） |
| 日志 | — | `app/core/logging_config.py`（已实现） |
| 消息类型化 schema | `design_02` §2.2 | `app/schemas/messages.py`（泛型 dict） |
| WS 会话/回显 | `design_02` §5 | `app/api/routes.py`（占位，前端后置） |
| REST 会话端点 | `design_05` §六 | `POST /api/sessions` / `GET /api/sessions/{id}` |
| 前端 WS/消息流 | `design_05` §3–4 | `frontend/src/lib/ws.ts`、`stores/*`（后置） |
| 前端组件 | `design_05` §5、`design_02` §3 | `frontend/src/`（后置） |
| 数据库迁移 | `design_04` §七 | `alembic/versions/0001_initial.py`（空迁移）；ORM 模型 `app/models/`、`db/event_store.py`、`db/factory.py` 已实现（落库后置但存储层就绪） |
| EngineConfig | `design_03` §6 | `app/core/engine_config.py`（已实现） |

---

## 九、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 结构化输出不稳定（JSON parse 失败） | Stage1 受阻 | 多 provider 配置 + 降级 + 结构化调参；
      素材/剧本 schema 用 Pydantic 强校验 + 重试 |
| 验证 Agent 误判导致反复驳回/僵局 | Stage2 卡死 | 降级为规则验证；僵局自动切模式 B 放权给玩家（D4/D5） |
| 多角色并行 LLM 超时/限流 | 主循环变慢 | `AgentScheduler` 信号量 + 超时；每轮每 Agent 一次 LLM（同步原则） |
| 事件/记忆状态与 DB 快照不一致 | 回溯异常 | 快照+截断同事务；内存/落库衔接（`design_04` §2.3） |
| 骨架 schema 泛型 dict 与协议类型漂移 | 前后端契约断裂 | Phase 1 即收敛为类型化消息；前端 `types.ts` 同步 |

---

## 九、横切：errorx 式错误体系与日志

实现一套 **errx**（`backend/app/errx/`）统一错误体系与标准库 logging，仿 Go 的
`psych-core-api/pkg/errorx`（位于外部项目，非本仓库）的 errorx 包设计。

### 9.1 errx 错误体系

| 概念 | Python 落点 | 说明 |
|------|-------------|------|
| StatusError | `errx.Error(Exception)` | 携带 `code` / `msg(message)` / `extra` / `is_affect_stability` / `cause` / `stack` |
| 注册表 | `errx._registry.register()` | 错误码集中定义，未注册回落 `"Service Internal Error"` |
| 构造 | `errx.new(code, extra=...)` / `errx.wrap(cause, code, extra=...)` | 新建 / 包装（保留原因链） |
| 匹配 | `errx.match_code(err, code)` | 沿 `__cause__` + `Error.cause` 链判断 |
| 消息占位 | `message` 支持 `{key}`，由 `extra` 替换 | |

**错误码（`backend/app/errx/codes.py`，集中注册）**：

| 模块 | 编号 | 含义 |
|------|------|------|
| 会话 SESS | 1001 / 1002 | session 不存在 / 已结束 |
| 引擎 ENG | 2001–2005 | 非法转换 / 回溯目标缺失 / 回溯越界 / 玩家操作非法 / 引擎未运行 |
| Agent | 3001–3002 | 角色不在会话 / 全部提议被驳回（僵局） |
| LLM | 4001–4002 | 调用失败 / 结构化输出解析失败 |

### 9.2 日志 / trace（`app/core/logging_config.py`）

- 标准库 `logging`，`logger = logging.getLogger("wenjing.<module>")`。
- 覆盖六类关键节点：引擎生命周期、phase cycle 各步、Agent 调度（提议/验证/重试/放弃）、玩家操作、回溯、LLM 调用。
- **事件即日志**：`EventStore.append` 对每条 `GameEvent` 落一条 structured `event` 日志，
  纯内存运行也能从日志还原整场剧情。
- `EngineConfig` 上未启用 DB 前的回溯通过内存快照恢复角色记忆（`GameEngine._memory_snapshots`）。

---

## 十、后续（非 MVP）路线

剧本编辑器 / 角色切换 / TTS·ASR·图片生成 / 多结局分支树 / 多人联机 / 作品分享社区 / 难度分级 / RAG 长期记忆（D8，Stage3 长续写再评估）——均不在 MVP 范围，见 `design.md` §六。

---

> 文档索引与状态更新见 [`design.md`](design.md)。