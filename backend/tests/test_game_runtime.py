"""GameRuntime command/step 机制测试（issue #7 验收标准）。

断言在最高稳定接缝（runtime 对外行为）：
生命周期阶段序列、事件编排、提议/验证、玩家动作记录、命令幂等、
显式状态快照/恢复等价、回溯、allowed_commands 约束。
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.game.game_runtime import GameRuntime
from app.infrastructure.errx import Error as WJError


def _is_ending_confirm(ix: dict | None) -> bool:
    if not ix:
        return False
    return any(o.get("proposed_by") == "system" for o in ix["options"])


async def play_until_terminal(
    rt: GameRuntime, *, end_at_ending: bool = False, _sid: dict | None = None
):
    """命令序列驱动器：自动选角并按阶段提交合法命令直到终态。"""
    counter = {"n": 0}

    async def send(kind: str, payload: dict | None = None):
        counter["n"] += 1
        return await rt.submit(
            command_id=f"auto-{counter['n']}", kind=kind, payload=payload or {}
        )

    result = await rt.start()
    while not result.terminal:
        stage = result.state["stage"]
        if stage == "stage1_complete":
            result = await send("select_role", {"role_name": "李白"})
        elif stage == "stage2_reenacting":
            assert result.active_interaction is not None
            choice = (
                1 if end_at_ending and _is_ending_confirm(result.active_interaction) else 0
            )
            result = await send("choose_option", {"option_id": str(choice)})
        elif stage == "stage2_complete":
            result = await send("enter_stage3")
        elif stage == "stage3_extending":
            result = await send("choose_option", {"option_id": "0"})
        else:
            raise AssertionError(f"非预期阶段 {stage}")
    return result


def _stages(rt: GameRuntime) -> list[str]:
    return [
        e.payload["stage"]
        for e in rt.event_store.events
        if e.event_type == "stage_transition"
    ]


# ===== 生命周期与编排 =====


async def test_start_stops_at_role_selection(make_runtime):
    rt = make_runtime()
    result = await rt.start()
    assert result.state["stage"] == "stage1_complete"
    assert "select_role" in result.allowed_commands
    assert result.active_interaction is None  # 稳定停靠点：无交互


async def test_full_lifecycle_reaches_ended(make_runtime):
    rt = make_runtime()
    result = await play_until_terminal(rt)
    assert result.terminal is True
    assert result.state["stage"] == "ended"
    assert result.state["ended"] is True
    summary = rt.summary()
    assert summary["event_count"] > 0
    assert summary["player_role"] == "李白"


async def test_stage_transitions_recorded(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt)
    stages = _stages(rt)
    assert "stage1_complete" in stages
    assert "stage2_reenacting" in stages
    assert "stage2_complete" in stages
    assert "stage3_extending" in stages
    assert stages[-1] == "ended"


# ===== Agent 编排 =====


async def test_character_proposals_collected_and_verified(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt)
    types = [e.event_type for e in rt.event_store.events]
    assert "proposal" in types
    assert "verification" in types
    prop_names = {
        e.payload["proposed_by"]
        for e in rt.event_store.events
        if e.event_type == "proposal"
    }
    assert rt.state.player_role == "李白"
    assert "杜甫" in prop_names
    assert "高适" in prop_names


async def test_npcs_but_not_player_role_propose(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt)
    prop_names = {
        e.payload["proposed_by"]
        for e in rt.event_store.events
        if e.event_type == "proposal"
    }
    assert "李白" not in prop_names  # 玩家角色不作为 NPC 提议


async def test_player_action_consumed_and_recorded(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt)
    actions = [
        e.payload
        for e in rt.event_store.events
        if e.event_type == "player_action"
    ]
    assert actions
    assert all(a["option_id"] == 0 for a in actions)


# ===== command_id 幂等 =====


async def test_duplicate_command_id_is_idempotent(make_runtime):
    rt = make_runtime()
    await rt.start()
    cid = str(uuid.uuid4())
    first = await rt.submit(
        command_id=cid, kind="select_role", payload={"role_name": "李白"}
    )
    events_before = len(rt.event_store)

    second = await rt.submit(
        command_id=cid, kind="select_role", payload={"role_name": "李白"}
    )

    assert second.duplicate is True
    assert second.state == first.state
    assert len(rt.event_store) == events_before, "重发不得产生重复领域事件"


# ===== allowed_commands 约束 =====


async def test_command_not_allowed_in_stage_rejected(make_runtime):
    rt = make_runtime()
    await rt.start()  # stage1_complete
    with pytest.raises(WJError) as excinfo:
        await rt.submit(command_id="bad-1", kind="choose_option", payload={"option_id": "0"})
    assert excinfo.value.code == 2004  # ENG_PLAYER_ACTION_INVALID
    assert rt.state.stage == "stage1_complete"

    with pytest.raises(WJError):
        await rt.submit(command_id="bad-2", kind="enter_stage3", payload={})


async def test_select_role_validates_playable(make_runtime):
    rt = make_runtime()
    await rt.start()
    with pytest.raises(WJError):
        await rt.submit(
            command_id="bad-role", kind="select_role", payload={"role_name": "杜甫"}
        )  # 杜甫未标记可扮演


# ===== 显式 RuntimeState：快照 / 恢复 =====


async def test_state_export_restore_roundtrip(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt, end_at_ending=False)
    snap = rt.export_state()

    rt2 = make_runtime()
    rt2.restore(snap)
    assert rt2.export_state()["stage"] == snap["stage"]
    assert rt2.export_state()["beat_cursor"] == snap["beat_cursor"]
    assert (
        rt2.export_state()["character_memories"]
        == snap["character_memories"]
    )
    assert rt2.export_state()["plot_log"] == snap["plot_log"]


async def test_runtime_state_has_no_infra_objects(make_runtime):
    """RuntimeState 序列化投影是纯 JSON 兼容结构。"""
    rt = make_runtime()
    await play_until_terminal(rt)
    state = rt.export_state()

    def _jsonable(obj):
        if isinstance(obj, dict):
            return all(isinstance(k, str) and _jsonable(v) for k, v in obj.items())
        if isinstance(obj, (list, tuple)):
            return all(_jsonable(v) for v in obj)
        return isinstance(obj, (str, int, float, bool)) or obj is None

    assert _jsonable(state), "export_state 必须为纯 JSON 结构（无对象引用）"


async def test_engine_module_free_of_web_frameworks():
    """引擎模块源码不 import FastAPI/WebSocket/SQLAlchemy。"""
    import inspect

    from app.domain.game import game_runtime

    src = inspect.getsource(game_runtime)
    for banned in ("fastapi", "sqlalchemy", "websockets", "uvicorn"):
        assert banned not in src, f"game_runtime 不应依赖 {banned}"


# ===== 阶段切换（D14 结局确认）=====


async def test_ending_confirm_enter_stage3(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt, end_at_ending=False)
    stages = _stages(rt)
    assert "stage3_extending" in stages
    assert stages[-1] == "ended"


async def test_ending_confirm_choose_end_skips_stage3(make_runtime):
    rt = make_runtime()
    await play_until_terminal(rt, end_at_ending=True)
    stages = _stages(rt)
    assert "stage3_extending" not in stages
    assert stages[-1] == "ended"


# ===== 回溯 =====


async def test_rollback_restores_and_reaches_next_interaction(make_runtime):
    """在第 2 个交互点前回退：rollback 事件入流、状态恢复、并重新推进到稳定交互点。"""
    rt = make_runtime()
    await rt.start()
    n = {"v": 0}

    async def send(kind: str, payload: dict | None = None):
        n["v"] += 1
        return await rt.submit(
            command_id=f"c-{n['v']}", kind=kind, payload=payload or {}
        )

    await send("select_role", {"role_name": "李白"})
    first = await send("choose_option", {"option_id": "0"})
    assert first.active_interaction is not None
    events_after_first_input = len(rt.event_store)

    # 回退到最近事件之前 2 步（真实存在的事件 id）
    target = rt.event_store.latest_event_id - 2
    roll_cid = "rollback-once"
    rolled = await rt.submit(
        command_id=roll_cid,
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )

    assert any(
        e.event_type == "rollback" for e in rt.event_store.events
    ), "应记录一次回退"
    assert rt.state.stage == "stage2_reenacting"
    assert rolled.active_interaction is not None, "回溯后应停在新的稳定交互点"
    assert rolled.allowed_commands

    # 幂等：同一命令重发不改变历史
    events_before_replay = len(rt.event_store)
    dup = await rt.submit(
        command_id=roll_cid,
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )
    assert dup.duplicate is True
    assert len(rt.event_store) == events_before_replay

    _ = events_after_first_input


async def test_rollback_overflow_rejected(make_runtime):
    rt = make_runtime()
    await rt.start()
    await rt.submit(command_id="r1", kind="select_role", payload={"role_name": "李白"})
    with pytest.raises(WJError) as excinfo:
        await rt.rollback(command_id="r2", target_event_id=9999)
    assert excinfo.value.code == 2003  # ENG_ROLLBACK_OVERFLOW
