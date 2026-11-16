# Stage3 自由探索与编年史：链路 / 记忆 / Prompt 设计 v2

> 状态：设计草案（2026-11-10，方向调整版）
> 关系：本文**修正** `docs/design/stage3-free-exploration.md` 的 Stage3 运行时部分，
> 并替代 `docs/prompts/runtime-agents.md` 中 GameMaster / stage3 goals 相关设计。
> v2 的关键变化：部署形态改为「机房内每学生一台设备运行一个游戏实例」，
> 记忆改为实例级 + 角色模板/工厂；编年史改为**限知视角 + 每轮增量**；Stage3
> **没有显式结束**。

## 0. 决策摘要

1. **部署形态**：机房内每学生一台设备运行一个游戏实例；账号系统后期再做。
   学生端与教师端暂时都挂在同一服务上，但每个实例是**单实例、单局**的。
2. **记忆模块实例化**：用 `CharacterTemplate`（角色模板）+ `CharacterFactory`
   （角色工厂）创建 `CharacterInstance`，记忆绑定到**实例**而不是账号/session，
   不再需要在 prompt 里做多租户隔离。存储走 `MemoryStore` 端口，**默认用本地
   文件系统（每个实例一个目录）**；SQLite 单文件作为低代码替代，Postgres 保留给
   服务端/测试；后续接账号系统再迁移。
3. **删除 `GameMasterAgent`**：旧剧本推进与 Stage3 续写目标一并移除；它不负责
   教学纠正，也不应干涉世界演进。
4. **删除 Stage3 目标体系与轮次上限**：`stage3_goals_set` / `stage3_goal_achieved`、
   `goals.py::derive_goals`、`Verifier.judge_stage3_goals`、`stage3_rounds`、
   前端 GoalTracker 全部退出主链路。
5. **Stage3 没有叙事结局**：不设轮次上限、不设自动收束、不写 ending。实例在
   学生关闭设备/教师结束课堂时自然停止；`exit_game` 只作为客户端关闭动作，
   写生命周期转换但不产生叙事终点。
6. **`Chronicler` 保留**：staff、零工具、不出场、不修改世界。每轮只写**本轮的
   增量段落**（`world_chronicle` 事件），不重写全文；`derive_chronicle` 负责拼接。
7. **编年史对角色是限知视角**：`derive_chronicle(events, viewer=…)` 只返回该角色**目睹/在场**
   的增量；全量编年史只给 staff/教师。`knows` 仍是角色私有的秘密/个人经历，
   不进编年史、不给其他角色。
8. **删除废字段**：`not_knows` 从角色 prompt/生成语义中移除；`Stage3Goal` /
   `stage3_goals` / `stage3_rounds` / `STAGE_DIRECTIVES["stage2"]` 下线。
9. **Educator 暂不实现**：后续作为教师端手动触发的评估功能，接教育行业 LLM；
   本版不进入实时链路。

---

## 1. 部署形态与记忆模块

### 1.1 为什么这个方向能简化记忆

原来的多用户后端要求：同一进程内多局并存、按 `session_id` / user / org 做鉴权、
prompt 里不能混入别人的状态。现在每学生一台设备跑一个实例：

- 一个实例只有一局、一个玩家、一组角色；
- 记忆不需要跨用户隔离，只需要**实例内角色隔离**（谁在场、谁听过什么）；
- 角色可以来自**静态模板**，记忆从模板种子 + 本局事件生长，不再依赖复杂的
  账号级记忆检索；
- 存储可以从 Postgres 降级为本地文件系统（实例目录），降低部署门槛；服务端
  Postgres 保留给测试、教师端聚合或后续账号系统。

> 注意：这是对上一版「不用文件系统、只用 Postgres」的**有依据的反转**。上一版
> 拒绝文件系统是因为多用户后端要自己补鉴权/事务/并发；单实例部署把这些成本
> 移除了。如果教师端要跨设备聚合，仍应通过服务端接口，不要让教师端直接读
> 学生设备的本地文件。

### 1.2 角色模板与角色工厂

```python
@dataclass(frozen=True)
class CharacterTemplate:
    """静态角色模板：可复用的身份、性格、说话风格、知识种子。"""
    template_id: str
    name: str
    public_background: str
    personality_traits: tuple[str, ...]
    speech_style: str
    knowledge_seeds: tuple[str, ...]   # 秘密/个人经历/少数人知道的事
    playable: bool = False

class CharacterFactory:
    """按模板 + 本局剧本创建角色实例；记忆绑定到实例。"""
    def create(self, template: CharacterTemplate, *, memory: MemoryStore) -> CharacterInstance: ...
```

- `CharacterTemplate` 是静态资产（可来自生成期产物、教师预置或手工模板），
  不随局变化。
- `CharacterInstance` 持有 `CharacterMemory` + `MemoryStore` 句柄；同一模板在
  不同局里互不共享记忆。
- 运行期新增角色（干涉 `add_character`）也走工厂，模板由上游生成/临时构造。
- 现有 `CharacterAgentManager` 可以收编为工厂的运行时注册表；不要新建第二套
  角色生命周期。

### 1.3 `MemoryStore` 端口

```python
class MemoryStore(Protocol):
    def append_event(self, event: GameEvent) -> None: ...
    def events(self, *, viewer: str | None = None) -> Iterable[GameEvent]: ...
    def chronicle(self, *, viewer: str | None = None) -> str: ...
    def private_knowledge(self, character: str) -> tuple[str, ...]: ...
```

- 默认实现：本地文件系统（实例目录，见 §1.4）；SQLite 单文件作为低代码替代。
- 服务端/测试实现：现有 Postgres 事件表；接口不变。
- 事件仍然是权威；文件/SQLite 只是实例内的持久化载体，不是第二份真相。
- 快照、回溯、编年史派生都建立在 `MemoryStore` 之上；换存储不换语义。

### 1.4 文件系统布局与原子性

可以，单实例部署下文件系统是合理默认。推荐布局：

```text
<instance_root>/<instance_id>/
  meta.json              # 实例元数据：script_id / player_role / schema_version / created_at
  events.jsonl           # append-only 事件日志，一行一个 GameEvent
  snapshots/
    seq-000001.json      # 状态快照（缓存，latest_event_id 对齐）
  memory/
    <character>.json     # 角色记忆缓存（派生，可重建）
  assets/                # 本地媒体缓存（可选）
  instance.lock          # 单写者锁
```

约束：

- **单写者**：一个实例同一时间只允许一个进程写；启动时拿 `instance.lock`，
  避免两个窗口/进程同时写。
- **追加语义**：`events.jsonl` 用 `O_APPEND` 写入并 `fsync`；启动时丢弃最后一行
  不完整 JSON。
- **快照原子替换**：先写临时文件再 `os.replace`，避免半截快照。
- **派生不落库**：编年史、角色记忆、资产索引都从事件派生；`memory/` 与
  `snapshots/` 只是缓存，删掉可重建。
- **崩溃恢复**：读 `meta.json` → 最新快照 → 重放快照之后的 `events.jsonl`；
  损坏快照直接忽略。
- **迁移**：所有读写走 `MemoryStore`，未来换 SQLite/Postgres 不动上层。
- **教师端**：跨设备聚合通过服务端 API，不要让教师端直接读学生实例目录。
- **平台**：机房若是 Windows，`os.replace` 仍原子；避免依赖 POSIX-only 文件锁，
  锁用文件创建/独占打开实现。

如果不想自己处理 JSONL 的追加/恢复，SQLite 单文件是更省事的等价选择：事务、
WAL、崩溃恢复都是现成的，仍然满足「本地单文件、无服务端」。

---

## 2. 目标链路

```
玩家命令（choose_option / free_input / act / switch_scene / intervene）
  │
  ├─ choose_option / free_input / act
  │    → ExplorationDirector.settle（确定性：地点化摘要 + 处境 + 在场）
  │    → 在场 CharacterInstance × N 反应（LLM，可流式）
  │    → Chronicler.write（LLM，只写本轮增量）→ world_chronicle 事件
  │    → Director.design_options（LLM）→ 交互点
  │
  ├─ switch_scene
  │    → 确定性换景（scene_switch）
  │    → 目标地点在场角色反应
  │    → Chronicler → Director → 交互点
  │
  └─ intervene
       → WorldBuilder.parse_intervention（LLM，只解析）
       → 运行时确定性校验 / 应用（scene_created / character_created / ...）
       → 回到同一回合头：Character 反应 → Chronicler → Director
```

- **没有自动结束**：以上循环可以无限进行；没有 goals、没有轮次上限、没有
  `stage3_end`。实例关闭即停止。
- Stage2 仍然有课文结局（canonical/alternate）并询问是否进入 Stage3；进入
  Stage3 后不再有「结局」概念。
- 世界写入只有一条路：玩家命令 → 确定性结算/校验 → 事件。Chronicler、Director、
  WorldBuilder 都不直接改世界。
- 失败不阻塞：Chronicler 失败回退确定性摘要；Director 失败回退已验证提议/地点
  选项；WorldBuilder 失败 fail-closed；Character 失败跳过该角色。

---

## 3. 记忆与上下文分层

| 层 | 内容 | 来源 | 去向 | 可见性 |
|---|---|---|---|---|
| Base rules | 角色扮演规则、输出边界 | 代码常量 | system（所有角色共享） | 公开 |
| Persona | 姓名、背景、性格、说话风格 | `CharacterTemplate` | user | 该角色 |
| Private knowledge (`knows`) | 秘密、亲身经历、少数人知道的事 | 模板种子 + 本局事件 | user | 仅该角色 |
| Chronicle (viewer) | 该角色目睹的编年史增量 | `world_chronicle` 事件 + 在场过滤 | user | 仅该角色 |
| Chronicle (full) | 全局编年史 | `world_chronicle` 事件 | staff/教师 | 工作人员/教师 |
| Recent speech | 最近公开发言 | `speech_log` / 事件 | user 或工具 | 按场景裁剪 |
| World facts | 结构化世界事实 | `world_fact` 事件 | 工具 | public + audience private |
| Proposals / rejected | 私有行动日志 | `CharacterMemory` | 工具（可选） | 仅该角色 |

### 3.1 `knows` 的语义

- 只放**秘密、个人经历、只有他/少数人知道的事**，用于制造误会、矛盾与冲突。
- 不进编年史；不进其他角色的上下文；不当作公共事实。
- 角色 prompt 里明确：「只在合适的时候透露或暗示；不要为了炫耀而倾倒秘密」。
- `not_knows` 删除：不知道的事不写；不再用「禁出清单」把秘密本身提示给模型。

### 3.2 编年史的两种视图

- **Chronicler 写入**：每轮只写增量 `world_chronicle {round, text, present,
  location_key, covers_event_id}`；不重写全文。
- **`derive_chronicle(events, viewer=None)`**：
  - `viewer=None`：全量拼接（staff/教师）；
  - `viewer=name`：只拼接 `present` 包含该角色的增量（限知视角）。
- **角色只会拿到 `derive_chronicle(events, viewer=…)`**；全局编年史不进角色 prompt。
- 私密 `world_fact`（`visibility=private`）仍只进 audience 角色的工具视图，
  绝不进编年史。

### 3.3 上下文策略

- 现阶段不做摘要压缩：限知编年史 + 最近事件 + 私有 `knows` 全量进 user。
- 每轮两个额外 LLM 调用（Chronicler + Director）；取消了角色多次 memory 工具
  往返，净成本可控。
- 后续若单场过长，再加窗口压缩；不在本版范围。

---

## 4. Prompt 设计

### 4.1 CharacterAgent：共享 system

所有角色共用同一段 system，保留前缀缓存；人设、私有知识、限知编年史全部进 user。

```text
# 身份
你是这个课堂剧情世界里的一个角色。你不是 AI 助手，不解释规则，不跳出角色。

# 行为边界
- 只写你这个角色此刻说的话和做的事。
- 不写旁白、镜头说明、系统提示，不复述本提示词。
- 不替玩家说话或行动，不描述玩家没有做过的动作，不替玩家决定结果。
- 不编造未发生的情节、不存在的人物或地点。
- 只使用你被给予的信息；没有依据的事不要当作事实说出。

# 输出
- 提议：一句话，具体可执行，符合身份与当前处境。
- 回应：只写这个角色此刻的一句话，可在括号里补一句简短的动作或神态。
```

### 4.2 CharacterAgent：每轮 user

```text
<persona>
姓名：{name}
背景：{public_background}
性格：{personality_traits}
说话风格：{speech_style}
</persona>

<private_knowledge>
以下是你独有的秘密、亲身经历，或只有少数人知道的事。它们不在公开编年史里。
{knows 逐条}
使用原则：只在合适的时候透露或暗示；不要当作人人皆知的公共事实；可以用它制造
误会、紧张或冲突，但不要为了炫耀而倾倒秘密。
</private_knowledge>

<chronicle>
{derive_chronicle(events, viewer=…)}
</chronicle>

<recent>
{最近公开发言 / 当前处境}
</recent>

<task>
{stage3 指令}
{本轮任务：提议 / 回应玩家行动}
</task>
```

- 删除 `STAGE_DIRECTIVES["stage2"]`；角色只在 Stage3 运行。
- 删除 `<not_knows>`。
- `derive_chronicle(events, viewer=…)` 为空时整段省略。
- `view_*` 工具保留作深挖，但不再是每次行动前的必调项；prompt 不再写
  「先查询再行动」。

### 4.3 Chronicler：system

```text
# 角色与边界
你是这个剧情世界的编年史作者。你用第三人称，把已经发生的事写成一段连贯的
叙事，作为这个世界不断续写的正文。
- 只写已经发生的事，不预测、不评价、不替角色做决定。
- 不写角色的内心秘密；秘密只属于角色本人。
- 不编造未发生的情节、人物或地点。
- 文风简洁、具体、有画面感，像连载小说的下一段，不是流水账。
- 只输出本轮的增量段落，不要重写前文，不要标题、不要解释、不要 Markdown。

# 输出
一段 200–400 字的第三人称叙事，只写本轮发生的事。
```

### 4.4 Chronicler：user（增量）

```text
【上一段编年史】
{chronicle_tail}

【本轮发生的事】
地点：{location_title}
玩家行动：{action_text}
在场角色：{present}
角色回应：
- {speaker}：{text}
世界事实（公开）：
- {fact}

请只写本轮的一段，不要重写上文。
```

- 触发：一轮 NPC 反应之后、Director 出选项之前。
- 事件：`world_chronicle {round, text, present, location_key, covers_event_id}`。
- 失败降级：`settle.summary` + 本轮公开发言拼成确定性段落，仍写事件，不阻塞。
- 不挂工具、不修改世界。

### 4.5 Director：调整

- 输入去掉 `goals`；新增 `chronicle_tail`（可使用全量或当前地点视角，staff 可见）。
- 保留：地点、画面、玩家角色、在场、当前处境、教学重点、最近角色回应、
  上一轮选项、公开世界事实。
- 输出仍是 2–4 条选项，`dimension` 只记日志。
- 失败 → 空列表 → 运行时回退已验证提议/地点选项。

### 4.6 Verifier：调整

- 只保留 `verify_proposal`；删除 `judge_stage3_goals` 与 goal judge prompt。
- 提议验证失败仍按 `conditional_pass` 降级，不阻塞。

### 4.7 WorldBuilder：不变

### 4.8 Educator：暂不实现

- 后续形态：教师端手动触发，读取实例事件 + 全量编年史，输出面向教师的评语；
- 接教育行业 LLM；不在实时链路、不修改世界状态；
- 产物可作为教师报告或 `educator_review` 事件，另行设计。

---

## 5. 事件 / 契约 / 配置改动

### 5.1 新增

- `EVENT_WORLD_CHRONICLE = "world_chronicle"`
  - payload：`{round, text, present, location_key, covers_event_id}`
  - 进 `contracts/enums.EventType`、`event.py`；投影默认不进玩家消息流，
    只作为 staff/教师/内部读模型。
- `derive_chronicle(events, viewer=None) -> str`：拼接增量，限知过滤。
- 生成期 `design_exploration` 节点：产出 `ExplorationMap`（起点、地点、
  participants、visual_summary），写入 `ScriptPackage.exploration`；位置在
  `final_audit` 之后。**这是删除旧剧本路径的前置条件。**
- `CharacterTemplate` / `CharacterFactory` 已落地；`CharacterInstance` 与
  `MemoryStore` 端口/文件系统实现已落地（2026-11-11，见 §6.1）。
- `MemoryStore` 端口（`domain/game/memory.py`）+ 文件系统默认实现
  （`infrastructure/memory_store.py`）：
  - 端口方法：`open` / `close` / `append_event` / `sync_events` /
    `read_events` / `chronicle` / `private_knowledge` /
    `save_private_knowledge`（全 async；限知过滤只在 `chronicle(viewer=…)`，
    `read_events` 返回镜像全量，见 §3.2）。
  - 实例目录 `<root>/<instance_id>/`：`meta.json`（剧本标题 + 创建时间 +
    schema 版本）+ `events.jsonl` + `instance.lock` +
    `memory/<character>.json`（派生缓存）；`snapshots/` 暂未启用。
  - `events.jsonl`：`O_APPEND` + `fsync`，崩溃残行在下次打开时隔断；按
    `(branch_id, event_id)` 增量去重镜像事件流（`GameRuntime._flush_events`），
    去重键在**落盘成功后**才登记（写失败下一轮重试）；回溯放弃的旧分支行
    保留可审计。
  - `instance.lock`：`O_CREAT|O_EXCL` 单写者锁；持有进程已死时按 PID 探测
    接管（`memory_store_stale_lock_reclaimed`）。PID 探测只在 POSIX 上做——
    Windows 的 `os.kill(pid, 0)` 会终止进程，故非 POSIX 平台一律保守拒绝
    接管；创建后、写 PID 前崩溃留下的空锁按年龄（60s）判残留回收。
  - 配置：`WENJING_MEMORY_BACKEND=null|fs`、`WENJING_MEMORY_FS_ROOT`
    （组合根装配，`fs` 时会话级句柄缓存复用同一实例目录锁；进程关闭时
    `SessionApplication.aclose()` 统一释放锁与 fd）。
  - 角色记忆缓存：命令收尾时 `CharacterInstance.persist_private_knowledge`
    把有界窗口刷到 `memory/<character>.json`；失败只记日志。缓存缺失时读侧
    返回空、由运行期下一条命令重写（完整离线重建见 §7）。

### 5.2 删除 / 停止写入

- `GameMasterAgent` 整类删除；`advance_plot` / `confirm_direction` /
  `design_interaction` / `design_stage3_goals` 一并删除。
- `stage3_goals_set` / `stage3_goal_achieved` 停止写入；事件枚举保留读兼容。
- `goals.py::derive_goals` / `fallback_goals` / `parse_goal_list` 删除或弃用。
- `VerifierAgent.judge_stage3_goals`、`build_goal_judge_prompt`、
  `GOAL_JUDGE_SLOTS`、`STAGE3_GOALS_SLOTS` 删除。
- `EngineConfig.stage3_rounds` 删除；Stage3 不设轮次上限。
- 前端 `GoalTracker` / `EndingCard` 的目标区删除；`RuntimeState.stage3_goals`
  先保留空数组兼容，下一主版本删除。
- `STAGE_DIRECTIVES["stage2"]` 删除。
- `not_knows` 停止注入与生成；契约字段暂留，后续主版本删除。

### 5.3 结束语义

- Stage2：到达课文结局后，仍可选择「进入 Stage3」或结束本局。
- Stage3：**没有叙事结局**。不设轮次上限、不写 ending/结局文案、前端不弹结局卡。
  客户端关闭/教师结束课堂即停止；`exit_game` 只作为关闭动作——写一条生命周期用的
  `stage_transition {stage:"ended"}` 让会话可恢复、客户端可收束，但该转换不携带任何
  结局字段。
- `EndingCard` 只服务 Stage2 结局；Stage3 不再展示。

---

## 6. 落地顺序

1. **实例化部署**（✅ 2026-11-11）：`MemoryStore` 端口 + 文件系统默认实现；
   `CharacterTemplate` / `CharacterFactory` 收敛现有 `CharacterAgentManager`
   的创建路径（`CharacterInstance` 持 agent + 实例记忆句柄）。
2. **生成期**：新增 `design_exploration` 节点与校验，让所有新剧本带
   `ExplorationMap`。
3. **运行期退行路径**：确认新剧本不再走 `exploration=None` 分支后，删除旧剧本
   `_run_cycle_head` 分支、`design_interaction` 与 `GameMaster`。
4. **目标体系下线**：停写 goals 事件、删 goal judge、删 `stage3_rounds`、
   清理前端目标展示；保留空字段兼容旧会话。
5. **Chronicler**：新增事件、增量派生、prompt bundle、每轮调用与降级；接入
   `_stage3_exploration_head`（反应之后、Director 之前）。
6. **Character prompt 重写**：共享 system + persona/private_knowledge/
   chronicle(viewer)/task 的 user；删 `stage2` / `not_knows`。
7. **Director / Verifier 输入调整**：Director 读编年史、去掉 goals；
   Verifier 只留提议验证。
8. **契约 / 前端**：`RuntimeState`、`Stage3Goal`、GoalTracker、EndingCard 清理；
   `contracts/fixtures`、`jsonschema`、`types.ts` 同步。
9. **测试**：
   - 实例/工厂：模板实例化、实例间记忆隔离、MemoryStore 换实现不改语义。
   - 生成期：所有剧本包带 exploration；`design_exploration` reject 重跑。
   - 运行期：无 goals / 无轮次上限 / 无 Stage3 ending；编年史重放/回溯正确。
   - 知识边界：`knows` 不进编年史；`derive_chronicle(events, viewer=…)` 只含目睹增量；
     private fact 不进编年史。
   - Prompt：system 指纹、Chronicler 增量与降级、角色 prompt 不含 stage2/not_knows。
   - 确定性 LLM：`FakeLLMService` / `DeterministicAgentLLM` 增加 Chronicler 路由键。

---

## 7. 待拍板

1. **文件系统细节**：`events.jsonl` 是否按大小轮转、快照频率、是否需要 SQLite
   替代？建议默认 JSONL + 快照，接口用 `MemoryStore` 屏蔽，后续可换 SQLite。
   （2026-11-11：JSONL 镜像 + 单写者锁已落地；轮转/`snapshots/`/SQLite 仍未做。）
2. **教师端如何访问实例**：每个实例本地存储时，教师端是同一服务上的一个视图，
   还是通过服务端聚合？跨设备聚合不要让教师端直接读学生本地文件。
3. **Stage2 → Stage3 的入口**：课文结局后是否仍允许「结束本局」；进入 Stage3
   后确认没有结局卡。
4. **`knows` 的生成来源**：生成期从教材/剧本产出，还是教师模板预置？两者可能
   并存，需要模板优先级。
5. **契约 breaking**：`not_knows` / `Stage3Goal` 是保留空字段兼容，还是直接升
   主版本删除？
6. **Educator 的教师端形态**：手动触发粒度（整局/某轮/某场景）、输出是否入库、
   接哪家教育 LLM。
7. **镜像的回溯语义**（2026-11-11）：`events.jsonl` 保留回溯放弃的旧分支行
   （可审计），但镜像未持久化分支血缘，`read_events()` / `chronicle()` 按
   镜像全量派生，不会自动裁剪到活动分支。要离线正确复现活动编年史，需要在
   镜像里记录分支血缘（或改为按活动路径索引）。角色记忆缓存同理：缺失时只能
   由运行期重写，尚不能纯离线重建。
