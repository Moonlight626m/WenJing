# 游玩链路前端增补设计（Stage2 还原 / Stage3 探索 / 回溯）

> 状态：设计草案 v1（2026-11-09）
> 依据：M4–M8 已落地实现的前端覆盖审计；协议以
> `docs/design/play-through-architecture.md` 为准。
> 范围：只讨论前端界面与逻辑。需要后端补的少量 payload 单列在第 5 节，
> 均为 `ServerMessage.payload` 的加法，不动 `CONTRACTS_SCHEMA_VERSION`。

## 0. 原则

- **不新增页面**：全部增补落在 `/game` 与 `/game/rollback` 现有组件上。
- **前端不派生第二份真相**：消息流来自事件投影；场景、台词、选项、目标、事实
  都以服务端下发的 payload 为准，前端只做展示与派生视图（如按幕分组）。
- **册 / 台两套面不混用**：`/game` 恒暗（`data-surface="stage"`），回溯页是册面；
  新组件沿用语义令牌（`border-rule` / `text-ink` / `glow-*`），不写调色板类。
- **能力缺口分两类**：能纯前端补的先做；需要结构化字段的标「后端 payload」，
  在字段到位前不靠解析中文文本硬猜。

## 1. 组件与数据流

```
WS / REST
  ├─ session_init ───────────────► gameStore（stage / branch / scene / goals / interaction）
  ├─ narrative / character_speech / system / asset_ready
  │                               └─► messages、sceneKey、currentAsset、goal 快照
  └─ interaction ────────────────► ActiveInteraction
                                   ├─ options（抉择）
                                   └─ scene_options（换景 + 在场）

game-screen
  ├─ GameHud（阶段、连接、回溯入口）
  ├─ GameStage（背景）
  ├─ StageFigures / CastDock（立绘与头像）
  ├─ InteractionCard（选项 / 自由输入 / 换景 / 干涉）
  └─ TranscriptPanel（剧情 / 原文 / 角色）
        ├─ MessageStream
        ├─ OriginalTextPanel（sceneIdOf 对照）
        └─ RollbackBar（快捷回溯 + 全量回溯页入口）
```

相关位置：

| 主题 | 文件 |
|---|---|
| 消息渲染 | `frontend/src/components/message-stream.tsx` |
| 交互卡（选项/换景/干涉） | `frontend/src/components/interaction-card.tsx` |
| 舞台与侧栏 | `frontend/src/components/game-screen.tsx`、`stage-figures.tsx`、`cast-dock.tsx` |
| 原文对照 | `frontend/src/components/original-text-panel.tsx` |
| 结局卡 | `frontend/src/components/ending-card.tsx` |
| 会话状态 | `frontend/src/stores/gameStore.ts` |
| 回溯页 | `frontend/src/components/rollback/rollback-timeline.tsx` |

## 2. Stage2 还原

### 2.1 分支场景的原文对照（P0，前端 bug）

**现状**：`original-text-panel.tsx` 的 `sceneIdOf` 只匹配 `^scene:(\d+)$`。
重演分支节点的 scene_key 是 `scene:{id}::branch:{bid}`（`replay.py` 的
`_BRANCH_SEP`），解析为 `null`，导致：

- 分支场景里「对照原文」入口消失（`game-screen.tsx` 的 `sceneHasOriginal`）；
- 原文页 `currentIndex = -1`，不展开当前场景。

**设计**：把分支节点映射回父场景 id。

```ts
const match = sceneKey ? /^scene:(\d+)(?:::branch:.*)?$/.exec(sceneKey) : null;
```

**边界**：

- `ending:{id}` 保持 `null`（结局没有对应课文场景；`finished` 后原文页全展开）。
- `loc:{key}` 保持 `null`（探索地点不是剧本场景）。

**验收**：进入分支节点时「对照原文」按钮出现，原文页展开并高亮父场景；
主线节点行为不变。

### 2.2 台词、旁白、选项、结局渲染（现状，保持）

- 预写台词落 `character_speech`（`source=replay`），旁白落 `narrative`；
  前端消息流直接渲染，**不重画珊瑚图**。
- 决策选项来自交互点 `options`；玩家选中后后端写 `replay_choice` 与
  `replay_node_entered`，前端按 `system`/`narrative` 展示。
- 回主干、分支终点、结局都由后端的事件投影决定；前端的场景标题/背景只跟随
  `scene_key`/`current_asset`。

### 2.3 结局卡增强（P1，需后端 payload）

**现状**：`replay_ending_reached` 只投影成一句「到达结局：X」的系统消息；
结局卡只有统计信息与续写目标，不显示具体结局名/类型。

**设计**（字段到位后）：

- 系统消息 payload 增加 `ending: { ending_id, title, description, kind }`；
- 结局卡标题下补一行结局名；`kind` 用标签区分：
  - `canonical` → 「正史结局」（`Tag tone="accent"`）
  - `alternate` → 「另一种结局」（`Tag`）
  - `distractor` → 「偏离结局」（`Tag tone="warn"`）
- 字段缺失时退回现状，不解析消息文本。

### 2.4 预写台词的舞台提示（P2，需后端 payload）

`DialogueLine.stage_direction` 目前在投影里被丢弃（`_event_text` 的
`character_speech` 分支只取 `text`）。字段补齐后，台词上方用一行小字
（`text-2xs text-ink-faint`）显示舞台提示，不改变现有台词排版。

## 3. Stage3 探索

### 3.1 当前在场（P0；先做静态名单，动态成员需后端一行修正）

**数据**：`interaction.scene_options` 的当前项带 `participants`（服务端已下发，
`is_current=true`）。

**注意**：该字段目前取的是**地点静态名单**（`ExplorationDirector.scene_options`
的 `location.participants`），不含 `pull_in_character` / `add_character` 拉进来的
运行期成员；而「在场」的权威判定是 `ExplorationDirector.present_names`
（静态名单 + 动态成员 ∩ 已创建角色）。因此分两步：

- **第一步（纯前端）**：先用 `scene_options` 当前项的 `participants` 渲染；
  动态拉入的角色在换景/重新设计交互点后会缺席于这一行，属于已知上限。
- **第二步（后端一行修正）**：`_scene_options` 里把 `participants` 换成
  `self.exploration.participants_at(location, self._world)`，与结算/反应同一口径；
  或把 `exploration_settle.present` 透传进叙事消息 payload。两种都只动投影，
  不新增事件。

**设计**：

1. 交互卡标题下增加一行：

   ```
   当前在场：沈先生、船夫
   ```

   - 空列表显示「这里只有你」；
   - 人数与场景选项写的是同一份 `participants`，不重复计算。
2. `CastDock`：
   - 当前在地点的角色保持原样；
   - 不在场的角色头像降低到 40% 不透明度，保留可点（角色档案仍可看）；
   - 窄屏 `+N` 折叠逻辑不变。
3. 立绘（`StageFigures`）只在说话人里取，不因不在场而额外处理。

**边界**：

- 旧剧本（`scene_options` 为空）不显示「当前在场」行，行为与改动前一致。
- 动态角色可能不在 `characters` 档案里（见 3.4），在场行用名字即可。

**验收**：换景后在场行随交互点更新；不在场角色在 CastDock 中被弱化；
无 `scene_options` 时不渲染；拉人入场后（后端修正到位）在场行包含新成员。

### 3.2 换景（现状已可用，补细节）

现状：`InteractionCard` 用地点 pill 列表渲染 `scene_options`，当前地点置灰，
`switch_scene` 前进式切换。

建议增补：

- pill 上显示地点名即可，`title` 保留在场名单（现有）；
- 当前地点 pill 增加「当前」小标签（现有「（当前）」文案保留）；
- 换景命令在途时整组禁用（现有 `busy`），并保持焦点不跳；
- 换景后的场景标题/背景由 `scene_switch` 叙事消息更新，前端不本地先行切换。

### 3.3 干涉反馈（P1，需后端 payload 或结果字段）

**现状**：玩家提交 `intervene` 后，成功与否只体现为消息流里的一条系统气泡
（「你的干涉：…」/「制作人没有应允：…」），输入框立刻清空，反馈容易被忽略。

**设计**：

- 干涉输入旁保留最近一次结果（本地状态，不落库）：
  - 成功：`Tag tone="ok"`「已生效」+ 一句「新地点/新角色已加入」；
  - 拒绝：`Tag tone="warn"`「未应允」+ 原因（来自 `intervention_rejected.reason`）；
- 每轮最多一次的限制做成输入框副标题的一部分（现有「每轮可以干涉一次」），
  被拒绝后不锁输入框，允许换说法重试；
- 可靠识别依赖消息 payload 的 `event_type`（第 5 节）；字段未到位前不解析中文。

**验收**：干涉成功/被拒都能在输入区就近看到结果；不打断消息流滚动。

### 3.4 动态角色（P1，先做前端兜底）

**现状**：`characters` 只在 `setScriptInfo`（剧本包加载）时写入；
`character_created` / `pull_in_character` 只投影成系统文本。结果：

- 动态角色说话时能上舞台（`StageFigures` 对未知名字降级为名牌）；
- 但 `CastDock` 与角色档案页看不到他们。

**设计（第一阶段，纯前端）**：

1. 从消息流收集「运行期登场」的名字：
   - `character_speech.speaker` 中不在剧本包 `characters` 里的名字；
   - 系统消息文本前缀「新角色「X」登场」「「X」来到了现场」；
   - 合并去重，生成 name-only 档案（`is_player_playable=false`）。
2. `listedCharacters` 接受一个可选的「额外名字」列表，追加在剧本角色之后。
3. 角色档案页给这类角色标 `Tag`「运行期登场」，背景描述暂用系统消息里的
   公开背景（能拿到就显示，拿不到就留空）。

**第二阶段（需后端 payload）**：`character_created` 带结构化 `character`
（name / public_background / personality_traits / location_key / origin /
avatar_brief），前端直接补全档案与头像占位；`pull_in_character` 至少带
`name`（角色档案若已在 `character_created` 里就复用），不再从文本提取。

**边界**：回溯到创建之前，相关事件消失；前端按「消息流里还有没有这个名字」
自然回落，不需要额外的删除逻辑。

### 3.5 世界事实与离线提示（P1，需 `event_type`）

- **世界事实**：public 事实是一条系统消息。字段到位后渲染成带标题的小卡片
  （「世界事实」+ 文本），与普通阶段提示区分；private 事实服务端整体过滤，
  前端不做旁路。
- **离线提示**：`offline_hint` 在重连补发时混在消息流里。字段到位后：
  - 在消息流顶部显示一条可点击横幅：「你离开期间，世界发生了一些事 → 查看进度」，
    链到 `/game/rollback?id=`；
  - 横幅只显示一次（按 `seq` 去重，本地 state 记录已关闭的 seq）；
  - 不阻塞游玩，不自动跳转。
- 字段未到位前维持现状（普通系统气泡），不做文本匹配。

### 3.6 续写目标（P2，纯前端）

`GoalTracker` 已有 `achieved` 快照。建议：

- 目标从未达成变为达成时，条目做一次短暂高亮（`animate-rise-in` 或
  `glow-border` 一瞬），不新增数据；
- 结局卡已有「目标达成 N/M」，保持不变。

### 3.7 无障碍与 E2E 约束

- 现有 E2E 依赖的可读名不能改：`回溯进度` 链接、`/回到 #\d+/` 按钮、
  `确认回溯` 按钮、「回溯到这一句」按钮。
- 页面上只能有一个 `<select>`（回溯栏），新控件不要引入第二个。
- 新交互控件补 `aria-label` / `aria-pressed` / `aria-busy`；颜色不作为唯一状态
  （在场/不在场同时用不透明度与文案）。

## 4. 回溯页（M8 已落地）

本轮已完成：分支切换竞态与错误重试、分支 pill 编号、只读语义、存档点解析到
最近可回溯拍、存档点与时间线联动、确认条失败保留可重试。

后续可选（不在本次范围）：

- 分支树可视化（M8 明确未落地）；
- 存档点保留策略（当前每命令一行，读侧取最近 20）；
- 学生空间 `GameRow` 的「回溯」次级入口（设计只要求游戏页入口）。

## 5. 需要的后端 payload 增补

全部是投影层 `project_messages` 的加法；`ServerMessage.payload` 是
`dict[str, Any]`，**不升契约版本**。字段到位前前端保持现状。

| 字段 | 事件 | 用途 | 优先级 |
|---|---|---|---|
| `event_type` | 所有消息 | 区分 `offline_hint` / `world_fact` / `intervention_rejected` / `character_created` 等，做专属样式与就近反馈 | P1 |
| `scene_options[].participants` | 交互点 | 并入动态拉入/新增成员，与 `present_names` 同一口径（或透传 `exploration_settle.present`） | P0 |
| `character` | `character_created`、`pull_in_character` | `character_created` 带完整档案（名字/背景/性格/地点/origin/头像简述）；`pull_in_character` 至少带 `name` | P1 |
| `ending` | `replay_ending_reached` | 结局名/描述/kind，结局卡展示 | P1 |
| `stage_direction` | `character_speech`（重演台词） | 台词舞台提示 | P2 |
| `intervention` | `intervention_requested` / `intervention_rejected` | 结构化结果（kind / reason / applied）供就地反馈 | P1 |

另一条**后端侧**的「反馈消化」缺陷（不属于前端，但直接影响 UI 可解释性）：

- `_on_input` 对 `choose_option` 只把 `option_id` 放进 `PlayerAction`，角色
  反应时只看到「选项 N」，看不到选项文案；而目标判定与结算拿的是解析后的
  `action_text`。应在写 `player_action` 事件与 `_collect_reactions` 时带上
  选中的文案（详见 `docs/prompts/runtime-agents.md` 第 8 节）。

## 6. 实施顺序与验收

1. **P0 前端独立**：2.1 分支原文对照 → 3.1 当前在场（静态名单）→ 3.4 动态角色（name-only）。
2. **P0 后端一行**：3.1 在场并入动态成员（`participants_at`）。
3. **P1 后端加法**：`event_type` → 3.3 干涉反馈 / 3.5 离线提示 / 3.4 完整档案
   → 2.3 结局卡。
4. **P2**：2.4 舞台提示、3.6 目标高亮、回溯页可选项。

每步验收：

- `npm run typecheck`、`npm run lint`、`npm run build`；
- `tests/e2e/core-flow.spec.ts` 不回归；
- 新增交互在窄屏（375px）与舞台面手动走一遍；
- 涉及新 payload 的，先在 mock fixture 里补样例，再改组件。
