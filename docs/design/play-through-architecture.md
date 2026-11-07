# 游玩链路说明（现行）

> 状态：M0–M4 已落地（2026-11-07）。上游设计见
> `docs/design/play-through-redesign.md`（v5，下称「设计」）。
> 本文讲**现在是什么样、为什么这样、去哪里找**，供后续里程碑（M4–M8）与排查时查阅；
> 任务与进度仍以 GitHub Issues 为追踪源。

## 1. 什么时候查这份文档

- 要动 Stage2 还原、Stage3 续写、回溯、快照、剧本契约或事件类型时，先读对应小节。
- 看到「旧剧本走 agent 路径 / 新剧本走纯 IO」两个分支时，第 3 节解释分流条件。
- 改契约前后，第 4 节列出必须同步的四处与当前版本号。
- 连接数据库、建库、迁移、seed 的口径在第 5 节。

---

## 2. 三条链路一眼图

```
剧本（ScriptPackage，可含珊瑚图字段）
  ├─ 旧剧本：无 options/dialogue/endings → Stage2 线性 + 运行期 agent（行为不变）
  └─ 新剧本：有珊瑚图字段 → Stage2 纯 IO 播放（M4 落地运行期）
Stage3 续写：参演（NPC + 玩家）在场行动，工作人员（Director/Producer/Painter…）
            不出场；探索地图与干涉（M5/M6 落地）
事件溯源：events 是唯一权威；分支切换保留历史；快照只是缓存
```

当前**已落地**的是：契约与事件注册（M1）、新库与 v2 基线（M2）、回溯修复（M0）、
Stage2 生成期（M3：珊瑚图大纲 + 台词预写 + 校验三处接线），以及 Stage2 运行期
（M4：珊瑚图纯 IO 播放，旧剧本走原 agent 路径）。
Stage3 探索/工作人员（M5/M6）、离线 tick（M7）、快照新列与回溯页（M8）仍按设计
推进——它们依赖的契约与事件名已经就位，见第 4 节。

---

## 3. Stage2：珊瑚图还原（契约已就位，运行期在 M4）

### 3.1 数据形状

`ScriptPackage` 在旧字段之外新增（全部有默认值，旧剧本零迁移）：

| 字段 | 含义 |
|---|---|
| `Beat.dialogue: DialogueLine[]` | 生成期预写台词；`speaker=None` = 旁白 |
| `Scene.options: SceneOption[]` | 决策点；空 = 线性播放 |
| `BranchScene.dialogue / ending_id / return_mode / return_scene_id` | 分支台词、终局、回主干方式 |
| `ScriptPackage.endings: Ending[]` | `canonical` / `alternate` / `distractor` 结局 |
| `ScriptPackage.exploration: ExplorationMap?` | Stage3 地图（地点 + 在场角色 + 离线事实） |

语义（设计 §A1）：

- **珊瑚形**：主干场景顺序播放；场景的选项指向分支、下一场景或结局。
- **回主干**：非终局分支播完按 `return_mode` 回主干——`choice` 回决策点、
  `continue` 续接下一场；带 `ending_id` 的分支是终局，不回主干。
- **选项目标**：`SceneOption` 的 `branch_id` / `target_scene_id` / `ending_id`
  最多填一个；全为空表示续接主干下一场。
- **旧剧本分流**：没有 `options`/`dialogue`/`endings` 的剧本仍走运行期 agent
  线性路径，行为与改动前完全一致。

### 3.2 生成期（M3 已落地）

节点链（`workflow/graph.py`）：

```
divide_events(v4 大纲：beats + branches + options + endings)
  → design_characters → [pre_write_gate]
  → write_script(主干) → write_dialogue(逐场景预写台词) → final_audit
  → design_assets → [final_gate]
```

- `divide_events` v4 产出 `SceneDraft.options` / `BranchSpec.return_mode|return_scene_id|
  ending_id` / `EventDivisionDraft.endings`；`write_script` 经 `_backfill_scenes`
  回填到 `Scene.options` / `ScriptPackage.endings`，分支的返回方式以草稿为准
  （不由分支文本决定）。
- `write_dialogue` 逐场景一次 LLM 调用，把 `Beat.dialogue` 与
  `BranchScene.dialogue` 填进剧本包；单场景失败只降级为空台词（运行时回退
  agent 路径），不阻塞整包。**可扮演角色也写台词**——玩家开局才选角色，
  其余可扮演角色由系统扮演；播放期只跳过玩家所选角色的台词（M4）。
- `validate_replay`（`domain/generation/validators.py`）把关珊瑚图：选项目标存在、
  canonical 可达 canonical 结局、分支返回合法、干扰项 ≤2/场景、分支台词 ≤4、
  结局 ≤4 且至少 1 个 canonical、speaker ∈ participants、无隐式环
  （`choice` 回决策点不算环）。走向判定按珊瑚语义：没有 `options` 的场景
  线性续接主干，「全空目标」的选项也是续接主干，带 `ending_id` 的分支是终点；
  环检测把线性场景的隐式主干边算在内。关键事件顺序由「canonical 只能向前跳、
  不得跳过含关键事件的场景」保证。旧剧本恒通过。
- 校验时机三处：`final_audit` 先跑确定性校验（失败直接打回重写，不花 doubter
  的钱）、`final_gate` 在教师编辑/配图后重跑 `validate_all`、落库
  `_persist_package` 前再跑一次（有原文分析时跑全量 `validate_all`，否则
  至少 `validate_replay`）。

> 关系表解析（设计 §A2 的 `script_*` 表）尚未落地：剧本仍整包存
> `scripts.script_data`。见第 5 节的延期说明。

### 3.3 运行期（M4 已落地）

`domain/game/replay.py` 从 `ScriptPackage` 派生只读珊瑚图（`build_replay_graph`，
无第二份持久化真相），`ReplayDirector` 零 LLM、零 agent，只产出事件：

- `start` / `enter(node_id)` 播到下一个决策点或结局；`choose(state, option_id)`
  写选择并播目标节点；`options(state)` 给交互点；`resolve(events)` 从活动分支
  事件折叠播放位置（快照不含它）。
- 节点编号：`scene:{id}`、`scene:{id}::branch:{id}`（与配图槽位同拼法）、
  `ending:{id}`。决策点选项 id 就是 `option_id` 字符串（`o1`…），前端无需改动。
- 事件：`replay_node_entered`（场景/分支，带 scene_key/title/current_asset）、
  `replay_narration`、`replay_choice`、`replay_ending_reached`；预写台词落
  `character_speech`（`source=replay`），Stage3 的 `speech_log` 因此有上下文。
  节点进入与旁白按 narrative 消息下发，选择/结局按 system 消息下发。
- 玩家所选角色的台词跳过（不替玩家说话），该拍由 beat 描述以旁白呈现。
- 回主干：`return_mode=choice` 的分支播完停在父场景决策点，交互文案
  「回到刚才的选择」；`continue` 续接 return_scene / 主干下一场；带
  `ending_id` 的分支是终点。主干播完没有显式结局时用第一个 canonical 结局。
- 回溯的「拍」变成 `replay_node_entered`：回退后整节点重演（新分支继承前缀）。
- 到达结局：`beat_cursor` 对齐 `total_beats`，交互复用 0=续写 / 1=结束。
- **Stage2 不允许自由输入**（见 6.1）；Stage3 仍是旧的 3 轮 agent 路径，
  探索/换景/工作人员在 M5/M6。

运行期不推 `beat_cursor`；场景键/标题/背景由播放位置解析（`export_state`）。
旧剧本（无 options/endings）不派生图，运行时保持原 agent 线性路径。

---

## 4. 契约与事件（单源四处）

### 4.1 版本与同步

当前 `CONTRACTS_SCHEMA_VERSION = 3.1.0`（`backend/app/contracts/base.py`）。
3.0.0 是 Stage2 删除自由输入的 breaking；3.1.0 是 M3 给生成草稿加可选字段（minor）。

改契约必须同步四处，缺一处都不会报错：

1. `backend/app/contracts/`（Pydantic，唯一事实源）
2. `contracts/fixtures/`（手工维护的样例载荷；每个 fixture 的 `schema_version`
   必须等于常量，嵌套 `VersionedContract` 也带该字段）
3. `contracts/jsonschema/`（`cd backend && uv run python -m scripts.export_contracts`）
4. `frontend/src/lib/contracts/types.ts`（手工镜像，**没有生成器**）

分类规则见 `docs/contract-change-process.md`：加可选字段/枚举值是 minor；
收紧校验、删字段、改名、改语义是 **breaking（升主版本）**。M1 从 Stage2 允许列表
删除 `free_input` 就属于收紧，所以是 3.0.0 而不是设计草案里写的 2.9.0。

### 4.2 命令

`CommandKind`：`select_role / choose_option / free_input / rollback_to_event /
enter_stage3 / confirm_ending / exit_game / intervene`。

- **Stage2 允许**：`choose_option / rollback_to_event / exit_game`（无 free_input）。
- **Stage3 允许**：`choose_option / free_input / rollback_to_event /
  confirm_ending / exit_game`；`intervene` 契约已声明，但**尚未**进允许列表——
  M6 接上 ProducerAgent 处理器时再加，否则会落到引擎的非法命令兜底。
- `IntervenePayload` 与 `FreeInputPayload` 共用 `TextPayload`（1–2000 字）。

### 4.3 领域事件登记表

`backend/app/domain/game/event.py` 的 `EVENT_*` 常量与
`backend/app/contracts/enums.py::EventType` 对**M1 新增的事件**是 1:1
（值相同）。投影 `session_projection._contract_event_type` 对未显式映射的事件
直接按值构造，未知值才降级为 `narrative_advanced`。

新人事件命名遵循设计用语；已有对照关系（`plot_advancement → narrative_advanced`
等）保留在 `_EVENT_TYPE_MAP`。测试
`test_contracts.py::test_new_domain_events_have_matching_contract_event_types`
钉住 1:1，新增事件时一并登记。

| 分组 | 事件 |
|---|---|
| Stage2 播放 | `replay_node_entered` / `replay_narration` / `replay_choice` / `replay_ending_reached` |
| Stage3 探索/场景 | `exploration_settle` / `scene_created` / `scene_switch` / `scene_unlock_rejected` |
| 角色 | `character_created` / `pull_in_character` |
| 干涉 | `intervention_requested` / `intervention_rejected` |
| 世界/离线 | `world_fact` / `offline_hint` |

---

## 5. 存储：wenjing_v2（M2）

### 5.1 拓扑

- 应用只连 `wenjing_v2`（默认 URL 在 `backend/app/infrastructure/config.py`，
  `.env.example`、docker-compose、CI、测试回落值都已指向它）。
- 旧库 `wenjing` **只读保留**用于观察；不做数据迁移，剧本重新生成后入新库。

### 5.2 迁移链

- `backend/alembic/versions/0001_v2_initial.py`：合并后的**单一基线**。
  它等价于旧链 0001–0012（服务端默认值已补齐，`ix_scripts_status` 保留）。
- `backend/alembic/legacy_versions/`：冻结的旧链，**不被 Alembic 扫描**，
  仅供对照/审计。
- 之后的 schema 改动从基线起写 `0002+` 增量迁移。

> 注意：v2 基线仍是**当前** schema（剧本整包 JSONB 在 `scripts.script_data`）。
> 设计 §D2 的 `script_characters/scenes/...`、`session_ticks`、快照新列会随
> 表仓储里程碑（M4 之后）、M5、M8 以增量迁移落地；等表仓储接管读写后再删
> `script_data`。M4 运行期先从整包派生珊瑚图。

### 5.3 建库/迁移/seed

```bash
make db-up            # 起 PostgreSQL
make db-create-v2     # 既有 pgdata 卷补建 wenjing_v2（新卷由 POSTGRES_DB 默认值建）
make migrate          # alembic upgrade head（v2 基线）
make seed             # 默认 org + 测试账号 + prompts（幂等）
```

`make test` 会清空所连的库（现在是 v2），跑完补 `make migrate && make seed`。

### 5.4 迁移 URL 的优先级

`backend/alembic/env.py`：调用方显式注入的 `sqlalchemy.url` 优先（迁移测试的临时
库）；只有 ini 占位符 `driver://...` 才回落到 `Settings.database_url`。

---

## 6. 回溯与事件溯源（M0 已修复）

### 6.1 回溯语义

- `rollback_to_event` 新建活动分支，**继承前缀止于目标所属叙事拍之前**；
  目标拍由新分支整拍重演。这样「从 DB 恢复时的『快照 + 增量重放』」与
  「回溯命令结束时的现场」严格一致，不会把同一拍计两次。
- 目标解析为「路径上 id ≤ target 的最后一个 `plot_advancement`」；落在回合中段
  的目标回到该回合起点；首拍之前没有合法目标（`ENG_ROLLBACK_TARGET_MISSING`，
  且不切分支）。
- 阶段、`beat_cursor`、`plot_log`、`direction`、角色记忆**全部随事件回退**。
  旧行为「保留当前阶段」会让状态与事件流不一致，已废弃。

### 6.2 记忆由事件重建

- `GameRuntime.replay_from(snapshot, events)`：快照提供基线（含 `latest_event_id`），
  只对**基线之后**的事件做记忆折叠，避免与快照缓存双计。
- 折叠入口 `CharacterAgentManager.derive_memories`，与实时写入共用
  `CharacterAgent.record_proposal / record_speech`（同一写法，防漂移）。
- **只喂活动分支事件**：`_restore_runtime` 统一取 `store.active_events()`；
  喂全量历史会把被放弃分支的回合折回来（游标/记忆都会错）。
- 被驳回后的重提也写 `proposal {revised: true}`，否则重放后这份记忆消失、
  `rejected` 去重弱于回溯前。

### 6.3 恢复路径

生产每条命令重建运行时（`session_runtime._restore_runtime`）：
读会话行（`FOR UPDATE`）→ 载入剧本与分支 → 最新快照基线 → 重放快照之后的
活动分支事件 → 执行命令 → 单个 CAS 事务落库（版本、事件、命令行、head/分支/阶段、
快照）。回溯目标前的快照优化留给 M8（快照带 `branch_id/sequence` 后才有定位依据）。

---

## 7. Stage3 设计要点（M5–M7，尚未落地）

只列后续实现必须遵守、容易踩的点（细节见设计 §B）：

- **参演 vs 工作人员**：NPC 与玩家出场、写台词、进 `speech_log`；Director（选项）、
  Producer（干涉解析）、Painter、Verifier、Screenwriter 不出场、不写角色台词。
- **在场是唯一事实源**：`participants` 成员集合 + `scene_switch` 事件；
  运行时按事件重建动态场景/角色，因此建场景/拉人/新增角色都可回溯。
- **干涉全部事件化**：`scene_created` / `character_created` / `pull_in_character`；
  回溯到创建之前 = 该场景/角色从未存在。预算：新场景 ≤3/会话、新角色 ≤2/会话、
  每轮 ≤1 次干涉。
- **私密事实不泄漏**：`world_fact` 的 `visibility=private` 只进对应角色视图，
  投影层必须按观众过滤，不能当普通系统广播。
- **离线 tick**：`session_ticks(session_id, tick_index)` UNIQUE + claim-first，
  一 tick 一事务；只写 `offline_hint` 与事件，不设计玩家选项、不跑 Director。
- **旧剧本**：`exploration=None` 时 Stage3 维持现有 3 轮行为。

---

## 8. 代码索引

| 主题 | 位置 |
|---|---|
| 契约（剧本/命令/枚举/版本） | `backend/app/contracts/{script,commands,enums,base}.py` |
| 事件常量 | `backend/app/domain/game/event.py` |
| 运行时（重放/回溯/推进） | `backend/app/domain/game/game_runtime.py` |
| 珊瑚图派生与纯 IO 播放 | `backend/app/domain/game/replay.py` |
| 角色记忆折叠 | `backend/app/domain/agents/character.py` |
| 恢复与命令事务 | `backend/app/services/session_runtime.py`、`session_store.py` |
| 投影（事件→消息/状态） | `backend/app/services/session_projection.py` |
| v2 基线 / 冻结旧链 | `backend/alembic/versions/0001_v2_initial.py`、`backend/alembic/legacy_versions/` |
| 迁移 URL 解析 | `backend/alembic/env.py` |
| 前端契约镜像 | `frontend/src/lib/contracts/types.ts` |
| 回溯验收测试 | `backend/tests/test_rollback_memory.py`、`test_branch_replay.py`、`test_full_flow.py` |
| 珊瑚图播放测试 | `backend/tests/test_replay_director.py` |

## 9. 验证口径

`make lint` → `make lint-arch` → `cd frontend && npm run typecheck` → `make test`
（`WENJING_LLM_API_KEY= make test` 走确定性 LLM，结果可复现）。契约改动后加跑
`uv run python -m scripts.export_contracts`；数据库相关集成测试需要 PG 可用，
否则会静默 skip（「全绿」不等于跑过）。
