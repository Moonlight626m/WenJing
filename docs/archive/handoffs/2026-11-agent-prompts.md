# 归档：WenJing 运行期 Agent Prompt 优化交接（2026-11-09）

> 状态：**已实现并归档**（2026-11-09）。本文是任务发起时的交接快照，保留旧名
> （`ProducerAgent` / `ScreenwriterAgent`）与旧行号；现行行为见
> `docs/prompts/runtime-agents.md` 与代码（`WorldBuilderAgent` / `GameMasterAgent`、
> `domain/agents/prompting.py`）。
>
> 实现摘要：选项文案闭环、Director/WorldBuilder/Character/Verifier/GameMaster
> 六段式 prompt、Verifier 结构化判定、全仓改名、PromptBundle + 槽位契约 + 版本/
> golden；记忆 Phase 1 是后续独立任务（见 `docs/design/memory-phase1-handoff.md`）。

---

# 交接：WenJing 运行期 Agent Prompt 优化

> 生成于 2026-11-09，供下一个 session 专门做 agents 提示词优化。
> 仓库 `/home/moonlight/projects/WenJing`，分支 `dev`，HEAD `693c536`，工作区干净。

## 1. 为什么开这个 session

上一轮已完成并提交的是**前端增补 + 投影 payload 加法**（回溯页、Stage2 原文对照、
Stage3 在场/动态角色/干涉反馈/结局/离线提示）。设计文档与 prompt 设计标准已经写好，
但**运行期 Agent 的 prompt 本体仍是旧版**：任务、规则、输出格式全塞在 user 消息里，
system 只有一句身份。这个 session 的目标是把它们按六段式重写并让「消化玩家反馈」
这条链路真正闭环。

不要重做前端工作；前三笔提交已完成：
`4be723c`（文档）、`e99f146`（原文对照/在场/动态角色）、`693c536`（payload 结构化 + Stage3 UI）。

## 2. 唯一设计依据

**`docs/prompts/runtime-agents.md`** 是这次工作的主文档，先完整读它：

- §2 Agent 一览（谁参演、谁是 staff、各自输入输出与失败策略）
- §4 六段式标准（角色与边界 / 任务 / 输入契约 / 规则与优先级 / 输出契约 / 示例，+可选自检）
- §5 现行 Prompt 全文（**改之前先对照**）
- §6 Director v2 草案（给玩家选项）
- §7 Producer v2 草案（消化干涉）
- §8 玩家反馈的三条通道 + 一个 P0 后端 bug
- §9 维护规则、§10 开放问题

架构语义以 `docs/design/play-through-architecture.md` §7.1–§7.2 为准。
前端 payload 字段（`event_type` / `character` / `ending` / `intervention` / `stage_direction`）
已在 `693c536` 落地，见 `docs/design/play-through-frontend.md` §5。

## 3. 代码地图（prompt 都是代码内联，改完即生效）

| 位置 | 内容 |
|---|---|
| `backend/app/domain/agents/director.py:28-85` | `DirectorAgent.design_options`；system 在 55-62，user 在 64-77 |
| `backend/app/domain/agents/director.py:88-112` | `parse_options`：2–4 条、去重、支持 `{label}` 对象 |
| `backend/app/domain/agents/producer.py:75-133` | `ProducerAgent.parse_intervention`；system 98-100，user 104-124 |
| `backend/app/domain/agents/producer.py:136-178` | `parse_intent`：未知 kind / 缺字段 fail-closed |
| `backend/app/domain/agents/character.py:96-122` | `CharacterIdentity.to_system_prompt()`（稳定 system） |
| `backend/app/domain/agents/character.py:42-45` | `STAGE_DIRECTIVES`（stage2/stage3） |
| `backend/app/domain/agents/character.py:164-191, 271-276` | `react_to` 与 `_build_user_message` |
| `backend/app/domain/agents/verifier.py:24-51` | `verify_proposal`（**占位实现**，见 §6.6） |
| `backend/app/domain/agents/verifier.py:54-92` | `judge_stage3_goals`（JSON 契约已可用） |
| `backend/app/domain/agents/screenwriter.py:117-162` | `design_stage3_goals`（只有这里是 LLM） |
| `backend/app/domain/game/game_runtime.py:689-746` | `_on_input`：choose_option 的文案解析与事件写入 |
| `backend/app/domain/game/game_runtime.py:977` | `_design_director_options` 的实际上下文装配 |
| `backend/app/domain/game/game_runtime.py:1520-1551` | `_collect_reactions` |
| `backend/app/domain/agents/tools.py` | CharacterAgent 的 7 个只读工具 |
| `backend/app/domain/game/goals.py:91-134` | `parse_goal_list` / `parse_achieved` / `extract_json_object` |
| `backend/app/infrastructure/llm/fake.py:37-50` | 确定性 LLM 的**关键词路由**（见 §6.3） |

## 4. 建议的实施顺序

### P0-1：修「choose_option 只看到选项编号」

这是文档 §8 的 P0，直接决定角色能不能消化玩家选择：

- `_on_input`（`game_runtime.py:689-718`）已经算出了 `action_text`，但
  `PlayerAction.text` 仍是 `None`，`player_action` 事件 payload 也只写 `text: null`。
- 后果：`CharacterAgent.react_to` 的 `detail = player_action.text or f"选项 {N}"`
  → NPC 只听到「选项 2」；回放/审计也只剩编号。
- 修法：写 `player_action` 前把解析出的选项文案填进 `PlayerAction.text`（或新增
  `label` 字段并同步 `_collect_reactions` / `react_to` / 事件 payload / 重放）。
- 补测试：选 `choose_option` 后，`character_speech` 的输入侧能看到文案；
  `player_action` payload 里带文案；回溯重放后一致。

### P0-2：Director（给玩家选项）按 §6.5 落地 v2

- 现状问题（§6.2）：2 条选项却要求覆盖三类维度、看不到上一轮选项、看不到角色
  最近回应、输出无差异维度、没有硬约束。
- prompt 重写为六段式；system 放稳定规则 + 输出 schema + 正/反例，user 只放本轮变量。
- **上下文还需要补三项**（§6.3，都已在运行时可得，不需要新事件）：
  - `recent_speeches`：`state.speech_log[-3:]`
  - `last_options`：上一轮选项（可放 `_RState` 或运行期局部缓存，不进事件）
  - `public_facts`：`WorldState.facts` 的 public 项
- 输出契约建议 `{"options":[{"label","dimension"}]}`，`dimension ∈ goal|relationship|environment`。
  `parse_options` 已兼容字符串；**建议只记日志、不强校验**（避免一次失误就回退兜底）。
- 补测试：真实/固定 LLM 返回含 `dimension` 的对象数组仍能解析；重复项去重；2 条以下回退。

### P1：Producer（消化玩家干涉）按 §7.3 落地 v2

- 加入**严格判定顺序**（改写事实/超预算 → reject；名单内 → pull_in；名单外新人 →
  add_character；新地点 → create_scene；拿不准 → reject）。
- few-shot 正例/反例（尤其 pull_in vs add_character 的混淆）。
- 把「预算为 0 应直接 reject」写进 system 规则，`reject.reason` 要求「学生能读懂、
  能给出替代说法」。
- `parse_intent` 的长度限制与 fail-closed 行为保持不变（`producer.py:136-178`）。

### P1：CharacterAgent 的 system 补边界

- 现有 system 只有身份 + 知识边界 + 一行工具说明；缺「只以角色身份回应、
  不写旁白/系统提示、不替玩家行动、不描述玩家未做的动作」。
- 注意：**system 是稳定部分**，`create_agent(system_prompt=...)` 每角色构造一次；
  改这里不会影响工具闭包与记忆机制。
- `react` 的 user 里应明确输出体裁（一句台词 + 可选动作神态），并带上选项文案（P0-1 之后）。

### P2：Verifier 与 Screenwriter

- `verify_proposal` 是占位实现：`_parse_verdict` 只按文本里有没有 `reject`/`conditional`
  判档（`verifier.py:95-102`），不是真实质量评估。**先问用户**要不要把它做成
  结构化 JSON 判定（会改变运行期行为与测试），再动 prompt。
- `design_stage3_goals` 可顺手改成六段式，但优先级最低；`advance_plot` /
  `confirm_direction` 是确定性实现，不是 prompt 问题。

## 5. 验证口径

- 快速、确定性：`WENJING_LLM_API_KEY= make test`（约 70 秒，走 `DeterministicAgentLLM`）。
- 单文件：`cd backend && uv run pytest tests/test_director_agent.py tests/test_producer_agent.py -q`
- 改动涉及运行期链路时至少跑：`test_game_runtime.py`、`test_intervention.py`、
  `test_exploration.py`、`test_revise_proposal.py`、`test_agent_tools.py`、
  `test_world_view_scoped.py`。
- 顺序：`make lint` → `make lint-arch` → `WENJING_LLM_API_KEY= make test`。
  前端 typecheck 只在动契约镜像时才需要。
- **`make test` 会清空所连数据库**：跑完补 `make migrate && make seed`。
- 按 `AGENTS.md`，功能/修复完成后用 **`feat-review`** 审查（Standards + Spec 双轴），
  修完再汇报。commit 用 Conventional Commits，描述中文。

## 6. 六个必须知道的约束与陷阱

### 6.1 运行期 prompt 不进 `prompts` 表

`backend/app/domain/prompts/` 只服务**生成期 workflow**（`collect_materials`、
`write_script` 等），有 DB 覆盖与 `VERSION` 机制。运行期 Agent prompt 是代码内联，
改完即生效，**不要** `make seed`、**不要**升 `VERSION`、**不要**搬进 `domain/prompts/`。

### 6.2 六段式是标准，但别把示例和答案一起输出

`extract_json_object` 用贪婪正则 `r"\{.*\}"`（`goals.py:122`）。system 里的示例
不会进模型输出，没问题；但如果模型在答案前后又复述示例 JSON，解析会拿到跨两段
对象的非法 JSON → 返回 `None` → 回退。prompt 里要明确「只输出一个 JSON 对象」；
若想更稳，可另开一笔把提取器换成 `json.JSONDecoder().raw_decode` 逐段尝试（非 prompt 改动，需用户认可）。

### 6.3 确定性 LLM 按关键词路由，改 user 消息会破测试

`infrastructure/llm/fake.py:45-50`：

```python
user = messages[-1]["content"]
if "验证 Agent" in user or "你是验证" in user: return "pass"
if "react" in user: return self._react_text
return self._proposal_text
```

- 角色任务依赖 user 里的 `任务：react`；把指令改成中文（如「任务：回应」）会让
  确定性测试拿到「提议」文本，行为漂移。
- Director/Producer 在确定性模式下本来就解析失败并回退（返回的不是 JSON），
  这是设计好的降级；相关单测用 `_FixedLLM` 不受影响。
- 若要改这些关键词，**同时**更新 `fake.py` 与 `test_director_agent.py` /
  `test_producer_agent.py` 的期望。

### 6.4 staff 与参演的知识边界是机制，不是提示词礼貌

- CharacterAgent 只拿 `WorldView.bind(name)` 的裁剪视图 + 7 个只读工具；
- Director/Producer/Verifier 看全量，但**不得把私密事实写进角色台词或选项**；
- 私密 `world_fact` 在投影层与时间线都被显式过滤，不要在前端或 prompt 里旁路。

### 6.5 输出必须 fail-closed，结果不能直接展示给学生

- Director 解析失败/少于 2 条 → 空列表 → 回退已验证提议 → 两条确定性兜底；
- Producer 未知/缺字段 → `reject`；
- 目标判定解析失败 → 本轮不达成；
- 角色失败 → 跳过该角色。
降级日志键：`director_options_degraded`、`producer_parse_degraded`、
`goal_judge_degraded`、`stage3_goals_degraded`、`verify_degraded`。

### 6.6 没有运行期真实 LLM 评测脚本

`backend/scripts/` 下只有生成链路的 `smoke_workflow.py` / `e2e_real_flow.py`，
没有针对 Director/Producer/Character 的评测器。若要量化「JSON 成功率 / 重复率 /
结果句比例 / 四类意图混淆矩阵」（文档 §6.7、§7.5），需要新写一个
`backend/scripts/eval_runtime_prompts.py`（需要真实 key，手动运行，不进 CI）。

## 7. 需要用户拍板的开放问题

1. Director 的 `dimension` 只记日志还是做强覆盖度校验（不满足就回退）？
2. 是否把运行期 staff prompt 迁进 `prompts` 表换取 DB 覆盖与版本化（代价是多一套 seed/迁移）？
3. `VerifierAgent.verify_proposal` 要不要从占位实现升级为真实结构化判定？这会改变运行期行为。
4. 是否要为 prompt 优化写一个真实 LLM 评测脚本（会产生 API 费用）？

## 8. 建议调用的 skills

| Skill | 用途 |
|---|---|
| `grilling` | 动笔前把 prompt 的规则冲突、边界情况、fail-closed 顺序压一遍；尤其 Director 的「数量 vs 覆盖维度」矛盾 |
| `writing-for-agents` | 更新 `docs/prompts/runtime-agents.md` 时保证文档写法对 agent 可读 |
| `feat-review` | 按仓库要求，改动完成后做 Standards + Spec 双轴审查（`AGENTS.md` 强制） |
| `tdd`（可选） | 先写解析/行为测试再改 prompt 时用 |
| `claude-api`（可选） | 只有在需要确认 provider 采样参数/模型行为时；本仓走 OpenAI-compatible，通常不必 |

## 9. 开工前 30 秒检查

```bash
cd /home/moonlight/projects/WenJing
git status --short          # 应为空
git log --oneline -3        # 确认 HEAD 是 693c536 或更新
```

若发现工作区有未提交改动，先问用户——可能有另一个并行 session
（「自由探索阶段实现」）在同一 checkout 工作。
