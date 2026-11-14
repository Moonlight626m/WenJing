"""回溯时间线的降噪：提议/离线提示过滤、离线事实归并、旁白去重、存档点标签。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.contracts.enums import MessageCategory
from app.domain.game.event import (
    EVENT_INTERVENTION_REQUESTED,
    EVENT_OFFLINE_HINT,
    EVENT_REPLAY_NARRATION,
    EVENT_REPLAY_NODE_ENTERED,
    EVENT_WORLD_FACT,
    EventStore,
)
from app.infrastructure.db.event_store import branch_uuid
from app.services.session_projection import project_timeline

_SID = uuid.UUID(int=7)


def _timeline(store: EventStore, snapshots=()):
    return project_timeline(
        _SID,
        store,
        stage="stage3_extending",
        allowed_commands=["rollback_to_event"],
        max_rollback_steps=100,
        snapshots=list(snapshots),
    )


def _world_fact(text: str, *, tick_id: str | None = None) -> dict:
    payload = {"text": text, "visibility": "public", "audience": []}
    if tick_id is not None:
        payload["tick_id"] = tick_id
    return payload


def test_timeline_skips_proposals_and_offline_hints():
    store = EventStore()
    store.append("proposal", {"proposed_by": "父亲", "description": "提案内容"}, session_id="s1")
    store.append(EVENT_OFFLINE_HINT, {"text": "你不在的这段时间……"}, session_id="s1")
    store.append(
        EVENT_WORLD_FACT, _world_fact("父亲：真的发生了"), session_id="s1"
    )

    texts = [entry.text for entry in _timeline(store).entries]

    assert "提案内容" not in texts
    assert not any("你不在的这段时间" in text for text in texts)
    assert "父亲：真的发生了" in texts


def test_world_facts_from_one_tick_are_merged():
    store = EventStore()
    store.append(EVENT_WORLD_FACT, _world_fact("父亲：甲", tick_id="t1"), session_id="s1")
    store.append(EVENT_WORLD_FACT, _world_fact("祖母：乙", tick_id="t1"), session_id="s1")
    store.append(EVENT_WORLD_FACT, _world_fact("朋友：丙", tick_id="t2"), session_id="s1")

    facts = [
        entry
        for entry in _timeline(store).entries
        if entry.kind is MessageCategory.SYSTEM
    ]

    assert [entry.text for entry in facts] == ["父亲：甲；祖母：乙", "朋友：丙"]


def test_repeated_replay_narration_is_dropped():
    store = EventStore()
    longer = "等他的背影混入来来往往的人里，再找不着了，我便进来坐下，我的眼泪又来了。"
    shorter = "他的背影混入来来往往的人里，再找不着了。"
    store.append(
        EVENT_REPLAY_NODE_ENTERED,
        {
            "node_id": "scene:1",
            "node_kind": "scene",
            "scene_key": "scene:1",
            "scene_title": "相遇",
        },
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {"node_id": "scene:1", "text": longer},
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {"node_id": "scene:1", "text": shorter},
        session_id="s1",
    )

    narratives = [
        entry.text
        for entry in _timeline(store).entries
        if entry.kind is MessageCategory.NARRATIVE
        and entry.text.startswith(("等他的背影", "他的背影"))
    ]

    assert narratives == [longer]


def test_empty_narration_does_not_swallow_following_narratives():
    """整条只剩作者注记的旁白剥成空串后必须跳过，不能进入去重窗口。"""
    store = EventStore()
    store.append(
        EVENT_REPLAY_NODE_ENTERED,
        {
            "node_id": "scene:1",
            "node_kind": "scene",
            "scene_key": "scene:1",
            "scene_title": "相遇",
        },
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {"node_id": "scene:1", "text": "（目标：收束于背影）"},
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {"node_id": "scene:1", "text": "第一段正常旁白。"},
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {"node_id": "scene:1", "text": "第二段完全不同的旁白。"},
        session_id="s1",
    )

    texts = [
        entry.text
        for entry in _timeline(store).entries
        if entry.kind is MessageCategory.NARRATIVE
    ]

    assert "第一段正常旁白。" in texts
    assert "第二段完全不同的旁白。" in texts
    assert not any("目标" in text for text in texts)


def test_short_narration_is_not_treated_as_duplicate():
    store = EventStore()
    store.append(
        EVENT_REPLAY_NODE_ENTERED,
        {
            "node_id": "scene:1",
            "node_kind": "scene",
            "scene_key": "scene:1",
            "scene_title": "相遇",
        },
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {"node_id": "scene:1", "text": "夜深了。"},
        session_id="s1",
    )
    store.append(
        EVENT_REPLAY_NARRATION,
        {
            "node_id": "scene:1",
            "text": "夜深了。他推开门，屋里空无一人，只有桌上的灯还亮着。",
        },
        session_id="s1",
    )

    texts = [
        entry.text
        for entry in _timeline(store).entries
        if entry.kind is MessageCategory.NARRATIVE
        and not entry.text.startswith("场景：")
    ]

    assert texts == [
        "夜深了。",
        "夜深了。他推开门，屋里空无一人，只有桌上的灯还亮着。",
    ]


def test_save_point_label_uses_player_action_text():
    store = EventStore()
    store.append(
        "player_action",
        {"type": "choose_option", "text": "扶父亲到廊下坐下歇一歇"},
        session_id="s1",
    )
    events = store.active_events()
    sequence = len(events) - 1
    snapshot = SimpleNamespace(
        branch_id=branch_uuid(_SID, store.active_branch_id),
        sequence=sequence,
        label="选择 · 徐州奔丧与父亲的劝慰",
        kind="command",
        created_at=None,
        plot_context={"latest_event_id": events[sequence].event_id},
    )

    save_points = _timeline(store, [snapshot]).save_points

    assert [point.label for point in save_points] == [
        "选择：扶父亲到廊下坐下歇一歇"
    ]


def test_intervention_save_point_uses_intervention_text():
    """干涉不写 player_action，标签不能回退到上一轮动作。"""
    store = EventStore()
    store.append(
        "player_action",
        {"type": "choose_option", "text": "扶父亲到廊下坐下歇一歇"},
        session_id="s1",
    )
    store.append(
        EVENT_INTERVENTION_REQUESTED,
        {"text": "建一间雨夜客栈"},
        session_id="s1",
    )
    events = store.active_events()
    sequence = len(events) - 1
    snapshot = SimpleNamespace(
        branch_id=branch_uuid(_SID, store.active_branch_id),
        sequence=sequence,
        label="干涉世界 · 徐州奔丧与父亲的劝慰",
        kind="command",
        created_at=None,
        plot_context={"latest_event_id": events[sequence].event_id},
    )

    save_points = _timeline(store, [snapshot]).save_points

    assert [point.label for point in save_points] == ["干涉世界：建一间雨夜客栈"]
