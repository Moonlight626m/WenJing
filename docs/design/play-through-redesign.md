# 游玩链路重构：Stage2 珊瑚图纯 IO + Stage3 参演/工作人员 + 回溯 + 新库

> 状态：设计草案 v5（2026-11-07）
> 已确认决策：
> 1. Stage2 单源扩展（Scene/BranchScene），不持久化独立 ReplayGraph；
> 2. 非主分支结束节点回溯回主干（珊瑚形）；干扰选项只在还原阶段；还原期不活化 agent，
>    纯前端 + DB 资源 IO；
> 3. 生成完成后把 agent 结果解析成 script/character/scene 等记录；
> 4. Stage3 的 DirectorAgent 是工作人员：不审核、不出场，设计并提供玩家行为选项，指挥画师；
> 5. 离线 tick 参考 AgentSociety：放任 NPC agent 自行行动；**不设计玩家选项、不跑 Director**；
>    需要新场景时由画师生图；不写详细摘要，只做提示 + 引导查看，然后正常放映并跳过玩家行为；
> 6. Stage2 禁用并删除 free_input（Stage3 保留）；
> 7. 新建 Postgres DB `wenjing_v2`，直接使用新 schema；**不做数据迁移**（现有数据仅临时观察）；
> 8. Stage3 增加**场景切换/选择**，以及玩家**干涉世界**（创建场景、拉入/新增角色）。

## Context

当前问题（已核实到行号）：

- Stage2 线性 beat + 运行期 agent；`branches/interaction_point` 只生成不消费
  （`script_adapter.py:49-59`）；玩家选项不改变走向。
- Stage3 用 `advance_plot` clamp 复读最后一拍（`screenwriter.py:46-55`），
  `stage3_rounds=3` 到顶即结束；无世界模型、无导演、无离线推进。
- 回溯生产 bug：`_memory_marks` 不落库，生产每条命令重建运行时
  （`session_runtime.py:761-813`），回溯只切事件分支、记忆不回退。
- 存储整包 JSONB（`scripts.script_data`），无角色/场景表；`snapshots` 无
  `branch_id/label/kind`，恢复永远取最新行。

目标：Stage2 珊瑚图纯 IO；生成期解析成关系表；Stage3 参演/工作人员分工 + 场景切换 +
玩家干涉；回溯按节点；新库新 schema。

---

## A. Stage2：珊瑚图还原（单源扩展，纯 IO）

### A1. 契约（可选字段，旧剧本零迁移）

```python
class DialogueLine(VersionedContract):
    speaker: str | None            # None = 旁白
    text: str
    stage_direction: str = ""

class Ending(VersionedContract):
    ending_id: str
    title: str
    description: str
    kind: Literal["canonical", "alternate", "distractor"]

class SceneOption(VersionedContract):
    option_id: str
    label: str
    kind: Literal["canonical", "distractor"]
    branch_id: str | None
    target_scene_id: int | None
    ending_id: str | None

Beat.dialogue: list[DialogueLine] = []
BranchScene.dialogue: list[DialogueLine] = []
BranchScene.ending_id: str | None = None
BranchScene.return_mode: Literal["choice", "continue"] = "continue"
BranchScene.return_scene_id: int | None = None
Scene.options: list[SceneOption] = []
ScriptPackage.endings: list[Ending] = []
```

**珊瑚语义**：主干场景顺序；场景内 `options` 指向 branch/target/ending；非主分支播完按
`return_mode` 回主干（`choice` 回决策点，`continue` 续接下一场）；有 `ending_id` 的分支
是终局。图天然无环。

**旧剧本**：无 `options/dialogue/endings` → `build_replay_graph` 返回 None → 现有线性
agent 路径不变。

### A2. 生成期解析成记录 + 纯 IO 门槛

生成 workflow 产出 `ScriptPackage` 后，`ScriptRepository.save_package()` 单事务解析进：

```
scripts（content_version/format/replay_ready）
  ├─ script_characters
  ├─ script_scenes（beat+dialogue JSONB）
  │    └─ script_scene_options
  ├─ script_branches（return_mode/return_scene）
  ├─ script_endings
  └─ script_locations（Stage3 地图 + scheduled_facts）
```

- `replay_ready=true` 条件：主干场景均有 dialogue、选项目标合法、分支有 return、
  至少 1 个 canonical ending。
- 生成节点：`divide_events` v4（大纲）→ `write_script` v4（主干文本）→
  `write_dialogue`（新，逐场景/分支预写台词）→ `final_audit(+validate_replay)` →
  `design_assets`（全部预生成）→ `final_gate`（编辑后**重跑** validate_all）。
- `ScriptPackage` 是传输/契约形态；表是持久层真相。

### A3. 校验（`validate_replay`）

选项目标存在、canonical 可达 canonical ending、分支 return 目标存在、关键事件顺序、
干扰分支 ≤2/场景且台词 ≤4 句、结局 ≤4（至少 1 canonical）、speaker ∈ participants、
无隐式环、教师编辑后重跑。

**实现注记（2026-11-07，M3 已落地）**：
- `divide_events` v4：`EventDivisionDraft` 增 `endings`，`SceneDraft` 增
  `options`，`BranchSpec` 增 `return_mode/return_scene_id/ending_id`；prompt 新增
  `option_rules`/`ending_rules` 两段；`_validate_division` 机器校验结局表、
  选项目标（分支/场景序号/结局）与分支返回引用。
- `write_script` 经 `_backfill_scenes` 把 `options`/`endings` 回填进剧本包；
  分支的返回方式以划分草稿为准（不由分支文本决定）。
- 新节点 `write_dialogue`（prompt v2）：逐场景一次 LLM 调用，填 `Beat.dialogue` 与
  `BranchScene.dialogue`（`SceneDialogueDraft`）；单场景失败降级为空台词。
  注册在 graph / runner `_NODE_MAP`·`_NODE_ORDER` / `GenerationNode` /
  `types.ts` / `labels.ts` / prompts defaults+seed 六处。
  v2 起**可扮演角色也写台词**（v1 让模型回避玩家角色，但玩家开局才选角色、
  其余可扮演角色由系统扮演，回避会让他们整场沉默）；播放期只跳过玩家所选
  角色的台词。
- `validate_replay` 三处接线：`final_audit`（先于 doubter，失败直接打回重写）、
  `final_gate`（教师编辑/配图后重跑 `validate_all`，不合法即报错不落库）、
  `_persist_package`（落库前再跑一次：三个调用点都能拿到原文分析，故跑全量
  `validate_all`，拿不到时才退回 `validate_replay`）。
- `validate_replay` 的走向判定按珊瑚语义：没有 `options` 的场景是线性播放、
  隐式续接主干下一场；「全空目标」的选项同样续接主干；带 `ending_id` 的分支
  是终点，即使 `return_mode=continue` 也不把主线往下带。环检测把线性场景的
  隐式主干边算进去；关键事件顺序靠「canonical 只能向前跳、不得跳过含关键事件的
  场景」保证（场景顺序即原文顺序）。
- 契约版本：M3 新增的草稿字段（`SceneDraft.options` / `EventDivisionDraft.endings` /
  `BranchSpec` 返回字段）是可选增量，按流程升 **3.1.0**（四处同步）。
- **与草案的差异**：
  - §A2 的「解析成 `script_*` 关系表 + `replay_ready`」仍未落地（M2 的注记曾把它
    排给 M3，实际后移；见 §D2 说明）。剧本继续整包存 `scripts.script_data`，
    M4 从整包派生珊瑚图。
  - `write_script` 仍是 **v3**（草案写 v4）：主干文本的写法没有变化，改的是上游
    划分草稿与新增的台词节点；空升版本只会让已 seed 的库重新落一份同内容默认。
  - 分支台词 ≤4 句/分支，**对所有分支**生效（草案只写干扰分支）：防包体膨胀，
    且与 `write_dialogue` 的输出约束一致。
  - 台词按**场景**一次生成（含该场景全部分支），不是每分支单独调用——成本与
    前后连贯性的权衡。
  - 选项直指 `ending_id`（不经分支）时没有独立场景，故没有配图槽位；M4 用当前
    场景背景兜底。`design_assets` 本身未改。
  - 关键事件顺序在 `validate_replay` 里是**相对判据**（canonical 只能向前跳、
    不得跳过含关键事件的场景）；与原文关键事件的对应仍由 `validate_event_order`
    按 beat 描述匹配，两者在总审/闸门/落库三处都会跑。

### A4. 运行时：纯 IO（`domain/game/replay.py`）

- `ReplayDirector`：`start/options/choose/resolve`，从表派生珊瑚图，零 LLM、零 agent。
- 事件：`replay_node_entered/replay_narration/replay_choice/replay_ending_reached`；
  预写台词落 `character_speech`（source=replay），保证 Stage3 的 `speech_log` 有上下文。
- 干扰分支播完写 `replay_node_entered(return_target)`（珊瑚回边），**不建事件分支**；
  UI 文案「回到刚才的选择」。玩家主动回溯仍走 `rollback_to_event`。
- 到达 ending：`beat_cursor=total_beats`，复用现有 0/1 交互。
- **Stage2 禁用 `free_input`**：从 `ALLOWED_COMMANDS[STAGE2_REENACTING]` 删除
  `FREE_INPUT`；交互点 mode 固定 `options`；前端 Stage2 隐藏自由输入框。
  `CommandKind.FREE_INPUT` 保留给 Stage3。
- 游玩期只读表 + 写事件 + 签名资产 URL。

**实现注记（2026-11-07，M4 已落地）**：
- `domain/game/replay.py`：`build_replay_graph(pkg)` 派生只读珊瑚图（场景顺序即
  主干；节点 `scene:{id}` / `scene:{id}::branch:{id}` / `ending:{id}`）；
  `ReplayDirector.start/enter/choose/options/resolve` 产出事件序列，零 LLM。
  旧剧本（无 options/endings）返回 None，运行时保持 agent 线性路径。
- 事件与投影：节点进入/旁白按 narrative 消息、选择/结局按 system 消息下发；
  `replay_node_entered` 带 `node_id/node_kind/scene_key/scene_title/current_asset`
  （结局由 `replay_ending_reached` 单独宣布，不在节点事件里），时间线沿它累积场景。
  分支播完回决策点时再写一条父场景的 `replay_node_entered`（带
  `returned_from`），**不建事件分支**。
- 对话：`Beat.dialogue` 与 `BranchScene.dialogue` 落 `character_speech`
  （`source=replay`）；`speaker=null` 的台词转 `replay_narration`；玩家所选
  角色的台词跳过。
- 决策点：选项 id 即 `option_id` 字符串；上下文取介入点的
  `what_player_can_do`（契约介入点没有 `context` 字段）。
- `return_mode=choice` 的分支停在父场景决策点（再写一条父场景的
  `replay_node_entered` 表示回边，文案「回到刚才的选择」），不建事件分支；
  `continue` 续接 `return_scene_id` 或主干下一场；主干播完且没有显式结局时
  用第一个 canonical 结局。图上有环/未知节点（教师手改包）时收敛到主线结局
  并打警告，不无限播放。
- 回溯按 `replay_node_entered` 定位「拍」：回退到节点开始前，新分支整节点重演。
- **与草案/前序注记的差异**：珊瑚图仍从 `scripts.script_data` 派生（表仓储后置，
  见 §D2 修正）；**Stage3 未改动**——到达结局选 0 进入续写仍是旧的 3 轮 agent
  路径（`beat_cursor` 在结局时对齐末尾，续写会复读最后一拍），探索/换景在 M5。
- 前端无需改动：现有消息流已按 narrative/character_speech/system 渲染，
  交互点选项 id 是字符串、自由输入框按 `allowed_commands` 自动隐藏。

### A5. 前端

镜像 `DialogueLine/Ending/SceneOption` 与新事件；Stage2 渲染 narration+dialogue、
只显示选项、无输入框；干扰分支结束显示「回到刚才的选择」；教师预览/闸门显示珊瑚结构。

---

## B. Stage3：参演人员 / 工作人员分工

### B1. Agent 分工

| 类别 | Agent | 职责 | 知识范围 | 出场 |
|---|---|---|---|---|
| **参演** | `CharacterAgent`（NPC×N） | 按人设/记忆/目标提出言行、回应玩家 | scoped WorldView（在场/公开信息） | 是 |
| **参演** | 人类玩家 | 选项、场景切换、自由发言、干涉请求 | 前端可见 | 是 |
| **工作人员** | `DirectorAgent` | **设计并提供玩家行为选项**；需要时产出 `SceneBrief`；指挥画师 | 引擎装配的全量上下文 | 否 |
| **工作人员** | `ProducerAgent`（制作人） | **解析玩家干涉/解锁新场景请求**（建场景/拉角色/引入地点）、canon 校验、派发画师与角色创建 | 全量剧本/世界/可用角色池 | 否 |
| **工作人员** | `PainterAgent`（现有 `PromptWriter`） | 画面主体转写（场景背景/新角色头像） | 场景/外貌锚点 | 否 |
| **工作人员** | `VerifierAgent`（现有） | 审核 NPC 提案/选项合法性 | 剧本/规则 | 否 |
| **工作人员** | `ScreenwriterAgent`（现有） | Stage3 剧情推进/方向（确定性优先） | 全量剧本 | 否 |

原则：
- 工作人员**不出场、不写角色台词、不进 `speech_log`**；输出只进系统事件/选项/资产。
- 参演只看到 scoped 视图；staff 看全量，但不得把系统信息泄漏给参演。
- **DirectorAgent 不审核**（审核是 Verifier）；**ProducerAgent 不设计选项**（选项是
  Director）；两者职责分离，避免一个 agent 既当裁判又当编剧。
- Director/Producer 都**不挂工具**：输入由运行时装配，输出结构化 JSON；解析失败走
  确定性回退（选项：已验证提案 + 地点；干涉：拒绝并提示）。

### B2. 在线回合数据流

```
人类：choose_option（可选 text 补台词） / switch_scene / free_input / intervene
  → player_action / scene_switch / intervention_requested 事件
  → Cast NPC 并行反应/提案（scoped，LLM）
  → VerifierAgent 审核提案
  → ExplorationDirector 确定性结算（在场/换景/目标/探索进度）
  → DirectorAgent 设计 2–4 个玩家选项
      · 至少 1 个推进目标、1 个关系向、1 个地点/探索向
      · 需要新场景时产出 SceneBrief（cap 3/会话）
  → 若有 SceneBrief：PainterAgent 转写 → SceneDesigner → asset_jobs 生图（惰性）
  → 交互点（选项 + 场景切换列表 + 自由发言 + 干涉入口）
```

### B3. 确定性骨架

- `exploration.py`：`derive_exploration`、`LocationRegistry`、`ExplorationDirector`、
  `Settlement`；事件 `exploration_settle`；在场过滤 `present_names`。
- Stage3 `_on_input` 先 settle 再收集在场 NPC 反应；`_run_cycle_head` 停止
  `advance_plot/confirm_direction/broadcast`。
- 旧剧本 `exploration=None` → 现有 3 轮行为不变。

**实现注记（2026-11-07，M5 已落地）**：
- `domain/game/exploration.py`：地点表（`loc:{key}` 场景键）、`derive_exploration`
  从 `scene_switch`/`exploration_settle` 折叠当前地点与已访问、`ExplorationDirector.settle`
  产出地点化摘要、`present_names = 地点 participants ∩ 已创建角色`。
- 运行时：Stage3 每轮动作先写 `exploration_settle`（摘要进 `plot_log`、处境进
  `direction`），再只让在场 NPC 回应；回合头不再 `advance_plot/confirm_direction`。
- 换景：新命令 `switch_scene {scene_key}`（契约加法，**3.2.0**）；写
  `scene_switch {from, to, scene_key, scene_title, participants}`，换景是前进式、
  不建事件分支；交互点带 `scene_options`（当前地点置灰），前端在交互卡里渲染「前往」。
- **与草案的差异**：M5 的地图是**平铺地点表**，没有地点间连边——地图里的地点
  都可前往；「解锁新场景 / 未连通地点不可见」与固定项「解锁新场景」随 M6 的
  Producer 落地。换景的「人物到场衔接」文案也归 M6（当前由目标在场者直接反应）。
- Stage3 的目标判定（goals）沿用原逻辑；回溯的「拍」在探索下是
  `exploration_settle`，回退后地点与 `scene_key` 一起回退。

### B4. 场景切换/选择（新增）

- 交互点携带 `scene_options`：
  - **已存在的场景**（静态剧本场景/地点 + 运行期 `scene_created` 动态场景），
    每项带 `title / participants / is_current`；
  - 固定项 **「解锁新场景」**。
- **切到已存在场景**：
  - 只列「已访问或与当前场景连通」的场景（未解锁不出现，避免跳过剧情）；
  - 人物到场衔接：目标场景的 `participants` 视为已在场；若玩家希望某角色从别处赶来，
    由 `ProducerAgent` 生成一句合理过渡（LLM）；无生产者时回退确定性模板；
    写 `scene_switch {from, to, participants}` 事件，目标场景 NPC 以「你走进来」反应；
  - 场景切换是前进式，不触发事件回溯。
- **解锁新场景**：
  - 玩家选择/输入方向 → `ProducerAgent` 生成合理 `SceneBrief`（地点、视觉摘要、
    在场角色、玩家为何能到、**锚定的父地点** `parent_location_key`）→ 写
    `scene_created` → `PainterAgent` **立即作画**；新场景进入列表；
  - 新场景**必须锚定在一个已访问/当前地点上**（地图保持连通，不能凭空跳到未解锁区域）；
    `kind=dynamic`，上限 3/会话；完全新造的地点也走这条路径；
  - Producer 判定不合理 → `scene_unlock_rejected` + 提示，不铸场景。
- **场景列表来源**：`script_scenes` + `script_locations` + 动态 `scene_created`；
  Stage2 不提供（还原期是固定图）。
- **AgentSociety 对照（调研结论）**：
  - 它**没有场景/地点抽象**，也没有「进入/离开场景」原语；唯一空间系统是
    `MobilitySpace`（AOI/POI + 路网），只提供按 person_id 的 `get_person`，**没有
    「查某地点有哪些人」的工具**；
  - **到场不广播**：`move_to` 到达只在 `env.step` 里改自己的 `status/position`，
    不产生事件；其他 agent 想知道只能主动查询；
  - **运行时不能新增环境模块/AOI/POI/agent**（`_agent_ids` 与 env modules 启动时固定）；
  - 它最接近的三样可借物：`SimpleSocialSpace` 的 group 成员集合（join/leave 幂等、锁内原子）、
    `GlobalInformationEnv` 的全局字符串广播（每步 observe 自动读到）、
    `daily_mobility` harness 的「外部编排 + 读后验证」（先设置成员/移动，再 observe 校验）。
  - **文境的取舍**：用「`participants` 成员集合 = 在场唯一事实源」+「`scene_switch` 事件 =
    显式广播」+「运行时按事件重建动态场景/角色」；这比它的查询式到场更强，且事件溯源
    天然可回溯。动态新增角色是文境独有能力，需自己承担重放/回滚正确性。

### B5. 玩家干涉世界（新增：建场景 / 拉入角色）

- 新命令 `CommandKind.INTERVENE` + `IntervenePayload{text}`（Stage3 允许）：
  玩家在「干涉输入框」里写自然语言，如「创建一个雨夜的客栈场景」「让一个乞丐加入」。
- `ProducerAgent` 解析为结构化 `InterventionIntent`：
  - `create_scene {title, participants?, visual_summary}`；
  - `add_character {name, brief, personality?, location_key?}`（**新角色**）；
  - `pull_in_character {name}`（从剧本角色池/已创建角色中拉入当前场景）；
  - `reject {reason}`。
- 校验（确定性 + staff）：
  - 预算：新场景 ≤3/会话、新角色 ≤2/会话、每轮 ≤1 次干涉；
  - canon：不得改写已发生事实/关键事件/目标；新角色不得是玩家角色；
  - 安全：内容过滤（复用媒体安全路径）；越界 → `intervention_rejected` + 提示。
- 应用（全部事件化）：
  - `scene_created {scene_key, title, participants, visual_summary}`：进动态场景注册表；
    PainterAgent 生成视觉（惰性/后台）。
  - `character_created {profile, avatar_brief, location_key, origin}`：运行时
    `CharacterAgentManager.add_character(profile)` 新增一个 NPC；PainterAgent 生成头像；
    **初始记忆为空 + 一条「为何在此」的 provenance 记忆**（可由 Producer 附带
    与既有角色的初始关系种子，默认不生成）；写入在场列表。
  - `pull_in_character {name, from_scene, to_scene}`：从剧本角色池/已创建角色中拉人；
    Producer 生成一句到场理由（如「他闻讯赶来」），写事件并让该角色入场。
  - `intervention_requested/rejected`：审计与玩家反馈。
- **回滚/重放**：动态场景与角色由 `scene_created/character_created` 事件派生；回溯到
  创建前 = 该场景/角色从未存在（运行时重建 manager/registry 时不加载）；快照不需要
  额外字段。
- **中心 agent 拉入角色**：`ProducerAgent` 可直接从剧本角色池（`script_characters`）
  拉一个当前不在场的角色进入场景（`pull_in_character`），无需新建 profile；新建角色
  走 `add_character` 生成 profile（staff LLM）→ 入池 + 入场。

### B6. 离线 tick：NPC 自主行动（无 Director）

- 触发：`session_init` 按 `last_tick_at` 补算，clamp `max_offline_ticks=3`；无定时器。
- 每 tick：Cast NPC 自主提案/行动（LLM，并行）→ Verifier → 确定性结算
  （world_fact/关系漂移/地点变化）。
- **不设计玩家选项、不跑 DirectorAgent**；需要新场景时：
  - 结算产出 `SceneBrief`（来自 NPC 行动/地点变化），**PainterAgent 生图**；
  - 新场景只记事件，图可后台生成（若费用敏感可惰性到玩家首次进入）。
- **不写详细摘要**：只写一条 `offline_hint` 系统事件（「你不在的这段时间，世界发生了
  这些事」+ 事件序列指针），前端提示并引导玩家查看时间线；随后正常放映，**跳过玩家
  行为**（从下一个玩家可行动场景继续）。
- 新场景图**立即生成**（用户要求降低延迟）；不判目标、不推进 `stage3_round_taken`；
  3 tick 上限；LLM 额度不敏感，预算只作防失控的软上限。
- 幂等：`session_ticks(session_id, tick_index) UNIQUE` claim-first；一 tick 一事务；
  `tick_id=uuid5(session_id, tick_index)`。

---

## C. 回溯修复与快照

### C0. M0 修复

**实现注记（2026-11-07，已落地）**：
- 删除 `_memory_marks`/`_mark_memories`；`GameRuntime.rollback` 改为「分支继承终点 =
  目标拍叙事事件之前 → 对新分支路径整段 `replay_from(None, prefix)`」——不依赖任何
  进程内状态，测试与生产同一条路径。
- 记忆回归由事件折叠：`CharacterAgentManager.derive_memories(events)` 在
  `replay_from()` 末尾调用（proposal→personal_log/rejected、character_speech→
  working_memory，与实时写入同构）；`replay_from(None, …)` 先 `clear_memories()`
  原地清空（保持对象身份——工具闭包持有 memory 引用）。
- 快照 `character_memories` 仍作基线缓存；只对 `latest_event_id` 之后的事件折叠，
  不双计。测试 `tests/test_rollback_memory.py` 走「快照 + 增量重放」的生产形状。
- **与草案的差异**：未新增 `SessionStore.restore(until)`。回溯的「回到目标」在
  `GameRuntime.rollback` 内完成（replay 到目标拍之前，代价 O(前缀事件)），
  Session 层无感；按目标选快照的优化留给 M8（快照带 `branch_id/sequence` 后做，
  届时 `_restore_runtime(until)` 才有可靠的定位依据）。
- **回溯目标收窄**：目标解析为「路径上 id ≤ target 的最后一个叙事事件」，即落在回合
  中段的目标回到该回合起点；首拍之前没有合法目标（`ENG_ROLLBACK_TARGET_MISSING`，
  不切分支）。UI 只提供叙事节点，行为与回溯页口径一致。
- **重放只喂活动分支**：`_restore_runtime` 原先在无快照/兜底时把
  `loaded.events`（含被放弃分支）整段重放，游标/记忆会停在被放弃的回合上；
  现统一取 `store.active_events()`（有快照时再按 `latest_event_id` 截断）。
- **重提提议落事件**：`revise_proposal` 原先只写记忆不产事件，重放后这份记忆消失、
  `rejected` 去重弱于回溯前；现在驳回重提同样写 `proposal {revised: true}`，
  保证「重放记忆 == 实时记忆」。
- 语义变更：回溯后**阶段随事件回退**（旧行为「保留当前阶段」会让状态停在 Stage3
  而事件流退到 Stage2）；`test_full_flow.py` 的断言已按新语义更新，并在 PG 用例里
  加了「重建 runtime 后状态 == 回溯现场」的生产路径断言。

原始方案：- `SessionStore.restore(session_id, *, until: RestorePoint | None)`：按「目标之前最近快照」
  （`plot_context.latest_event_id <= target`）恢复后重放到目标。
- 删除 `_memory_marks`；`derive_memories(events, names)` 在 `replay_from()` 末尾重建记忆。
- 快照 `character_memories` 只作兼容缓存；测试走生产路径。

### C1. 快照/坐标

- `snapshots` + `branch_id/sequence/label/kind`，索引 `(session_id, branch_id, sequence)`；
  `sessions` + `head_sequence`、`last_tick_at`、`script_content_version`。
- 对外统一 `(branch_id, sequence)`；`TimelineEntry` + `branch_id/event_id/sequence`；
  修正 `head_sequence` 语义。
- 不新增 checkpoint 事件；不加 `snapshots.asset_id`。

### C2. 回溯目标与 UI

- `rollback_to_event` 兼容 `target_event_id`（UUID）与旧 `target_sequence`；
  `_restore_runtime(until)` → `rollback_to` → `rollback` 事件 → 推进到交互点。
- 回溯页：存档点卡片 + 时间线 + 分支只读视图；补回游戏页 → `/game/rollback` 入口。

---

## D. 新数据库与新 schema（只建表，不迁数据）

### D1. 方案

- 在现有 Postgres 实例中新建 `wenjing_v2`；应用只连新库。
- 新库使用**合并后的单一 `0001_v2_initial`**；旧迁移链冻结/归档；新库没有
  `script_data` 等遗留列。
- **不做数据迁移**：现有数据仅临时观察；剧本重新生成后入新库；账号通过 seed 重建。
- `ScriptRepository` 只读写表；`ScriptPackage` 仍是生成/契约传输形态。

### D2. 新 schema

```
scripts（id, org_id, owner_user_id, material_id, name, description, status,
  visibility, content_version, format, replay_ready, verification）

script_characters（id, script_id, ordinal, name, public_background, appearance JSONB,
  personality_traits JSONB, speech_style JSONB, knowledge_boundary JSONB,
  is_player_playable, avatar_asset_id, fullbody_asset_id, credits JSONB,
  UNIQUE(script_id,name)）

script_scenes（id, script_id, scene_key, scene_id, ordinal, title, participants JSONB,
  visual_notes JSONB, background_asset_id, beats JSONB, is_ending, ending_id,
  UNIQUE(script_id,scene_key)）

script_scene_options（id, script_id, scene_key, option_id, label, kind,
  branch_id, target_scene_key, ending_id, ordinal,
  UNIQUE(script_id,scene_key,option_id)）

script_branches（id, script_id, scene_key, branch_id, label, title, participants JSONB,
  visual_notes JSONB, background_asset_id, beats JSONB, ending_id,
  return_mode, return_scene_key, ordinal,
  UNIQUE(script_id,scene_key,branch_id)）

script_endings（id, script_id, ending_id, title, description, kind, scene_key,
  UNIQUE(script_id,ending_id)）

script_locations（id, script_id, location_key, title, participants JSONB,
  visual_summary, scheduled_facts JSONB, ordinal,
  UNIQUE(script_id,location_key)）

session_character_states（session_id, character_id, location_key, memory JSONB,
  status, updated_at, PK(session_id,character_id)）——投影，事件/快照权威

session_ticks（id, session_id, tick_index, tick_id UUID UNIQUE, status, created_at,
  UNIQUE(session_id,tick_index)）

snapshots（+branch_id, +sequence, +label, +kind）
sessions（+head_sequence, +last_tick_at, +script_content_version）
assets（+subject_type, +subject_key；运行期资产仍记 script_id，不记 session_id）
```

### D3. 切换

1. `docker/initdb/01_create_v2.sql` 或 `make db-create-v2` 创建 `wenjing_v2`；
   `WENJING_DATABASE_URL` 指向新库；docker-compose 默认库改为 `wenjing_v2`（旧库保留）。
2. 新 baseline `0001_v2_initial.py`；`alembic/env.py` 指向新版本目录；
   `test_migrations.py` 基线表更新。
3. `make seed` 重建管理员/提示词；剧本重新生成。
4. 旧库只读保留用于观察；不写迁移脚本。

**实现注记（2026-11-07，已落地）**：
- `alembic/versions/0001_v2_initial.py` 是合并后的单一基线；旧链 0001–0012 移到
  `alembic/legacy_versions/`（不再被 Alembic 扫描，供对照/审计）。基线由
  autogenerate 生成后**补齐了服务端默认值**（模型未声明 `server_default` 的列从
  旧库回填），并与旧库 `pg_dump` 逐段比对；保留旧链手工建的
  `ix_scripts_status`（模型同步加 `index=True`）。
- 与冻结旧链的**已知等价差异**（方向都是对齐模型、更严格）：
  14 个时间戳列由可空改为 `NOT NULL`；3 个索引改名
  （`auth_sessions_token_hash_key`→`ix_auth_sessions_token_hash`、
  `idx_auth_sessions_user`→`ix_auth_sessions_user_id`、
  `idx_users_org`→`ix_users_org_id`，语义等价）；`script_generations`
  新增 `org_id`/`owner_user_id` 外键（旧链 0005 漏建）；其余仅列顺序不同。
- `alembic/env.py`：显式注入的 `sqlalchemy.url` 现在真正优先（原先底部无条件用
  Settings 覆盖，迁移测试的临时库 URL 实际无效）；只有占位符才回落 Settings。
- 新库创建：新卷由 `POSTGRES_DB=wenjing_v2` 直接创建；既有卷用
  `make db-create-v2` 补建（幂等）。应用默认 URL、`.env.example`、docker-compose
  已指向 `wenjing_v2`；旧库 `wenjing` 只读保留。
- **与草案的差异**：M2 基线仍是**当前** schema（含 `scripts.script_data`）。
  §D2/§D1 的下列内容随各自里程碑以 0002+ 增量迁移落地，**不是**被丢弃：
  `script_characters/script_scenes/script_scene_options/script_branches/
  script_endings/script_locations` 与 `scripts` 的 `content_version/format/
  replay_ready`（**表仓储里程碑**——草案曾写 M3，M3 实际只做生成期，未拆表）、
  `session_character_states`、`session_ticks`（M5/M7）、`snapshots` 与
  `sessions` 的新列（M8）、`assets.subject_type/subject_key`（资产归属细化，
  未排期）、以及「`ScriptRepository` 只读写表」。M4 运行期先继续从
  `scripts.script_data` 整包派生珊瑚图；等表仓储接管读写后再删 `script_data`。

---

## E. 里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M0 回溯修复 | 目标前快照 + 重放到目标；`derive_memories`；生产路径测试 | 重建 runtime 后回溯状态正确 |
| M1 契约波 | `DialogueLine/Ending/SceneOption/ExplorationMap` + 事件/命令/DTO；**3.0.0**（见下） | contracts 全绿；旧 fixture 兼容 |
| M2 新库 | `wenjing_v2` + v2 baseline + seed；不迁数据 | 新库可跑；剧本可重新生成入表 |
| M3 Stage2 生成期 | `divide_events` v4 + `write_dialogue` + `validate_replay` + gate 校验 + 预生成图 | 生成带选项/分支/结局/台词/图 |
| M4 Stage2 运行期 | `ReplayDirector` 珊瑚播放 + 事件/投影 + 前端；删 Stage2 free_input | 纯 IO 可玩；旧剧本不变 |
| M5 Stage3 骨架 | `exploration.py` + settle + 在场过滤 + 地点/场景切换 | 换景/切场景/目标收束可玩 |
| M6 工作人员 | DirectorAgent（选项）+ ProducerAgent（干涉）+ Painter 接线 + world_fact | 选项来自导演；建场景/拉角色可回滚；私密事实不泄漏 |
| M7 离线 tick | NPC 自主行动 + 画师新场景 + offline_hint + claim-first ≤3 | 幂等、预算内、跳过玩家行为 |
| M8 回溯/快照 | 快照列 + 坐标统一 + 回溯页 + 入口 | 存档点/回跳正确 |

（M2 可与 M0/M1 并行；M3/M4 与 M5/M6 可并行；M7/M8 后置。）

**表仓储归属（M3 后修正）**：§A2 的 `script_*` 关系表、`scripts.replay_ready`
与 `ScriptRepository` 只读表**没有单列里程碑**——它们是 M3 之后的后置项。
M4 运行期先从 `scripts.script_data` 整包派生珊瑚图；等真实查询需求出现，
再以 0002+ 增量迁移 + 仓储接管落地，届时删 `script_data`。这期间
`replay_ready` 用「包里有完整的 options/endings/dialogue」现判，不落列。

**契约版本注记（M1）**：草案写 2.9.0，但 §A4 从 Stage2 允许列表删除
`free_input` 属于 `docs/contract-change-process.md` 定义的**收紧校验
（breaking）**，按流程升 **3.0.0**（旧客户端在 Stage2 提交自由输入会被
拒绝）。新增字段/枚举本身是 minor，breaking 的只有这一条。

**契约版本注记（M5）**：新增 `switch_scene` 命令与交互点 `scene_options` 都是
加法（旧客户端不认识就不发/不显示），按流程升 **3.2.0**；3.1.0 是 M3 的草稿字段。

---

## F. 验证

- `make lint` → `make lint-arch` → `cd frontend && npm run typecheck` → `make test`
  （`WENJING_LLM_API_KEY= make test` 快速确定；PG/MinIO 先起）。
- 契约：`export_contracts` + `test_contracts` + `types.ts` 手工同步。
- 新库：baseline 升级/降级、seed、空库启动。
- 新测试：`test_rollback_*`（生产路径）、`test_replay_director.py`、
  `test_game_exploration.py`、`test_director_agent.py`（选项设计）、
  `test_producer_agent.py`（干涉解析/预算/canon）、`test_dynamic_cast.py`
  （新角色创建/回滚/重放）、`test_world_facts.py`（private 不泄漏）、
  `test_exploration_ticks.py`、`test_script_repository.py`。
- 事件登记表测试：枚举 `EVENT_*`，断言重放与投影都有分支。
- 端到端：生成带图剧本 → gate → Stage2 纯 IO（主干/干扰回跳）→ Stage3
  （NPC 行动/导演选项/场景切换/玩家建场景或拉角色/画师生图）→ 断线重登离线 tick
  → 回溯页回跳。

---

## G. 风险

| 严重度 | 风险 | 缓解 |
|---|---|---|
| S1 | 回溯 bug 未修 | M0 先行 + 生产路径测试 |
| S1 | 非法 dialogue/options 落库 | save_package 前 validate_all；gate 后重跑 |
| S1 | 动态角色/场景回滚不干净 | 全事件化 + 重放测试 + 快照前重建 manager |
| S1 | 新事件漏登记 | 事件枚举登记测试 |
| S2 | 玩家干涉破坏 canon | Producer 校验 + 预算 + 关键事件不可改 + 内容安全 |
| S2 | 导演选项质量/延迟 | 结构化输出 + 确定性回退 + 每轮 1 次 |
| S2 | 离线 tick 费用 | 3 tick 上限 + 每 tick 预算 + 惰性/后台生图 |
| S3 | 场景切换与地点移动语义重叠 | M1 合并为地点切换，M2 再拆 |
| S3 | 新库切换窗口 | 停写 → 建库/迁移/schema → 切 URL；旧库保留 |

---

## 附录：已定与待确认

已定：
- ProducerAgent 独立于 Director，命名 `ProducerAgent`（制作人）；
- 场景切换提供「已存在场景列表 + 解锁新场景」；解锁由 Producer 生成合理地点并作画；
- 离线新场景图立即生成；
- LLM 额度不敏感，预算只作防失控软上限（每轮 ≤1 次干涉、新场景/新角色数量上限
  仍保留用于叙事一致性，不用于省钱）。

待确认 / 待调研：
1. 解锁新场景的边界：已定「必须锚定已访问/当前地点，`kind=dynamic`，上限 3/会话」，
   是否允许完全新造的地点独立于探索地图（当前：不允许，必须挂父地点）。
2. 新角色的初始关系种子：默认只给「为何在此」的 provenance，不生成与既有角色的关系；
   若需要更好的戏剧性，可由 Producer 附带 1–2 条初始关系（建议后置为可选）。
3. 到场过渡：已定「切已有场景用 Producer 生成一句衔接（失败回退确定性模板）；
   拉人由 Producer 生成到场理由」。
4. AgentSociety 场景/到场调研已完成，结论已并入 B4（无场景抽象、无到场广播、
   不能运行时加模块/角色；借成员集合 + 全局广播 + 读后验证）。
