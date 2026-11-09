# 交接：角色记忆 Phase 1（已实现并归档）

> **状态（2026-11-09）：已实现。** 本文件保留当时的设计与代码地图，作为历史快照，
> 不追改；行号可能已漂移。现行实现见：
> - `backend/app/domain/agents/tools.py`（`view_my_memory` 返回 `recent_speech`）
> - `backend/app/domain/game/game_runtime.py`（`plot_entries_for`、有界
>   `plot_log` / `speech_log`）
> - `backend/app/domain/game/world_view.py`（`plot_log` 取最近窗口）
> - `backend/app/domain/agents/character.py`（5 层记忆、有界 `CharacterMemory`）
> - `backend/app/services/session_store.py`（快照保留策略）
> - 现行说明：`docs/prompts/runtime-agents.md` §5.2 / §11、
>   `docs/design/play-through-architecture.md` §6.2–6.3、`CONTEXT.md`
>
> Phase 2（快照瘦身与保留）也已落地：`plot_log` / `speech_log` 与角色记忆均为
> 有界窗口，每分支保留最近 20 个命令快照 + 全部回溯快照。事件流仍是唯一权威。

- 日期：2026-11-09
- 仓库：`/home/moonlight/projects/WenJing`，分支 `dev`
- 状态：上一轮已完成 **运行期 Agent Prompt 优化 + 全仓改名 + PromptBundle seam**，改动**未提交**。
  Phase 1 只做记忆读取链路，不改契约/DB/前端。
- 本文件是交接文档，不是规格；已归档。`docs/README.md` 只保留目录级索引，不单列本文件。

## 0. 开工前先看

```bash
cd /home/moonlight/projects/WenJing
git status --short          # 应看到 prompt/rename/PromptBundle 的未提交改动
git log --oneline -3
```

必读：

1. `AGENTS.md`（仓库约定、验证顺序、陷阱）
2. `CONTEXT.md`（术语：参演/工作人员、事件溯源、剧情主持）
3. `docs/design/play-through-architecture.md` §6（事件溯源与记忆重建）
4. `docs/prompts/runtime-agents.md` §4.5 / §5.1–5.2 / §11（PromptBundle、Character 记忆槽位、已知边界）
5. 本文件 §2 的代码地图

**不要回退或覆盖当前未提交改动**：`ProducerAgent → WorldBuilderAgent`、
`ScreenwriterAgent → GameMasterAgent` 的改名和 `domain/agents/prompting.py` 的
PromptBundle seam 都是有意为之。Phase 1 在它们之上继续。

## 1. 目标与验收（Phase 1）

只修「写了没人读」和「读错窗口」三件事，不做快照瘦身、不做向量检索、不动契约/DB/前端：

1. **`view_my_memory` 暴露近期发言**
   - `MemoryView` 增加 `working_memory`；`view_my_memory` 返回
     `{"personal_log": last 10, "rejected": last 10, "recent_speech": working_memory[-10:]}`。
   - 只含本人发言（`record_speech` 只写本人；测试确认不同角色不串）。
   - **不要把 `plot_context` / `current_direction` 放进输出**：它们目前是 write-only，
     直接暴露会带来知识边界风险；`view_plot_log` 是叙事摘要的唯一读取口。

2. **`RuntimeWorldView.plot_log` 返回「最近」而不是「最早」**
   - 当前实现 `entries[:limit]` 返回最早 5 拍，与工具 docstring「最近发生」相反。
   - 改为 `entries[-limit:]`；并且剧情摘要改为从**活动分支事件**派生，
     让 Stage3 的 `exploration_settle` / `scene_switch` 摘要对在场角色可见。
   - 新增 `GameRuntime.plot_entries_for(viewer: str | None) -> list[str]`，
     `RuntimeWorldView.plot_log` 调它，再拼上按 `_in_scene` 过滤的最近发言。

3. **确保 `broadcast_plot_context` 不泄漏**
   - 现状：`CharacterAgentManager.broadcast_plot_context` 把摘要全局写进每个角色的
     `memory.plot_context`，但该字段没有任何工具/提示词读取，所以尚未泄漏。
   - Phase 1 **不**把它接进 prompt/工具；可以留一个注释说明「write-only，Phase 2 再处理」。
   - 不要为了「用起来」而把全局广播塞进 `view_my_memory` 或 Character system。

验收口径：上述三条都有测试；`WENJING_LLM_API_KEY= make test` 全绿；
没有新增表/迁移/契约/前端改动。

## 2. 当前实现与代码地图

行号以当前工作区为准，先 `rg` 再改：

| 位置 | 现状 |
|---|---|
| `backend/app/domain/agents/character.py:46` `CharacterMemory` | 字段：`working_memory` / `personal_log` / `plot_context` / `current_direction` / `rejected` |
| `character.py:127` `record_speech` | 只把**本人**发言写进 `working_memory`（`{"role": name, "content": text}`） |
| `character.py:338` `broadcast_plot_context` | 全局写 `plot_context`，当前无读取方 |
| `character.py:342` `broadcast_direction` | 全局写 `current_direction`，当前无读取方 |
| `character.py:362` `derive_memories` | 事件折叠：`proposal` → `personal_log/rejected`；`character_speech` → `working_memory` |
| `backend/app/domain/agents/tools.py:46` `MemoryView` | 只有 `personal_log` / `rejected` |
| `tools.py:87` `view_my_memory` | 返回 `personal_log[-10:]` / `rejected[-10:]` |
| `backend/app/domain/game/world_view.py:46` `RuntimeWorldView.plot_log` | 从剧本 beat 重建 `entries[:limit]`（最早），不读 `state.plot_log`；再拼 `spoken[-limit:]` |
| `world_view.py:69` `_in_scene` | 用 `runtime._scene_participants(scene_key)` 判定 viewer 是否在该场景 |
| `backend/app/domain/game/game_runtime.py:428` `_replay_event` | 事件重放入口；`plot_advancement` / `exploration_settle` / `scene_switch` / `replay_narration` / `replay_ending_reached` 都在这里折叠 |
| `game_runtime.py:505` `_apply_settle_event` | `exploration_settle` 折叠；payload 含 `summary` / `scene_key` / `location_key` / `present` / `conflict` / `context` |
| `game_runtime.py:524` `_apply_switch_event` | `scene_switch` 折叠；payload 含 `from` / `to` / `scene_key` / `scene_title` / `participants` |
| `game_runtime.py:912` `_settle_stage3` | 生成 `exploration_settle` payload（`present` 就在里面） |
| `game_runtime.py:1033` `_on_switch_scene` | 生成 `scene_switch` payload（`participants` 就在里面） |
| `backend/app/domain/agents/prompting.py` | `CHARACTER_SLOTS` 已声明 `recent_speech`（tool、self、limit 10）；PromptBundle/system 指纹在 `backend/tests/test_prompt_bundles.py` |
| `backend/tests/test_world_view_scoped.py` | 现有裁剪语义测试；`_advance_to` 直接改 `beat_cursor`，没有事件 |
| `backend/tests/test_rollback_memory.py` | 生产路径回溯测试；`_RebuiltRuntime.runtime_at_head()` 可做「回溯后事件流」断言 |
| `backend/tests/test_agent_tools.py` | `view_my_memory` / `build_character_tools` 测试 |

事件 payload 事实（Phase 1 可见性判断直接用）：

- `plot_advancement {summary, scene_key, scene_title}`（Stage2/旧路径）
- `exploration_settle {summary, scene_key, scene_title, location_key, present, ...}`
- `scene_switch {from, to, scene_key, scene_title, participants, ...}`
- `replay_narration {text}` / `replay_ending_reached {title}`
- `character_speech {speaker, text}`：已有 `speech_log` 路径，**不要**在
  `plot_entries_for` 里重复收录。

## 3. 实现方案

### 3.1 `view_my_memory` 返回近期发言

`backend/app/domain/agents/tools.py`：

```python
class MemoryView(Protocol):
    personal_log: list[str]
    rejected: list[str]
    working_memory: list[dict]

@tool
def view_my_memory() -> str:
    """查看你自己的私有记忆：近期发言、先前提议与自我行动日志。"""
    return _dump({
        "personal_log": memory.personal_log[-10:],
        "rejected": memory.rejected[-10:],
        "recent_speech": memory.working_memory[-10:],
    })
```

- `working_memory` 结构是 `{"role": name, "content": text}`；原样返回即可。
- 若担心未来混入他人发言，可在 `CharacterMemory` 增加 owner 或在写入侧保证；
  Phase 1 先依赖「`record_speech` 只写本人」这条现有不变量，并用测试钉住。
- `CharacterMemory` 结构上已满足 `MemoryView`，不需要改类。

### 3.2 `plot_entries_for` + `plot_log`

`backend/app/domain/game/game_runtime.py` 新增（放在 `_replay_event` 附近）：

```python
def plot_entries_for(self, viewer: str | None) -> list[str]:
    """活动分支上 viewer 可见的叙事摘要（事件顺序）。

    viewer=None 是引擎内部/调试视图：返回全部。
    可见性按事件当时的参与者判定，不做「当前地点」回溯删除。
    """
    entries: list[str] = []
    for ev in self.event_store.active_events():
        etype = ev.event_type
        payload = ev.payload or {}
        if etype == evt.EVENT_PLOT_ADVANCEMENT:
            if viewer is None or viewer in self._scene_participants(payload.get("scene_key")):
                text = str(payload.get("summary", ""))
                if text:
                    entries.append(text)
        elif etype == evt.EVENT_EXPLORATION_SETTLE:
            if viewer is None or viewer in payload.get("present", []):
                text = str(payload.get("summary", ""))
                if text:
                    entries.append(text)
        elif etype == evt.EVENT_SCENE_SWITCH:
            if viewer is None or viewer in payload.get("participants", []):
                title = str(payload.get("scene_title") or payload.get("to") or "")
                if title:
                    entries.append(f"来到「{title}」")
        elif etype == evt.EVENT_REPLAY_NARRATION:
            text = str(payload.get("text", ""))
            if text:
                entries.append(text)
        elif etype == evt.EVENT_REPLAY_ENDING_REACHED:
            title = str(payload.get("title", ""))
            entries.append(f"结局：{title}".rstrip("："))
    return entries
```

`backend/app/domain/game/world_view.py::plot_log`：

```python
def plot_log(self, limit: int = 5) -> list[str]:
    entries = self._runtime.plot_entries_for(self._viewer)
    spoken = [
        f"{speaker}说：{text}"
        for speaker, scene_key, text in self._runtime.state.speech_log
        if self._in_scene(scene_key)
    ]
    return [*entries[-limit:], *spoken[-limit:]]
```

要点：

- **最新窗口**：`entries[-limit:]`，修掉「最早 5 拍」。
- **事件是权威**：回溯后 `active_events()` 不含被放弃分支，`plot_entries_for`
  自动回退；不要从 `state.plot_log` 直接读（它只是当前分支的折叠结果，且
  无法区分「谁在场」）。
- **Stage2 现有测试会变**：`test_world_view_scoped.py::test_plot_log_excludes_foreign_scene`
  直接改 `beat_cursor`、没有事件；改为用 `replay_from(None, events)` 或真实命令
  产生 `plot_advancement` 事件后再断言。
- **可见性语义**：按事件发生时的参与者判定。角色在旧地点待过，仍能看到旧地点的
  摘要（这是记忆，不是「当前地点过滤」）；不在场的人看不到。若测试文案写成
  「换景后原地点摘要不出现」，请改成「不在旧地点的人看不到旧地点摘要」，
  不要为了实现测试而删掉角色的合法记忆。
- `plot_advancement` 的 `summary` 自带 `[stage2] 场景：...` 前缀；测试断言用
  `in` 包含关系，不要钉死整句格式。

### 3.3 `broadcast_plot_context`

Phase 1 建议：**保持现状，不接入任何读取方**。在
`CharacterAgentManager.broadcast_plot_context` 上加一句注释：

```python
# write-only：当前没有任何工具/prompt 读取 plot_context；
# Phase 2 再决定删除、按在场过滤还是保留给内部调试。
```

不要为了让记忆「看起来完整」而把它塞进 `view_my_memory` 或 Character system：
`plot_context` 是全局广播，包含角色不在场的内容，接出去就是知识边界泄漏。

### 3.4 Prompt 槽位与文档同步

- `prompting.py::CHARACTER_SLOTS` 的 `recent_speech` 槽位已声明为
  `tool:view_my_memory`、`self`、limit 10；Phase 1 实现后它从「声明」变成「可用」。
  如改了上限，同步 `CHARACTER_MEMORY_LIMIT` 与 `tests/test_prompt_bundles.py`。
- **不要改 prompt 文本**：Phase 1 只改工具输出。system 指纹应保持不变；
  若确实改了 prompt 文本，必须升 `CHARACTER_PROMPT_VERSION` 并更新 golden 指纹。
- 更新 `docs/prompts/runtime-agents.md` §11 第 6 条（working_memory 已暴露）和
  `docs/prompts/runtime-agents.md` 中 `view_my_memory` 的描述。
- 若确认「工作记忆是有界窗口（10 条）」，在 `CONTEXT.md` 补一条术语；
  若暂不决定，保持 `recent_speech` 只是读取窗口、不改存储。

## 4. 可见性规则表（Phase 1）

| 事件 | 谁可见 | 摘要文本 |
|---|---|---|
| `plot_advancement` | `scene_key` 对应场景的 participants | `payload.summary` |
| `exploration_settle` | `payload.present` | `payload.summary` |
| `scene_switch` | `payload.participants` | `来到「{scene_title}」` |
| `replay_narration` | 公开 | `payload.text` |
| `replay_ending_reached` | 公开 | `结局：{title}` |
| `character_speech` | 仍走 `state.speech_log` + `_in_scene` | `{speaker}说：{text}` |

`viewer=None` 是引擎内部/调试视图，返回全部；工具消费方永远用
`world_view.bind(name)`，不要把未绑定视图交给 agent。

## 5. 测试清单（TDD，先写失败用例）

1. `tests/test_agent_tools.py`
   - `view_my_memory` 返回 `recent_speech`，条数 ≤10，内容只含本人；
   - 输出不含 `plot_context` / `current_direction`。
2. `tests/test_world_view_scoped.py`
   - 6+ 条叙事事件时返回**最近** 5 条（`entries[-limit:]`），不再是第 1–5 条；
   - `exploration_settle` 摘要只对 `payload.present` 中的角色可见；
   - `scene_switch` 摘要只对目标地点 `participants` 可见；
   - 非参与者看不到对应摘要；参与者仍能看到自己过去参与过的摘要；
   - 现有 `_advance_to` 测试改为用事件/真实命令构造。
3. `tests/test_rollback_memory.py`
   - 回溯到某事件之前后，`runtime_at_head().plot_entries_for(name)` 不含被放弃分支的摘要。
4. `tests/test_prompt_bundles.py`
   - 若未改 prompt 文本，golden 指纹应保持不变；
   - 若改了 `CHARACTER_SLOTS` 上限，更新对应断言。
5. 回归：`tests/test_agent_tools.py`、`tests/test_game_runtime.py`、
   `tests/test_exploration.py`、`tests/test_world_facts.py`。

## 6. 验证命令

```bash
cd /home/moonlight/projects/WenJing
make lint
make lint-arch
cd frontend && npm run typecheck   # 只在动契约镜像时需要；Phase 1 不应需要
cd ..
WENJING_LLM_API_KEY= make test      # 确定性 LLM，约 80 秒
```

- `make test` 会清空所连数据库；跑完补 `make migrate && make seed`。
- 快速单文件：
  `cd backend && WENJING_LLM_API_KEY= uv run pytest tests/test_world_view_scoped.py tests/test_agent_tools.py tests/test_rollback_memory.py -q`
- 外部依赖不可用时集成测试会静默 skip；全绿不代表跑过 PG/MinIO，注意输出里的 `s`。

## 7. Definition of Done

- [ ] `view_my_memory` 返回 `recent_speech`（本人、≤10），不含 `plot_context`。
- [ ] `RuntimeWorldView.plot_log` 返回最近 `limit` 条剧情摘要 + 最近在场发言。
- [ ] `plot_entries_for` 从活动分支事件派生；回溯后不含被放弃分支。
- [ ] Stage3 `exploration_settle` / `scene_switch` 摘要按事件参与者可见。
- [ ] 上述测试全部新增/更新并通过；`make lint`、`make lint-arch`、`WENJING_LLM_API_KEY= make test` 全绿。
- [ ] 更新 `docs/prompts/runtime-agents.md` §11 与 `view_my_memory` 描述；必要时在 `CONTEXT.md` 补「有界工作记忆」。
- [ ] 没有契约/DB/前端改动；没有把运行期 prompt 迁进 `prompts` 表。
- [ ] 完成后按 `AGENTS.md` 用 `feat-review` 做 Standards + Spec 双轴审查。

## 8. 未决问题（Phase 1 不要擅自扩大范围）

1. **有界窗口 vs 全量可回溯**：本 Phase 只把读取窗口定为 10 条；是否让
   `working_memory` 本身有界、快照只存尾窗口，留给 Phase 2（快照 O(n²) 同批）。
2. **`broadcast_plot_context` 的处置**：删除、按在场过滤、还是保留给内部调试？
   Phase 1 保持 write-only，不暴露；Phase 2 再决定。
3. **`plot_context` / `current_direction` 是否进 prompt**：当前不建议；如果未来要进，
   必须先做 viewer 裁剪，不能直接用全局广播值。
4. **Director 的 `recent_speeches` 是否改用 `plot_entries_for`**：Phase 1 不改；
   Director 已由运行时按当前地点过滤 `state.speech_log`，与角色工具是两条独立读取口。

## 9. 建议 skills

- `tdd`：先写 §5 的失败用例，再改 `tools.py` / `world_view.py` / `game_runtime.py`。
- `codebase-design`：确定 `plot_entries_for` 的 seam 与 `MemoryView` 扩展。
- `domain-modeling`：若在 `CONTEXT.md` 补「有界工作记忆 / 叙事摘要可见性」术语。
- `writing-for-agents`：更新 `docs/prompts/runtime-agents.md` / `AGENTS.md`。
- `feat-review`：完成后双轴审查（仓库强制）。
- 需要纯正确性扇出排查时再用 `code-review`。
