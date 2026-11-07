# Stage3 自由探索（探索沙箱）设计

> 状态：草案 v2（待立 GitHub Issue 拆任务后实施）
> 日期：2026-11-03（v1 为 2026-11-02，早于 PR #72 合入）
> 依据：`docs/research/agentsociety-architecture-study.md`（AgentSociety v2 调研快照）
> 范围：仅运行期 Stage3（`STAGE3_EXTENDING`）。Stage2 还原、生成 workflow、流式/音频、
> 持久化事务层不动；本设计全部落在 `domain/` 与既有服务接缝之上，不改命令入口、
> 不改 CAS 事务拼写、不引入 Ray/tick/仿真时钟。

## 0. v1 → v2：对齐 PR #72 已落地的基线

PR #72（契约 2.8.0）已把「续写目标」实现为**事件派生**：

- 进入续写写 `stage3_goals_set`，每轮判定达成写 `stage3_goal_achieved`；
- `domain/game/goals.py::derive_goals` 从活动分支事件折叠出目标状态，
  **不进 `_RState`** ——回溯/重放/重连天然对账；
- 判定由验证 Agent（LLM）做，解析不了视为「本轮未达成」；出题失败退回教学重点；
- 全部达成即收束，`stage3_rounds`（3）降为兜底上限。

v1 设计稿有三处被这次落地推翻或简化，本文已修正：

1. **探索状态不进 `_RState`**：v1 的 `ExplorationState{location_key, visited…}`
   字段方案废弃，改为与目标同构的事件折叠（`derive_exploration`）。
2. **不新增 `travel` 命令**：地点选项走既有 `choose_option`（交互点选项里带
   `location_key`），命令入口与契约零扩张；M3 的 free_input 归一化也走同一内部路径。
3. **达成判定沿用 LLM 验证 Agent**，不再是 v1 的「纯规则匹配」——PR #72 已经过
   产品判断；规则只留给「线索/地点解锁」这类可枚举结构。

## 1. 三个机制：AgentSociety → 文境

AgentSociety 的运行期由三层构成：agent 生命周期（record 重建）、tick 循环
（`society.step`）、沙箱 env 交互（`EnvBase` + Router）。逐层对照文境现状与
自由探索要补的缺口。

### 1.1 Agent 生命周期

| AgentSociety | 文境对应物 | 自由探索要做的 |
|---|---|---|
| 每 tick `from_workspace → step → to_workspace → close`，agent 对象不常驻 | `CharacterAgent` 会话级常驻；每命令跑 1–3 轮 executor；记忆在进程内、`_memory_marks` 快照支撑回溯 | **「在场」成为回合级生命周期开关**：不在场的 NPC 本回合不生成（不耗 LLM）、不进 `speech_log`、不进目标判定输入 |
| 单 agent 失败 → `{"ok": False}` 记录，同批继续（但 tick 级抛错） | `gather(return_exceptions=True)`，失败只记日志 | 保留：失败 NPC = 本回合缺席（降级），**不采纳** tick 级硬失败 |
| workspace 文件是每步权威 | 事件流是权威，记忆是缓存 | 不新增持久化；探索进度 = 事件折叠 |

**不重建 agent 对象**：文境只有 2–6 个角色，常驻对象才能保住 LangChain executor
的 `system + tools` 前缀缓存（AgentSociety 自己实测的 52%→82% 前提就是
「messages 一次构建只 append」）。按 record 每轮重建会把这笔收益全部还回去。

生命周期的唯一新增是**在场判定**：

```python
# domain/game/exploration.py
def present_names(progress, registry, active_names) -> list[str]:
    """当前地点在场者 = 地点 participants ∩ 会话角色。
    地方没列到的角色视为「在别处」，本回合缺席。"""
```

### 1.2 tick 运行

AgentSociety 的 `society.step()`：推时钟给 env → 切批 fan-out → gather →
**env.step 统一结算** → 时钟前进 → checkpoint。文境把它映射为**一条玩家命令 =
一个 tick**：

| AgentSociety | 文境已有 / 新增 |
|---|---|
| `set_current_time`（fan-out 前同步世界上下文） | 结算前先 `derive_exploration(events)` 得到当前地点/在场者，scoped 视图据此回答 |
| 切批 `step_agent_batch` | `asyncio.gather`（已有） |
| env.step 统一结算（确定性代码） | **新增 `ExplorationDirector.settle`**：换景校验、`exploration_settle` 事件、方向载荷——纯确定性 |
| 时钟前进 | `stage3_round_taken`（已有，`player_action` 重放自增） |
| `to_workspace` checkpoint | `SessionStore.commit`（已有，不变） |
| tick 级失败 | **不采纳**：单角色失败降级缺席 |

自由探索回合模型（替换 Stage3 现行线性 cycle）：

```
玩家命令（choose_option：NPC 提议或地点选项 / speak / free_input）
  → player_action 事件（已有）
  → 结算（确定性）：travel 校验 → 换景 → exploration_settle 事件
                    {location_key, scene_key, summary}
  → 在场 NPC 并行反应（gather；scoped 视图读到的是新地点）
  → 目标判定（既有验证 Agent，1 次调用）
  → 收束检查：全达成 → 结束（M1 沿用现状）；exploration_max_rounds 兜底
  → 下一交互点：在场 NPC 提议 + 地点选项 + free_input
```

**可见性决策（沿用 v1，定死）**：回合内 NPC 并行、互不可见；所有发言在结算时
统一进 `speech_log`。NPC 间「接话链」是 M5 可选（默认 0 层，预算硬上限）。

**与现状的关键差异**：Stage3 不再走 `advance_plot` / `confirm_direction`（它们把
游标 clamp 到最后一个 beat，正是「复读结局」的根源），也不再
`broadcast_plot_context` / `broadcast_direction`；方向载荷与叙事摘要改由结算产出。

### 1.3 沙箱 env 交互

AgentSociety 的「沙箱」是三层进程/目录隔离 + Router（CodeGen 等），**没有一层是
安全边界**（调研 §4）。文境不引入任何代码执行，对应物是**知识边界**：

| AgentSociety | 文境对应物 |
|---|---|
| EnvBase `@tool` + Router 把环境能力暴露给 agent | `WorldView` scoped 只读工具 + LangChain tool calling（ADR-0004，已有） |
| agent 可通过工具**修改** env | 文境 agent **只读**：世界写入只经「提议 → 验证 → 结算 → 事件」 |
| Router/CodeGen/restricted exec | 不引入。工具 schema 就是接口，不需要中间层 |
| 每个 agent 一个 workspace 目录（物理隔离） | 每个角色一个 scoped 视图（知识隔离）：只看到自己所在地点的公开信息 |

自由探索新增的环境视图（`domain/agents/tools.py` 同构注册）：

- `view_exploration`：当前地点、已访地点、目标与达成态、在场者；
- `view_scene_speech_log`：**当前地点**的公开发言（`speech_log` 按地点裁剪，
  复用现有逐角色裁剪逻辑，`_in_scene` 增加 `loc:` 命名空间解析）。

写路径保持不变：玩家移动来自选项/命令；NPC 只能「提议」，经验证后进交互点。
这也意味着 **agent 消息构建不需要动**（system + tools 前缀不变，缓存纪律不受影响；
地点上下文由 agent 主动调工具获取，或经 user message 的 `extra` 注入）。

## 2. 组件设计

### 2.1 `LocationRegistry`（剧本包 → 运行时）

```python
# domain/game/exploration.py
class LocationRegistry:
    """探索地图的只读索引。键是稳定字符串（不进事件的就是派生）。"""

    def __init__(self, exploration: ExplorationMap, active_names: list[str]): ...

    def start_key(self) -> str: ...
    def get(self, key: str) -> ExplorationLocation | None: ...
    def participants(self, key: str) -> list[str]:
        """地点在场者（与 active_names 求交；地点没列到的人视为在别处）。"""
    def scene_key(self, key: str) -> str:
        """`loc:{key}` —— 与剧本场景 `scene:{id}` 分属两个命名空间。"""
    def visual_description(self, key: str) -> str:
        """地点 visual_summary，供配图管线（与 scene_visual_description 同一声明）。"""
```

地图空（旧剧本 `exploration=None`）→ registry 为 None → 整个自由探索退行到
现状（线性 beat + 3 轮上限），不阻塞存量游玩。

### 2.2 事件派生 `derive_exploration`

```python
@dataclass(frozen=True)
class ExplorationProgress:
    location_key: str          # 当前地点（无事件时 = start_location_key）
    visited: tuple[str, ...]   # 到访过的地点，按序去重
    moves: int                 # 换景次数（与 round 计数无关）

def derive_exploration(events: Iterable[Any], *, start_key: str) -> ExplorationProgress:
    """折叠 `exploration_settle` 事件。与 goals.derive_goals 同构：
    接受 GameEvent 或其 dict 形状；无事件 = 起始地点。"""
```

回滚换分支后自动回到分支上的地点——与目标达成状态同一套对账机制，不需要额外
同步代码。

### 2.3 `ExplorationDirector.settle`（确定性结算器）

```python
@dataclass(frozen=True)
class Settlement:
    location_key: str             # 结算后的当前地点
    moved: bool                   # 是否换景（决定是否写事件/请求配图）
    summary: str                  # 叙事摘要（plot_advancement 的替代来源）
    direction_payload: dict       # {conflict, context}，来自探索语境而非 beat
    travel_options: list[TravelOption]   # 上一交互点本回合可去的地点

class ExplorationDirector:
    """纯确定性、无 LLM、无基础设施依赖。两个方法：
      start(progress) -> Settlement          进入续写时的首次落位
      settle(progress, action, registry) -> Settlement
    """
```

- `travel` 合法性（地点存在）错 → 回退为「留在原地 + 摘要说明」，
  不抛错、不卡死（玩家输入错不该中断游戏）。
- `direction_payload`：冲突 = 剩余未达成目标的具体语境；context = 当前地点标题 +
  在场者。目标全达成时换成结局语境。
- 达成判定**不在 director 里**（沿用 PR #72 的验证 Agent）；director 只读
  `goals` 的当前状态决定 `ending` 语境。

### 2.4 在场过滤与失败降级

`_collect_reactions` / `_collect_proposals` 的角色来源从 `active_names()` 改为
`present_names(progress, registry, active_names)`。Stage2 行为不变（无 registry 时
回退全量，与现状一致）。失败 NPC 不写 `speech_log`、不进目标判定输入——与现有
`gather(return_exceptions=True)` 语义一致，只是显式化为「缺席」。

### 2.5 交互点与地点选项

`InteractionPoint.options` 增加可选字段 `location_key`（仅地点选项）：

```python
{"id": 3, "text": "去当铺", "proposed_by": "system",
 "location_key": "pawnshop"}
```

玩家 `choose_option` 选中它 = 移动意图；运行时按 `location_key` 走 §2.3 的 settle。
选项 id 仍是顺序编号，前端沿用现有选项渲染，只需识别 `location_key` 时改样式。
**命令入口、`CommandKind`、`contracts/commands.py` 全部不动。**

### 2.6 配图：复用现有管线（一处泛化）

`_request_scene_asset` 现在接收 `ctx: Scene | None`；泛化为
`(stage, scene_key, description, current_asset)`，两个调用方各自提供描述：
剧本场景用 `scene_visual_description`，探索地点用 `LocationRegistry.visual_description`。
`assets` 事件索引按 `scene_key` 存，`loc:` 键天然可用；槽位兜底对 `loc:` 为 None。
其余（`SceneAssetIntent → asset_jobs → 后台任务`）不变。

### 2.7 流式 / 音频 / 命令入口：不动

反应仍走 `_react` 的 speech_sink 多轨出口；命令端点仍是唯一输入；WS 瞬态消息与
事件流划分不变。

## 3. 契约与事件

### 3.1 新契约（`contracts/script.py`）

```python
class ExplorationLocation(VersionedContract):
    key: str                       # 稳定键（事件里存它）
    title: str
    participants: list[str]        # 在场角色名（须 ⊆ 剧本角色）
    visual_summary: str            # 配图描述（与 scene_visual_description 同一声明）

class ExplorationMap(VersionedContract):
    start_location_key: str
    locations: list[ExplorationLocation]
    ending_brief: str = ""         # 结局语境文案（M2 结局提议用）

ScriptPackage: + exploration: ExplorationMap | None = None
```

`Stage3Goal` 契约已存在（`contracts/runtime.py`，PR #72 起被消费）。M4 生成期
把目标写进 `ExplorationMap` 还是沿用现有 `design_stage3_goals` 的输出，实施时二选一
——**本设计不预设**，M1 继续走现有目标设置路径。

### 3.2 新事件

```
EVENT_EXPLORATION_SETTLE = "exploration_settle"
# payload: { location_key, scene_key, summary, moved }
```

- 进事件流（有 seq、权威）；进入续写时写一条（首次落位），之后每次换景写一条。
- 重放分支：设置 `state.scene_key`、`plot_log` 追加 summary；**不碰
  `beat_cursor`**（这是它不能复用 `plot_advancement` 的原因）。
- `session_projection` 增加该类型的投影（时间线叙事条目 + 地点标题）；
  前端目标面板沿用 PR #72 的 `stage3_goals` 投影。
- `direction` 事件复用，payload 来源换成 `Settlement.direction_payload`。

### 3.3 同步清单

| 处 | 内容 |
|---|---|
| `backend/app/contracts/script.py` | `ExplorationLocation` / `ExplorationMap` / `ScriptPackage.exploration` |
| `contracts/fixtures/` | 含 exploration 的 ScriptPackage 样例（手工） |
| `contracts/jsonschema/` | `scripts/export_contracts.py` 导出 |
| `frontend/src/lib/contracts/types.ts` | 手工镜像（无生成器，易漏） |
| `domain/game/event.py` | `EVENT_EXPLORATION_SETTLE` |
| `contracts/runtime.py` | 如需暴露当前地点到 RuntimeState（M2 再定，M1 不需要） |

## 4. 编码文件树（新增 / 修改）

```
backend/app/
├── contracts/
│   ├── script.py                 [改] +ExplorationLocation +ExplorationMap；ScriptPackage.exploration
│   └── events.py                 [改] +exploration_settle（若事件类型在此登记）
├── domain/
│   ├── game/
│   │   ├── exploration.py        [新] ExplorationProgress / derive_exploration /
│   │   │                              LocationRegistry / ExplorationDirector / Settlement
│   │   │                              ——深模块，纯确定性，只 import domain 内模块
│   │   ├── game_runtime.py       [改] _RState 不变；_on_enter_stage3 首次落位写
│   │                              exploration_settle；_on_input stage3 分支走 settle；
│   │   │                              _run_cycle_head 拆出 stage3-exploration 分支
│   │   │                              （-advance_plot -confirm_direction -broadcast）；
│   │   │                              _collect_reactions/_collect_proposals 在场过滤；
│   │   │                              _replay_event +EVENT_EXPLORATION_SETTLE 分支；
│   │   │                              _request_scene_asset 泛化签名
│   │   ├── event.py              [改] +EVENT_EXPLORATION_SETTLE
│   │   ├── world_view.py         [改] +view_exploration / view_scene_speech_log；
│   │   │                              _in_scene 支持 loc: 命名空间
│   │   └── engine_config.py      [改] +exploration_max_rounds（默认 12；stage3_rounds
│   │                                  保留给无地图旧剧本）
│   ├── agents/
│   │   ├── tools.py              [改] 注册两个新视图工具
│   │   ├── screenwriter.py       [改] stage3 交互点增加地点选项；advance_plot/
│   │   │                              confirm_direction 在 stage3 不再被调用（保留给 Stage2）
│   │   └── character.py          [不改]（结构不变；地点上下文经工具获取）
│   └── prompts/defaults.py       [不改]（M3 translator 才新增键）
├── services/
│   ├── session_projection.py     [改] exploration_settle 投影
│   └── scene_assets.py           [不变]
└── tests/
    └── test_game_exploration.py  [新] 派生/结算/在场过滤/重放回溯/退行模式
frontend/src/
├── lib/contracts/types.ts        [改] 手工镜像新契约
└── app/game/                     [改] 地点选项渲染 + 当前地点展示（复用现有选项组件）
```

集中而少：新逻辑收敛在 `exploration.py` 一个深模块；`game_runtime.py` 只做分支
接线；`character.py` 零改动。

## 5. 快照 / 回溯 / 重放

- **快照**：`export_state` 不新增段——探索进度与目标一样从事件派生
  （与 PR #72 的 goals 同策略）。场景背景仍按 `state.scene_key` 解析。#53 已有机制。
- **重放**：`exploration_settle` 分支重建 `scene_key` + `plot_log`；`derive_exploration`
  随后从同一批事件折叠出地点，二者天然一致。
- **回溯**：`rollback_to` 语义不变；换景事件被回滚 = 那次移动从未发生，地点与
  目标达成态都随分支回退。
- **并发**：单 worker、命令串行不变；NPC 并发 `gather(return_exceptions=True)`；
  单角色失败缺席本回合，不杀世界（明确不采纳 AgentSociety 的 tick 级硬失败）。

## 6. 成本护栏与可观测性

1. **在场过滤本身就省钱**：不在场 NPC 零调用；每回合 LLM 调用 = 在场人数
   （反应）+ 提议/验证（既有预算）+ 至多 1 次目标判定。
2. **安全阀**：`exploration_max_rounds`（12）到顶礼貌收尾；全达成提前收束。
3. **确定性结算零 LLM**：换景、方向、地点选项全在代码里。
4. **（可选，独立立项）** `llm_usage.cached_input_tokens` 列 + prompt 前缀回归
   断言——验证「agent 常驻 + 前缀稳定」的省钱效果；不是本设计的前置条件。

## 7. 里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1 骨架 | `exploration.py`（registry/派生/settle）；`ScriptPackage.exploration` 四处同步；`exploration_settle` 事件与重放；`_on_input`/`_run_cycle_head` stage3 分支；在场过滤；地点选项；退行模式 | 旧剧本行为不变；新地图剧本可换景、目标收束、回溯正确 |
| M2 收束交互 | 全达成后从「硬结束」改为结局提议交互（复用 Stage2 结局确认形状）；换景配图走既有管线；RuntimeState 暴露当前地点 | 玩家可拒绝结束继续探索；换景出图 |
| M3 free_input 归一化 | `ExplorationTranslator`（唯一 Stage3 LLM 缝）：free_input → travel/speak，失败回退 speak；prompts 表新键 | 「我要去当铺」正确换景；输入畸形回退发言 |
| M4 生成期 | workflow 增 `design_exploration` 节点（final_audit 之后）；地图进剧本包 | 生成剧本带地图；reject 重跑仅该节点 |
| M5（可选） | NPC 接话链（默认 0 层、预算硬上限）；cached_input 计量与前缀回归断言 | 接话受预算约束；缓存命中率可观测 |

## 8. 风险与未决

- **地点与剧本场景的关系**：`loc:` 与 `scene:` 两个命名空间并存；Stage2/旧剧本
  不受影响。若地图地点想复用剧本场景的视觉设定，M4 生成节点可直接把
  `Scene.title/visual_notes` 写进 `ExplorationLocation`，不做运行时映射。
- **更换默认轮数**：`stage3_rounds=3` 对自由探索太短，用独立配置
  `exploration_max_rounds=12`，旧剧本继续走 3，互不影响。
- **收束后硬结束 vs 结局提议**：M1 沿用 PR #72 的硬结束（改动最小），M2 再改
  交互（产品决定；已有 `confirm_ending` 命令提示语可复用）。
- **free_input 里的移动意图**：M1/M2 不识别（一律按发言处理），M3 由 translator
  覆盖；这是有意的分期，避免 M1 引入 LLM 判定导致「说话被判成走路」。
- **目标判定质量**：沿用验证 Agent 的「宁可少判」策略；地图地点与目标无关时
  只是多走几步，不会误判收束（未达成就是未达成）。
