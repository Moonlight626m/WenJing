"""运行时回放 / 命令幂等 / 分支回溯测试（issue #8 验收标准）。

断言在最高稳定接缝（runtime 对外行为 + event store 分支语义）：
- snapshot + active-branch 事件重放后重建相同的确定性状态（属性级断言）
- 回溯创建新分支、旧事件保留、head 切换到新分支
- 回溯后后续命令只追加到新活动分支
- 历史可审计：血缘链（parent/root）可重建完整历史
"""

from __future__ import annotations

import pytest

from app.core.event import MAIN_BRANCH_ID
from app.errx import Error as WJError


def _active_branch_ids(rt) -> list[int]:
    return [e.branch_id for e in rt.event_store.active_events()]


# ===== 1. 快照 + 事件重放 =====


async def test_replay_from_snapshot_and_events_rebuilds_state(make_runtime):
    rt = make_runtime()
    await rt.start()  # stage1_complete（无 LLM）
    snap = rt.export_state()
    base_count = len(rt.event_store)

    await rt.submit(
        command_id="c1", kind="select_role", payload={"role_name": "李白"}
    )
    events_after = [e.to_dict() for e in rt.event_store.events[base_count:]]
    assert events_after, "快照之后应有事件"

    rt2 = make_runtime()
    rt2.replay_from(snap, events_after)

    a, b = rt.export_state(), rt2.export_state()
    for key in (
        "stage",
        "player_role",
        "beat_cursor",
        "stage3_round_taken",
        "plot_log",
        "ended",
    ):
        assert b[key] == a[key], f"重放后 {key} 不一致"

    # 剧情上下文/处境可由 plot/direction 事件确定性重放
    assert rt2.state.player_role == "李白"


async def test_replay_from_events_only_restores_defaults(make_runtime):
    """无快照时从事件流重放：从初始状态起重建（快照是优化而非真相）。"""
    rt = make_runtime()
    await rt.start()
    events = [e.to_dict() for e in rt.event_store.events]

    rt2 = make_runtime()
    rt2.replay_from(None, events)
    assert rt2.state.stage == "stage1_complete"
    assert rt2.export_state()["plot_log"] == []


# ===== 2. 回溯 = 新分支 + 保留旧历史 =====


async def test_rollback_creates_new_branch_and_preserves_history(make_runtime):
    rt = make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await rt.submit(command_id="c2", kind="choose_option", payload={"option_id": "0"})

    main_count = len(rt.event_store)
    target = rt.event_store.latest_event_id - 2

    rolled = await rt.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )

    # 旧事件全部保留（append-only）
    assert len(rt.event_store) >= main_count, "回溯不得物理删除历史"
    assert rt.event_store.active_branch_id != MAIN_BRANCH_ID
    assert rolled.state["active_branch_id"] == rt.event_store.active_branch_id
    # 回退事件记录在新活动分支
    roll_events = [
        e for e in rt.event_store.events_in_branch(rt.event_store.active_branch_id)
        if e.event_type == "rollback"
    ]
    assert roll_events, "新分支应记录 rollback 事件"


async def test_post_rollback_commands_append_to_new_branch(make_runtime):
    rt = make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await rt.submit(command_id="c2", kind="choose_option", payload={"option_id": "0"})

    target = rt.event_store.latest_event_id - 2
    await rt.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )
    new_branch = rt.event_store.active_branch_id

    await rt.submit(command_id="c3", kind="choose_option", payload={"option_id": "0"})
    recent = rt.event_store.events[-1]
    assert recent.branch_id == new_branch, "回溯后新命令只追加到新活动分支"
    assert all(
        e.branch_id == new_branch
        for e in rt.event_store.events_in_branch(new_branch)
    )


async def test_branch_history_is_auditable(make_runtime):
    rt = make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await rt.submit(command_id="c2", kind="choose_option", payload={"option_id": "0"})
    target = rt.event_store.latest_event_id - 2
    await rt.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )

    branches = rt.event_store.branches
    assert branches[0].branch_id == MAIN_BRANCH_ID
    assert branches[0].parent_branch_id is None
    assert len(branches) == 2
    new_meta = branches[-1]
    assert new_meta.parent_branch_id == MAIN_BRANCH_ID
    assert new_meta.root_event_id == target

    # 新分支历史 = 主分支前缀（到 target）+ 新分支事件
    path = rt.event_store.branch_path(new_meta.branch_id)
    path_ids = [e.event_id for e in path]
    assert path_ids == sorted(path_ids), "分支历史必须有序"
    assert target in path_ids
    # 主分支被放弃的事件仍在主分支流里（可审计），但不在活动路径
    assert len(rt.event_store.events) > len(path)


async def test_rollback_target_not_on_active_path_rejected(make_runtime):
    rt = make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    await rt.submit(command_id="c2", kind="choose_option", payload={"option_id": "0"})
    target = rt.event_store.latest_event_id - 2
    await rt.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )
    # 被放弃的主分支事件仍在流中，但不属于活动路径 → 不可作为回溯目标
    superseded = [
        e
        for e in rt.event_store.events_in_branch(MAIN_BRANCH_ID)
        if e.event_id > target
    ]
    assert superseded, "应存在被放弃的旧分支事件"
    stale_target = superseded[-1].event_id
    with pytest.raises(WJError) as excinfo:
        await rt.submit(
            command_id="rb2",
            kind="rollback_to_event",
            payload={"target_event_id": stale_target},
        )
    assert excinfo.value.code == 2002  # ENG_ROLLBACK_TARGET_MISSING


# ===== 3. 端到端：回溯 → 重新选择 → 新分支状态一致且历史可审计 =====


async def test_rollback_reselect_end_to_end(make_runtime):
    rt = make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    first = await rt.submit(command_id="c2", kind="choose_option", payload={"option_id": "0"})
    assert first.active_interaction is not None

    target = rt.event_store.latest_event_id - 2
    rolled = await rt.submit(
        command_id="rb1",
        kind="rollback_to_event",
        payload={"target_event_id": target},
    )
    assert rolled.active_interaction is not None
    new_branch = rt.event_store.active_branch_id

    # 重新选择：走新分支推进
    reselected = await rt.submit(
        command_id="c3", kind="choose_option", payload={"option_id": "0"}
    )
    assert reselected.state["stage"] == rt.state.stage
    assert reselected.state["active_branch_id"] == new_branch
    # 新分支历史可审计：包含目标前缀 + rollback + 重新选择的推进事件
    path_types = [e.event_type for e in rt.event_store.active_events()]
    assert "rollback" in path_types
    assert "player_action" in path_types
