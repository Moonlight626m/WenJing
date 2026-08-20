"""游戏引擎机制测试：编排 / 事件 / 提议验证 / 玩家驱动 / 回溯 / 阶段切换。

本轮目标：验证引擎机制正确性（Q13），不断言剧情质量。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.game_engine import GameEngine
from app.core.types import InteractionPoint, PlayerAction

PlayerDecision = Callable[[InteractionPoint], Awaitable[PlayerAction]]


def _ending_confirm_is_shown(interaction: InteractionPoint) -> bool:
    return any(o.get("proposed_by") == "system" for o in interaction.options)


def _auto_player() -> PlayerDecision:
    """脚本化玩家：有选项就选第一个，否则自由输入。"""

    async def decision(_interaction: InteractionPoint) -> PlayerAction:
        if _interaction.options:
            return PlayerAction(type="choose_option", option_id=0)
        return PlayerAction(type="speak", text="我继续行动。")

    return decision


def _player_choose_end() -> PlayerDecision:
    """在所有提示处都选第一个，仅在结局确认处选「到此结束」。"""

    async def decision(_interaction: InteractionPoint) -> PlayerAction:
        if _ending_confirm_is_shown(_interaction):
            return PlayerAction(type="choose_option", option_id=1)
        if _interaction.options:
            return PlayerAction(type="choose_option", option_id=0)
        return PlayerAction(type="speak", text="我继续。")

    return decision


def _player_rollback_at(trigger_turn: int, steps: int = 1) -> PlayerDecision:
    """在第 N 个玩家回合注入一次回退。"""
    state = {"n": 0}

    async def decision(_interaction: InteractionPoint) -> PlayerAction:
        state["n"] += 1
        if state["n"] == trigger_turn:
            return PlayerAction(type="rollback", steps=steps)
        if _interaction.options:
            return PlayerAction(type="choose_option", option_id=0)
        return PlayerAction(type="speak", text="我继续。")

    return decision


def _stage_sequence(engine: GameEngine) -> list[str]:
    return [
        e.payload["stage"]
        for e in engine.event_store.events
        if e.event_type == "stage_transition"
    ]


# ===== 生命周期与编排 =====


async def test_full_lifecycle_reaches_ended(make_engine):
    engine = make_engine()
    summary = await _run(engine)
    assert summary["stage"] == "ended"
    assert summary["ended"] is True
    assert summary["event_count"] > 0


async def _run(engine: GameEngine) -> dict:
    return await engine.run(_auto_player())


async def test_stage_transitions_recorded(make_engine):
    engine = make_engine()
    await _run(engine)
    stages = _stage_sequence(engine)
    assert "stage1_complete" in stages
    assert "stage2_reenacting" in stages
    assert "stage2_complete" in stages
    assert "stage3_extending" in stages
    assert stages[-1] == "ended"


# ===== Agent 编排 =====


async def test_character_proposals_collected_and_verified(make_engine):
    engine = make_engine()
    await _run(engine)
    types = [e.event_type for e in engine.event_store.events]
    assert "proposal" in types
    assert "verification" in types
    prop_names = {
        e.payload["proposed_by"]
        for e in engine.event_store.events
        if e.event_type == "proposal"
    }
    assert engine.player_role == "李白"
    assert "杜甫" in prop_names
    assert "高适" in prop_names


async def test_npcs_but_not_player_role_propose(make_engine):
    engine = make_engine()
    await _run(engine)
    prop_names = {
        e.payload["proposed_by"]
        for e in engine.event_store.events
        if e.event_type == "proposal"
    }
    assert "李白" not in prop_names  # 玩家角色不作为 NPC 提议


async def test_player_action_consumed_and_recorded(make_engine):
    engine = make_engine()
    await _run(engine)
    actions = [
        e.payload for e in engine.event_store.events if e.event_type == "player_action"
    ]
    assert actions
    assert all(a["option_id"] == 0 for a in actions)


# ===== 阶段切换（D14 结局确认）=====


async def test_ending_confirm_enter_stage3(make_engine):
    engine = make_engine()
    await engine.run(_auto_player())  # 有选项选第一个 → 结局确认处选「进入续写」(id=0)
    stages = _stage_sequence(engine)
    assert "stage3_extending" in stages
    assert stages[-1] == "ended"


async def test_ending_confirm_choose_end_skips_stage3(make_engine):
    engine = make_engine()
    await engine.run(_player_choose_end())  # 结局确认处选「到此结束」(id=1)
    stages = _stage_sequence(engine)
    assert "stage3_extending" not in stages
    assert stages[-1] == "ended"


# ===== 回溯 =====


async def test_rollback_truncates_events(make_engine):
    engine = make_engine()
    await engine.run(_player_rollback_at(trigger_turn=2, steps=1))
    # 事件流应包含一条 rollback 事件，且历史被截断后仍正常推进到结束
    rollbacks = [e for e in engine.event_store.events if e.event_type == "rollback"]
    assert rollbacks, "应记录一次回退"
    assert engine.state_machine.stage.value == "ended"
