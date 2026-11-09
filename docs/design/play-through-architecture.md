# 游玩链路说明（现行）

> 状态：M0–M8 已落地（2026-11-08）。上游设计见
> `docs/design/play-through-redesign.md`（v5，下称「设计」）。
> 本文讲**现在是什么样、为什么这样、去哪里找**，供后续排查与增量开发查阅；
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
Stage3 续写：参演（NPC + 玩家）在场行动，工作人员（Director/WorldBuilder/Painter…）
            不出场；探索地图与干涉（M5/M6 落地）
事件溯源：events 是唯一权威；分支切换保留历史；快照只是缓存
```

当前**已落地**的是：契约与事件注册（M1）、新库与 v2 基线（M2）、回溯修复（M0）、
Stage2 生成期（M3：珊瑚图大纲 + 台词预写 + 校验三处接线）、Stage2 运行期
（M4：珊瑚图纯 IO 播放，旧剧本走原 agent 路径）、Stage3 确定性探索骨架
（M5：地点/在场/结算/换景）、Stage3 工作人员与玩家干涉
（M6：DirectorAgent 选项 + WorldBuilderAgent 干涉 + 动态场景/角色 + world_fact）、
离线 tick（M7：NPC 自主行动 + offline_hint），以及快照坐标与回溯页
（M8：`(branch_id, sequence)` 坐标、存档点、按目标选快照、旧分支只读、游戏页入口）。

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
- 事件：`replay_node_entered`（场景/分支，带 node_kind/scene_key/scene_title/
  current_asset；回决策点时带 `returned_from`）、`replay_narration`、
  `replay_choice`、`replay_ending_reached`；预写台词落 `character_speech`
  （`source=replay`），Stage3 的 `speech_log` 因此有上下文。
  节点进入与旁白按 narrative 消息下发，选择/结局按 system 消息下发。
- 玩家所选角色的台词跳过（不替玩家说话），该拍由 beat 描述以旁白呈现。
- 回主干：`return_mode=choice` 的分支播完回到父场景决策点（写一条父场景
  `replay_node_entered` 表示珊瑚回边，交互文案「回到刚才的选择」）；
  `continue` 续接 return_scene / 主干下一场；带 `ending_id` 的分支是终点。
  主干播完没有显式结局时用第一个 canonical 结局。图上有环/未知引用
  （教师手改包）时收敛到主线结局并打警告，不无限播放。
- 回溯的「拍」变成 `replay_node_entered`：回退后整节点重演（新分支继承前缀）。
- 到达结局：`beat_cursor` 对齐 `total_beats`，交互复用 0=续写 / 1=结束。
- **Stage2 不允许自由输入**（见 6.1）；Stage3 探索骨架（M5）与工作人员/干涉
  （M6）、离线 tick（M7）与快照/回溯页（M8）见第 7 节。

运行期不推 `beat_cursor`；场景键/标题/背景由播放位置解析（`export_state`）。
旧剧本（无 options/endings）不派生图，运行时保持原 agent 线性路径。

---

## 4. 契约与事件（单源四处）

### 4.1 版本与同步

当前 `CONTRACTS_SCHEMA_VERSION = 3.4.0`（`backend/app/contracts/base.py`）。
3.0.0 是 Stage2 删除自由输入的 breaking；3.1.0 是 M3 给生成草稿加可选字段；
3.2.0 是 M5 的 `switch_scene` 命令与交互点 `scene_options`；3.3.0 是 M6 把
`intervene` 加进 Stage3 允许列表；3.4.0 是 M8 给回溯 payload 加可选的
`target_event_id`（`target_sequence` 保留兼容，都是加法，minor）。

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
enter_stage3 / confirm_ending / exit_game / intervene / switch_scene`。

- **Stage2 允许**：`choose_option / rollback_to_event / exit_game`（无 free_input）。
- **Stage3 允许**：`choose_option / free_input / rollback_to_event /
  confirm_ending / exit_game / switch_scene / intervene`（干涉由 WorldBuilderAgent
  解析，运行时校验预算与 canon，见 7.2）。
- `IntervenePayload` 与 `FreeInputPayload` 共用 `TextPayload`（1–2000 字）；
  `SwitchScenePayload.scene_key` 是交互点 `scene_options[].scene_key`（`loc:{key}`）。
- `RollbackToEventPayload` 接受两种坐标：`target_event_id`（事件 UUID，
  `TimelineEntry.event_id` / 存档点卡片，首选）与 `target_sequence`（分支时间线
  下标，旧坐标，保留兼容）；两者至少给一个，UUID 优先。

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
- 目标解析为「路径上 id ≤ target 的最后一个叙事事件」——旧剧本是
  `plot_advancement`，珊瑚图剧本是 `replay_node_entered`（M4）；落在回合中段
  的目标回到该回合起点；首拍之前没有合法目标（`ENG_ROLLBACK_TARGET_MISSING`，
  且不切分支）。
- 阶段、`beat_cursor`、`plot_log`、`direction`、角色记忆**全部随事件回退**。
  旧行为「保留当前阶段」会让状态与事件流不一致，已废弃。

### 6.2 记忆由事件重建

- `GameRuntime.replay_from(snapshot, events)`：快照提供基线（含 `latest_event_id`），
  只对**基线之后**的事件做记忆折叠，避免与快照缓存双计。
- 折叠入口 `CharacterAgentManager.derive_memories`，与实时写入共用
  `CharacterAgent.record_proposal / record_speech`（同一写法，防漂移）。
- **记忆是有界窗口**：`working_memory` / `personal_log` / `rejected` 各保留最近
  `CHARACTER_MEMORY_LIMIT`（10）条；`_RState.plot_log` / `speech_log` 各保留最近
  50 条。事件流仍是全量权威，收口只影响读取窗口与快照大小。
- 角色可见的叙事摘要由 `GameRuntime.plot_entries_for(viewer)` 从活动分支事件派生
  （`plot_advancement` 按场景 participants、`exploration_settle` 按 `present`、
  `scene_switch` 按 `participants`、`replay_*` 公开），`view_plot_log` 取最近窗口；
  不再从剧本 beat 重建，也不再返回最早 5 拍。
- **只喂活动分支事件**：`_restore_runtime` 统一取 `store.active_events()`；
  喂全量历史会把被放弃分支的回合折回来（游标/记忆都会错）。
- 被驳回后的重提也写 `proposal {revised: true}`，否则重放后这份记忆消失、
  `rejected` 去重弱于回溯前。

### 6.3 恢复路径

生产每条命令重建运行时（`session_runtime._restore_runtime`）：
读会话行（`FOR UPDATE`）→ 载入剧本与分支 → 最新快照基线 → 重放快照之后的
活动分支事件 → 执行命令 → 单个 CAS 事务落库（版本、事件、命令行、head/分支/阶段、
快照）。

快照坐标（M8）：`snapshots` 带 `(branch_id, sequence)`——`sequence` 是**分支时间线
下标**（含继承前缀），与 WS `seq`、`sessions.head_sequence`、回溯 `target_sequence`
同一口径。恢复时不再盲取「会话最新一行」：只在活动路径的分支里挑、`sequence` 不晚于
目标、且 `plot_context.latest_event_id` 与 `path[sequence]` 对齐的快照（父分支在回溯点
之后、属于被放弃历史的快照会在这一步被排除）。回溯命令因此可以「按目标选快照」：
`_restore_runtime(rollback=…)` 的状态迁移与记忆折叠停在目标事件（`replay_from`
末尾的世界/播放位置/探索进度折叠仍遍历整条路径，但随后会被回溯的前缀重放覆盖）；
随后 `GameRuntime.rollback` 仍按前缀整段重放（事件是唯一权威）。HEAD 阶段本来就不允许
回溯的会话（`ended` / `stage2_complete`）不做截断，保持旧行为让运行时按 HEAD 阶段拒绝。

快照保留（`SessionStore._prune_snapshots`）：每分支只留最近
`SNAPSHOT_KEEP_PER_BRANCH`（20）个命令快照，`kind='rollback'` 全部保留。
快照是性能优化而非真相，删旧快照只增加回溯时的重放量，不改变结果。

---

## 7. Stage3：探索 + 工作人员 + 离线 tick（M5–M7）与回溯页（M8）

### 7.1 已落地：确定性探索骨架

- `domain/game/exploration.py`：`LocationRegistry`（地点表，场景键 `loc:{key}`）、
  `derive_exploration`（从 `scene_switch` / `exploration_settle` 折叠当前地点与
  已访问）、`ExplorationDirector.settle`（地点化摘要，确定性）、`present_names`。
- **在场是唯一事实源**：`present_names = 地点 participants ∩ 已创建角色`；
  Stage3 的提议与反应都只取在场者（旧剧本无地图 = 全部参演，行为不变）。
- 每轮玩家动作先写 `exploration_settle {location_key, scene_key, scene_title,
  summary, conflict, context, present}`：摘要进 `plot_log`、处境进 `direction`；
  Stage3 回合头不再 `advance_plot/confirm_direction`。
- 换景：`switch_scene` 命令（payload `scene_key`）→ 校验地点存在且非当前 →
  写 `scene_switch {from, to, scene_key, scene_title, participants}` → 目标在场者
  反应；换景是前进式，不建事件分支。交互点带 `scene_options`（当前地点置灰）。
  换景按 **narrative** 消息下发（前端只在 narrative 上应用场景键/标题），
  不消耗续写回合预算。旧剧本没有地图：契约按阶段允许该命令，但引擎会拒绝。
- 场景列表来源：`exploration_map.locations`（静态）+ 运行期 `scene_created`
  动态场景（M6，追加在后面）；仍不显示静态剧本场景。
- 回溯的「拍」在 Stage3 探索下是 `exploration_settle`：回退后地点进度与
  `scene_key` 一起回退（`_sync_exploration_scene_key` 兜底纠正）。
- 地图是**平铺地点表**（无地点间连边）：静态地点 + 已创建的动态地点都可前往；
  「未连通地点不可见」仍未实现，连通性过滤留给后续。

### 7.2 已落地：工作人员与玩家干涉（M6）

- **参演 vs 工作人员**：NPC 与玩家出场、写台词、进 `speech_log`；Director（选项）、
  WorldBuilder（干涉解析）、Painter、Verifier、GameMaster 不出场、不写角色台词。
  `DirectorAgent`/`WorldBuilderAgent`（`domain/agents/director.py`、`world_builder.py`）都
  **不挂工具**：上下文由运行时装配，输出结构化 JSON；解析失败分别回退
  「已验证提议 + 默认行动」与「拒绝并提示」，工作人员故障不能让玩家卡住。
- **导演选项**：Stage3 回合头收集/验证提议后调用 `DirectorAgent.design_options`
  （地点、在场、目标、教学重点、近期剧情、最近角色回应、公开世界事实、上一轮选项），
  交互点优先用导演的 2–4 条，其次已验证提议，最后两条确定性兜底。导演失败 = 选项为空，
  不影响推进。玩家选选项时，选项文案写进 `PlayerAction.text` 与 `player_action` 事件，
  NPC 反应、目标判定、回放/审计看到的是文案而不是编号。
- **剧情主持（GameMasterAgent）不是剧本生成器**：剧本由生成期 workflow 产出。运行期
  的 GameMaster 只负责旧剧本路径（无珊瑚图/无探索图）的确定性推进与交互设计，以及
  进入 Stage3 时定 2–3 个续写目标；新版 Stage2 珊瑚图与 Stage3 探索主循环都不经过它。
- **干涉管线**：`intervene {text}` → 写 `intervention_requested`（审计）→
  `WorldBuilderAgent.parse_intervention` 解析为 `create_scene / add_character /
  pull_in_character / reject` → 运行时确定性校验（预算、同名、玩家角色、地点存在）→
  事件化应用；失败写 `intervention_rejected {reason}` 并保持当前交互点。
  地点参数容忍 key 或标题（LLM 只见得到标题，`_resolve_location_key` 两种都认）；
  canon 的「不得改写已发生事实」由 prompt 约束，确定性校验不覆盖。
- **预算**：新场景 ≤3/会话（`MAX_DYNAMIC_SCENES`）、新角色 ≤2/会话
  （`MAX_NEW_CHARACTERS`）、每轮 ≤1 次干涉——全部由事件折叠判定（重放/回溯
  自动回退），预算用尽即 `intervention_rejected`。
- **动态场景**：`scene_created {scene_key: "loc:{title}", location_key, title,
  participants, visual_summary}` 进运行期注册表（`WorldState.dynamic_scenes`），
  交互点 `scene_options` 追加、可 `switch_scene` 进入、结算/在场判定与静态地点
  同一套代码（`ExplorationDirector.location/resolve_scene` 先查静态再查动态）；
  配图走 `SceneAssetIntent(kind="scene_montage")`，由 Session 层后台生成。
  静态探索地点没有 Stage2 的离线槽位，结算/换景时若事件索引无图同样补一次
  `scene_montage` 意图（`_request_location_asset`），去重由调度器负责。
- **动态角色**：`character_created {name, public_background, personality_traits,
  location_key, origin}` → `CharacterAgentManager.add_character` 建 agent（与剧本
  角色同一路径、同一裁剪视图），「为何在此」的 provenance 记忆由
  `derive_memories` 从事件折叠（实时/重放同一写者）；拉人入场
  `pull_in_character {name, from_scene, to_scene, reason}` 只改在场成员，不新建
  profile。
- **世界事实**：`world_fact {fact_id, kind, text, visibility, audience,
  location_key}` 由 `derive_world` 折叠进 `WorldState.facts`；`public` 进公屏
  （投影为 system 消息），`private` **只**进 audience 角色的 `view_world_facts`
  工具结果——投影层与时间线都显式过滤，绝不当普通系统广播。
- **回滚/重放**：动态场景与角色全部由事件派生。`replay_from` 先 `derive_world`
  + `_sync_world_characters`（补建缺失、移除「从未存在」），再折叠记忆；
  回溯到 `exploration_settle` 之前，在它之后创建的场景/角色/事实一并消失。
- **干涉不消耗续写回合**：不写 `player_action`（否则重放会多算一拍）、
  `stage3_round_taken` 不变；每轮上限由「最近一次 settle/switch 之后已有
  `intervention_requested`」判定。

### 7.3 已落地：离线 tick（M7）

- 触发：WS `session_init` 进快照之前补算（`_run_offline_ticks_guarded`），失败只记日志
  不阻断连接；只对续写阶段、未结束的会话生效。间隔由
  `offline_tick_interval_minutes`（缺省 30）决定，一次最多
  `max_offline_ticks`（缺省 3）个时段；间隔 0 = 关闭。
- 幂等：`session_ticks(session_id, tick_index)` 是 **claim-first** 幂等闸——认领行与
  该 tick 的事件在**同一事务**里写（`SessionStore.commit(claim=...)`），并发 init
  只会有一个赢家；`tick_id = uuid5(session_id, tick_index)`。
- 每 tick：重建运行时 → **全体 cast** 自主提议（LLM，并行；事实按各自所在地点锚定）
  → Verifier → 确定性结算
  （每个被接受的行动写成 public `world_fact {kind: npc_action, tick_id, location_key}`）。
  不设计玩家选项、不跑导演、不判目标、不推进 `stage3_round_taken`、不写台词。
- 结束写一条 `offline_hint`（命令外事件路径）：只指路时间线，不写详细摘要。
- 已知边界：LLM 提议在 claim 之前执行（并发 init 可能重复花费，但事件效果由
  claim 保证只落一次）；`offline_hint` 在 tick 事务之外单独提交（report_runtime_event
  CAS 重试；极端失败时本批次不再补写提示，但 tick 事实不会丢）；「事件序列指针」
  以 tick id 形式给出（`world_fact.fact_id` 前缀即 tick id）。
- 未做：关系漂移（无关系模型）、**地点变化**（确定性结算不推断）自助迁移、
  tick 内铸新场景与画师生图（需要 WorldBuilder 式裁定）、`scheduled_facts`（v5 改为
  NPC 自主行动，未使用作者预写事实）。

### 7.4 已落地：快照坐标与回溯页（M8）

- `snapshots` 新增 `branch_id/sequence/label/kind`（索引
  `(session_id, branch_id, sequence)`），`sessions` 新增 `head_sequence`；
  `SessionStatusResponse.head_sequence` 不再拿全局事件行 id 充数。
- 每条命令落一个存档点：`label` 由场景/命令生成（「选择 · 场景：当铺」
  「回溯 · 场景：当铺」；旧坐标回溯给出「回溯到 #N」），`kind = command | rollback`。
  不新增 checkpoint 事件，也不加 `snapshots.asset_id`。
- `GET /api/sessions/{id}/timeline` 返回 `entries[].event_id/branch_id`、`save_points`、
  `branches`；`?branch_id=` 指向旧分支时返回**只读**视图（`read_only=true`，
  进度原样保留但不可回溯）。回溯页按 `target_event_id` 提交，游戏顶栏补「回溯进度」入口；
  剧情回顾面板里的 `RollbackBar` 仍用 `target_sequence`（WS 消息只带 seq）。
- 已知边界：`last_tick_at` 不落列——离线 tick 的权威是 `session_ticks` 台账；
  `script_content_version` 随表仓储里程碑；存档点不做保留策略（每命令一行，
  读侧只取最近 20 个展示）；回溯页只做分支列表切换 + 只读回看，没有分支树可视化。

### 7.5 未落地（后续）

- **表仓储**：`script_*` 关系表、`scripts.replay_ready`、`ScriptRepository` 只读表
  （设计 §D/附录 A，未排期）。
- **新角色头像**：`character_created` 已带 公开背景/性格，但画师侧只接了场景的
  `scene_montage` 意图；角色头像生成随资产管线扩展。
- **旧剧本**：`exploration=None` 时 Stage3 维持现有 3 轮行为（干涉/换景命令
  契约允许但引擎拒绝）。

---

## 8. 代码索引

| 主题 | 位置 |
|---|---|
| 契约（剧本/命令/枚举/版本） | `backend/app/contracts/{script,commands,enums,base}.py` |
| 事件常量 | `backend/app/domain/game/event.py` |
| 运行时（重放/回溯/推进） | `backend/app/domain/game/game_runtime.py` |
| 珊瑚图派生与纯 IO 播放 | `backend/app/domain/game/replay.py` |
| Stage3 探索（地点/在场/结算/换景/世界） | `backend/app/domain/game/exploration.py` |
| 导演/世界构建（选项设计、干涉解析） | `backend/app/domain/agents/director.py`、`world_builder.py` |
| 角色记忆折叠 | `backend/app/domain/agents/character.py` |
| 恢复与命令事务 | `backend/app/services/session_runtime.py`、`session_store.py` |
| 投影（事件→消息/状态/时间线） | `backend/app/services/session_projection.py` |
| 快照坐标规则（单源） | `backend/app/services/session_store.py::snapshot_sequence_on_path` |
| v2 基线 / 冻结旧链 | `backend/alembic/versions/0001_v2_initial.py`、`backend/alembic/legacy_versions/` |
| 迁移 URL 解析 | `backend/alembic/env.py` |
| 快照坐标迁移 | `backend/alembic/versions/0003_snapshot_checkpoint.py` |
| 前端契约镜像 | `frontend/src/lib/contracts/types.ts` |
| 回溯页 / 存档点 UI | `frontend/src/components/rollback/rollback-timeline.tsx` |
| 回溯验收测试 | `backend/tests/test_rollback_memory.py`、`test_branch_replay.py`、`test_full_flow.py`、`test_snapshots.py` |
| 珊瑚图播放测试 | `backend/tests/test_replay_director.py` |
| 探索/换景测试 | `backend/tests/test_exploration.py` |
| 干涉/动态角色/世界事实测试 | `backend/tests/test_intervention.py`、`test_world_facts.py` |

## 9. 验证口径

`make lint` → `make lint-arch` → `cd frontend && npm run typecheck` → `make test`
（`WENJING_LLM_API_KEY= make test` 走确定性 LLM，结果可复现）。契约改动后加跑
`uv run python -m scripts.export_contracts`；数据库相关集成测试需要 PG 可用，
否则会静默 skip（「全绿」不等于跑过）。
