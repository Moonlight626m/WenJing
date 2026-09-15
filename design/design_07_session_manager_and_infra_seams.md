# 文境 (Wenjing) — 模块设计：会话组合根、长驻引擎与 Infra 接缝

> 澄清后端后续扩展时的架构取向：**不推倒重分层**，只补"组合根/use-case"这一层，
> 并划清基础设施抽象的边界。本文记录三个已收敛的裁决，供实现里程碑落地。

状态：**决策（已评估）** · 变更范围：仅设计文档，暂不改代码。

---

## 〇、要回答的三个问题

1. **每会话是否"一个长驻 GameEngine 实例服务"？** — 是，但要由谁持有、如何恢复。
2. **当前架构"既非 DDD 也非三层"是否不伦不类？** — 否，是符合"深模块/接缝"的健康形态，只缺一层。
3. **Infra（DB / Redis / COS / email–sms / 用户）是否现在抽象？** — 只抽象有真实需求的 DB，其余在组合根 seam 上按需补。

---

## 一、惯例用词（源自 codebase-design）

统一全库术语，避免在代码与文档里混用：

- **Interface**：调用方必须了解的一切（签名 + 不变量 + 顺序约束 + 错误模式 + 配置）。
- **Adapter**：在接缝上满足某接口的具体物（身负 role，无关 substance）。
- **深模块**：小接口 + 大实现，调用方低成本获得高纵深。
- **接缝（Seam）**：不修改内部也能换取行为的位置；接口所在处。
- **组合根（Composite Root）**：把 Adapter 组装到各接缝的薄层，通常是进程入口附近。

> 原则参照：**one adapter = hypothetical seam；two adapters = real seam**——
> 不为不存在的第二个 adapter 预先造抽象。

---

## 二、裁决 1 — 每会话一个长驻引擎实例

### 结论

**成立**。每场游戏 = 一个 `GameEngine` 对象长期存活，由新的 `SessionManager`（组合根 / use-case 层）持有。

依据（现状）：

- `GameEngine` 已是"一场游戏 = 一个对象"：构造注入 `session_id/script/llm`，内部私有持有
  `state_machine`、`event_store`、`CharacterAgentManager`、`_memory_snapshots`
  （`app/core/game_engine.py:37-71`）。
- 一个 asyncio 协程长驻挂起不占 OS 线程，成本极低 → 支持几百上千并发会话。
- 真正的成本不是 CPU/内存，而是**生命周期与状态所有权**：谁建、谁持有、崩溃/重启从哪恢复。

### 需要谁持有

新增 **`SessionManager`**（组合根 / use-case 层，计划于实现里程碑落地）：

```
本次尚未实现，仅定契约与形状：
```

- `start(session_id, script_id) -> GameSession`：从 DB（sessions/scripts）恢复或新建引擎实例。
- `submit(session_id, player_action)`：把玩家动作喂给对应实例的进行中的 run。
- `recover(session_id)`：重启后从 `PersistentEventStore.restore` 恢复实例状态。
- 维护 `session_id -> GameEngine` 的存活表 + 空闲/结束清理。

### 关键取舍：**保留 `run()`，用 asyncio Task 糊**（已收敛）

经评估，当时不把 `run()` 拆成 `step_until_player_turn()/submit_decision()` 语义。

- `run(player_decision)`（`game_engine.py:75`）内部 `while True` 阻塞循环到游戏结束。
- 半交互场景下 `player_decision` 需跨网络 await 玩家输入（Step 6 是天然中断点）。
- **本阶段做法**：`SessionManager` 为每个会话 `asyncio.create_task(engine.run(decision_cb))`，
  再用一个 `asyncio.Queue` 充当 `player_decision` 的喂入口 — 引擎编排不变，接口不动。
- 代价：一旦进程退出，进行中的 run 协程随进程消失，需靠 `recover`（事件重放）补回——断点续跑的
  精确断点语义（"停在 Step 6"）暂不提供，退化为"重放恢复到最后已落库事件"。

**后续若需要真·断点（精确停在玩家回合、可暂停/恢复）再升级为 step 语义**，属另一个里程碑，
不影响本文件结论。

---

## 三、裁决 2 — "既非 DDD 也非三层"不是问题

### 结论

**当前分层是健康的"core 领域 + 外围 adapter"形态，不是四不像。** 不应按 DDD 或 strict 三层强行重分层。

现状映射（用接缝语言重读）：

| 层 | 内容 | 角色 |
|---|---|---|
| 领域 / 编排（深） | `core/game_engine`、`core/state_machine`、`core/types`、`core/event` | 行为的所在地，纵深所在 |
| 领域 Agent | `agents/*`（character/screenwriter/verifier/model_config） | 带 LLM adapter 的子域 |
| 横切 | `errx/` | 底层共享错误体系，零业务依赖 |
| Infra adapter | `db/`、`models/`（SQLAlchemy async） | 持久化的 adapter |
| 表示层 | `api/routes.py` | 目前为占位符，**尚未接引擎/DB** |

### 缺失的只有一层：use-case / 组合根

三层里的 `service`、DDD 里的 application service，落到此处就是**一个薄的用例层**，
把"接 LLM → 建引擎 → 调 run → 落 session 元数据"框住。当前缺的就是它
（引擎既是 coordinator 又是 orchestrator，且没有显式入口旁落）。

**推论**：这个 use-case 层，正是裁决 1 的 `SessionManager`。二、三合为一处。

---

## 四、裁决 3 — Infra 抽象的边界

### 结论

**只抽象有真实需求的 DB；其余 Infra（Redis / COS / email–SMS / 用户体系）等第一个真实需求出现时，
在组合根 seam 上补 adapter。**

> ⚠️ **2026-09-15（ADR-0002）**：用户体系的「第一个真实需求」已出现——多用户账号与
> 教师/学生 RBAC 已纳入范围。AuthPort 按本文预期在组合根 seam 上**落地为具体实现**
> （`orgs`/`users` + `auth_sessions` Cookie 会话），不再是「将来」。Redis/COS/email–SMS
> 的结论不变。

不做的理由（遵循"two adapters = real seam"）：

- **DB 已经是真实 adapter**：`app/db/session.py`（async engine/session）+ `models/`（ORM 五表）
  + `PersistentEventStore`（flush/restore/truncate）。无需再造容器，ORM 本身就是 infra adapter。
- **Redis cache / COS / email–SMS / 用户体系当前零用例**。在无调用方前预造
  `CacheService`/`StorageService`/`Notifier`/`AuthProvider` 是"为不存在的第二个 adapter 造假缝"，
  强行增加纵深噪音。

### 组合根的 seam 位置（现在要定下）

未来这些 Infra 的**接缝位置**现在就定在组合根（`SessionManager`/`build_*` 工厂）里汇聚，
内容等到真需求来临再加：

```
组合根（SessionManager / 工厂）
 ├─ DB:    SessionLocal / PersistentEventStore（现在就用）
 ├─ cache:   将来 CachePort      ← seam 已定，adapter 后补
 ├─ storage: 将来 StoragePort    ← seam 已定，adapter 后补
 ├─ notify:  将来 NotifierPort   ← seam 已定，adapter 后补
 └─ auth:    AuthPort            ← ADR-0002 已落地（账号/RBAC/会话）
```

- 将来任一出现真实需求 → 在同一 seam 上换 adapter = **只改一个调用点**。
- 记住：接缝位置是设计决定，接缝内容要由真实 adapter 触发。别为假缝铺路。

---

## 五、后续实现里程碑（本文不落地，仅登记）

以下不在本轮执行，作为未来工作的候选：

1. **`app/session/`（组合根 / use-case）**：`SessionManager` + `build_engine()` 组合根，
   把 `Settings → ModelConfig → LLMService → GameEngine` 接真，并用 asyncio.Task 长驻每会话。
2. **`main.py` lifespan** 接 DB（`init_db`/engine 释放）、挂 `SessionManager` 为应用级单例。
3. **`api/routes.py` 接真**：`POST /api/sessions` 真建会话；`WS /ws` 真跑 `run` + 事件流推送；
   补 errx → WS/REST 错误映射中间件。
4. **断点续跑（真·step 语义）**：仅当需求要求"精确暂停/恢复"时，再把 `run()` 拆成 step。
5. **Infra**：Redis/COS/email —— 各带第一个真实需求时在同一组合根 seam 上补。
   （用户体系/AuthPort 已由 ADR-0002 落地。）

---

## 六、与既有文档的关系

- 补 `design_03`（引擎）「十、启动流程」之外的**会话持有与恢复**视角。
- 是 `design_06`（MVP 实施收敛）「横切 + 接线空档」的后续：确认 API/LLM/DB 接线的归属层。
- 不推翻 `design_04`（数据持久化）——事件存储仍是落库唯一真实 Infra adapter。