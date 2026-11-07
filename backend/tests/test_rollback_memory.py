"""M0 回溯修复验收：生产路径（每命令重建 runtime）下的回溯正确性。

旧实现的 bug（design/play-through-redesign.md §C0）：`_memory_marks` 只在进程内，
生产每条命令从 DB 重建 runtime（`session_runtime.py::_restore_runtime`），
回溯只切事件分支——beat 游标/剧情日志/角色记忆**不回退**。

本文件全部走生产路径：
- `_RebuiltRuntime`：每条命令后丢弃 runtime，下一条命令前从事件流**全量重放**
  （`replay_from(None, active_events)`，与 `_restore_runtime` 的「快照基线 +
  增量重放」等价——快照是缓存，真相是事件）重建；
- 断言回溯后 beat_cursor/plot_log/direction/角色记忆/发言台账都回退到目标之前。

顺带钉住三个不变量：
- 目标拍由新分支**重演**（继承前缀不含目标拍）；
- 记忆由事件折叠（`derive_memories`），与实时写入同构；
- 回溯后 `_drive_until_interaction` 产出的重演事件在新分支上。
"""

from __future__ import annotations

from app.domain.game.game_runtime import GameRuntime


class _RebuiltRuntime:
    """生产路径模拟器：每条命令一个全新 runtime 实例，从「快照 + 事件」重建。

    生产 `_restore_runtime` 的形状：restore(最新快照) → replay_from(快照,
    cutoff 之后的事件)。快照在每条命令结束时落库（export_state），cutoff 之后
    通常无事件；交互点由快照承载（事件流不含它）。
    """

    def __init__(self, make_runtime) -> None:
        self._make = make_runtime
        self.store = None
        self.snapshot: dict | None = None

    def _build(self, *, keep_store: bool) -> GameRuntime:
        rt = self._make()
        if keep_store:
            rt.event_store = self.store
        return rt

    async def start(self):
        rt = self._build(keep_store=False)
        result = await rt.start()
        self.store = rt.event_store
        self.snapshot = result.state
        return result

    async def submit(self, *, command_id: str, kind: str, payload: dict):
        rt = self._build(keep_store=True)
        # 生产路径：快照基线 + 增量重放（快照是每命令落库的 export_state）
        base = self.snapshot
        cutoff = int((base or {}).get("latest_event_id", 0) or 0) if base else 0
        events = [e.to_dict() for e in self.store.active_events() if e.event_id > cutoff]
        rt.replay_from(base, events)
        result = await rt.submit(command_id=command_id, kind=kind, payload=payload)
        self.store = rt.event_store
        self.snapshot = result.state
        return result

    def export_state(self) -> dict:
        """纯事件全量重建（快照缺失/损坏时的兜底路径）并导出。"""
        rt = self._build(keep_store=True)
        rt.replay_from(None, [e.to_dict() for e in self.store.active_events()])
        return rt.export_state()

    def runtime_at_head(self) -> GameRuntime:
        rt = self._build(keep_store=True)
        rt.replay_from(None, [e.to_dict() for e in self.store.active_events()])
        return rt


async def _advance_one_beat(p: _RebuiltRuntime, n: int) -> None:
    await p.submit(command_id=f"cmd-{n}", kind="choose_option", payload={"option_id": "0"})


async def test_rollback_rewinds_everything_on_production_path(make_runtime):
    """生产路径（每命令重建）回溯：记忆/游标/剧情/方向全部随事件回退。"""
    p = _RebuiltRuntime(make_runtime)
    await p.start()
    await p.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    state_after_beat1 = p.export_state()

    await _advance_one_beat(p, 2)
    await _advance_one_beat(p, 3)  # 第 3 拍 = 最后一拍，停在结局确认交互点
    state_later = p.export_state()
    assert state_later["beat_cursor"] > state_after_beat1["beat_cursor"]
    assert state_later["plot_log"] > state_after_beat1["plot_log"]

    # 目标 = 第二拍的叙事事件（回到它开始前 = 第一拍后）
    narratives = [
        e for e in p.store.active_events() if e.event_type == "plot_advancement"
    ]
    assert len(narratives) >= 2
    target = narratives[1].event_id

    rolled = await p.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )
    assert rolled.active_interaction is not None, "回溯后停在稳定交互点"

    state_rolled = p.export_state()
    # beat/剧情随事件回退：重演第二拍后 = 第一拍后 + 1
    assert state_rolled["beat_cursor"] == state_after_beat1["beat_cursor"] + 1
    assert (
        state_rolled["plot_log"][: len(state_after_beat1["plot_log"])]
        == state_after_beat1["plot_log"]
    )

    # 从 DB 全量重建（下一命令的 `_restore_runtime`）与回溯命令后的状态一致：
    # 这是旧实现必挂的断言——mark 只在进程内，重建后记忆不回退
    rt = p.runtime_at_head()
    rebuilt = rt.export_state()
    assert rebuilt["beat_cursor"] == state_rolled["beat_cursor"]
    assert rebuilt["plot_log"] == state_rolled["plot_log"]
    assert rebuilt["direction"] == state_rolled["direction"]
    assert rebuilt["character_memories"] == state_rolled["character_memories"]


async def test_rollback_rewinds_character_memories(make_runtime):
    """回溯后角色记忆回退：被放弃回合的提议/发言不再出现在个人记忆里。"""
    p = _RebuiltRuntime(make_runtime)
    await p.start()
    await p.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await _advance_one_beat(p, 2)
    await _advance_one_beat(p, 3)
    # 第二拍回合里有 NPC 提议与反应发言
    memories = p.export_state()["character_memories"]
    assert any(mem["personal_log"] or mem["working_memory"] for mem in memories.values())

    narratives = [
        e for e in p.store.active_events() if e.event_type == "plot_advancement"
    ]
    target = narratives[1].event_id
    await p.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )

    rt = p.runtime_at_head()
    rebuilt_memories = rt.export_state()["character_memories"]
    # 第二拍之后的提议/发言被回退：重演回合只会重新产生它们
    # （fake LLM 文案固定，故与「第一拍后」+「重演一拍」的内容一致）
    proposals_in_log = {
        entry
        for mem in rebuilt_memories.values()
        for entry in mem["personal_log"]
    }
    assert all("提议：" in entry for entry in proposals_in_log)
    # 重演回合里每个 NPC 各重提一次（personal_log 只记提议，不含被回退回合的重复）
    for name, mem in rebuilt_memories.items():
        if name == "李白":
            continue
        assert len([e for e in mem["personal_log"] if e.startswith("提议：")]) <= 2


async def test_rollback_target_beat_is_replayed_not_inherited(make_runtime):
    """目标拍由新分支重演：继承前缀不含目标拍叙事事件（防 DB 恢复双计）。"""
    p = _RebuiltRuntime(make_runtime)
    await p.start()
    await p.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await _advance_one_beat(p, 2)
    await _advance_one_beat(p, 3)

    narratives = [
        e for e in p.store.active_events() if e.event_type == "plot_advancement"
    ]
    target = narratives[1].event_id
    await p.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )

    # 新分支路径不含目标拍（旧主分支的叙事事件）
    path_ids = [e.event_id for e in p.store.active_events()]
    assert target not in path_ids
    # 但重演产生了新的叙事事件（同一拍内容）
    new_narratives = [
        e for e in p.store.active_events() if e.event_type == "plot_advancement"
    ]
    assert len(new_narratives) == 2, "重演一拍：前缀一拍 + 重演一拍"


async def test_rollback_replay_equals_live_state(make_runtime):
    """全量重放 == 回溯命令结束时进程内状态（快照基线与全量重放一致性）。"""
    p = _RebuiltRuntime(make_runtime)
    await p.start()
    await p.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await _advance_one_beat(p, 2)
    await _advance_one_beat(p, 3)

    narratives = [
        e for e in p.store.active_events() if e.event_type == "plot_advancement"
    ]
    target = narratives[1].event_id
    rolled = await p.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )
    live = rolled.state

    rebuilt = p.export_state()
    for key in (
        "stage",
        "beat_cursor",
        "plot_log",
        "direction",
        "scene_key",
        "character_memories",
    ):
        assert rebuilt[key] == live[key], f"全量重放后 {key} 与回溯命令现场不一致"
