"""Stage3 确定性探索（M5）：地点表、在场过滤、结算与换景。

旧剧本（`exploration=None`）必须保持原 3 轮行为；有地图时：
- 只有当前地点的 participants ∩ 已创建角色会回应/提议；
- 每轮玩家动作写一条 `exploration_settle`（地点化摘要 + 处境）；
- `switch_scene` 只切到地图里已存在的地点，写 `scene_switch` 并让新地点在场者反应。
"""

from __future__ import annotations

import pytest
from conftest import FakeLLMService

from app.contracts.script import ExplorationLocation, ExplorationMap
from app.domain.game.event import (
    EVENT_ASSET_READY,
    EVENT_CHARACTER_SPEECH,
    EVENT_EXPLORATION_SETTLE,
    EVENT_SCENE_SWITCH,
    EventStore,
)
from app.domain.game.exploration import (
    ExplorationDirector,
    ExplorationProgress,
    WorldState,
    build_location_registry,
    derive_exploration,
)
from app.domain.game.game_runtime import GameRuntime
from app.domain.game.types import Beat, CharacterSetting, Scene, Script
from app.infrastructure.errx import Error, codes


def _script() -> Script:
    return Script(
        title="渡口续写",
        characters=[
            CharacterSetting(name="甲", public_background="渡客", is_player_playable=True),
            CharacterSetting(name="乙", public_background="船夫"),
            CharacterSetting(name="丙", public_background="过路人"),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="渡口",
                participants=["甲", "乙"],
                beats=[Beat(beat_id=1, description="船靠岸")],
            )
        ],
        stage2_ending_beat_id=1,
        teaching_focus=["同舟共济"],
    )


def _map() -> ExplorationMap:
    return ExplorationMap(
        start_location_key="harbor",
        locations=[
            ExplorationLocation(
                location_key="harbor",
                title="渡口",
                participants=["乙"],
                visual_summary="雨后的渡口，船绳滴着水。",
            ),
            ExplorationLocation(
                location_key="inn",
                title="客栈",
                participants=["乙", "丙"],
                visual_summary="客栈里点着油灯。",
            ),
            ExplorationLocation(
                location_key="market",
                title="集市",
                participants=[],
                visual_summary="雨后的集市空荡荡。",
            ),
        ],
    )


def _make_runtime(*, with_map: bool = True, llm=None) -> GameRuntime:
    return GameRuntime(
        session_id="explore-session",
        script=_script(),
        llm=llm or FakeLLMService(),
        event_store=EventStore(),
        exploration_map=_map() if with_map else None,
    )


def _events(rt: GameRuntime, event_type: str) -> list[dict]:
    return [e.payload for e in rt.event_store.active_events() if e.event_type == event_type]


def _is_ending_confirm(ix: dict | None) -> bool:
    if not ix:
        return False
    return any(o.get("proposed_by") == "system" for o in ix["options"])


async def _to_stage3(rt: GameRuntime):
    result = await rt.start()
    result = await rt.submit(
        command_id="c-select", kind="select_role", payload={"role_name": "甲"}
    )
    n = 0
    while not _is_ending_confirm(result.active_interaction):
        n += 1
        assert n < 10, "Stage2 在有限拍内必须到达结局确认"
        result = await rt.submit(
            command_id=f"c-stage2-{n}",
            kind="choose_option",
            payload={"option_id": str(result.active_interaction["options"][0]["id"])},
        )
    result = await rt.submit(
        command_id="c-ending", kind="choose_option", payload={"option_id": "0"}
    )
    assert result.state["stage"] == "stage2_complete"
    return await rt.submit(command_id="c-stage3", kind="enter_stage3")


# ===== 纯函数 =====


def test_legacy_without_map_has_no_registry():
    assert build_location_registry(None) is None
    assert build_location_registry(
        ExplorationMap(start_location_key="missing", locations=[])
    ) is None


def test_derive_exploration_folds_events_and_ignores_unknown():
    registry = build_location_registry(_map())
    assert registry is not None
    events = [
        {"event_type": EVENT_SCENE_SWITCH, "payload": {"from": "harbor", "to": "inn"}},
        {"event_type": EVENT_SCENE_SWITCH, "payload": {"from": "inn", "to": "nope"}},
        {"event_type": EVENT_EXPLORATION_SETTLE, "payload": {"location_key": "harbor"}},
    ]
    progress = derive_exploration(events, registry)
    assert progress.current_location_key == "harbor"
    assert progress.visited == ("harbor", "inn")


def test_derive_exploration_accepts_game_event_shape():
    """生产路径传的是 `GameEvent`（不是 to_dict）：折叠结果必须一致。"""
    registry = build_location_registry(_map())
    assert registry is not None
    store = EventStore()
    store.append(EVENT_SCENE_SWITCH, {"from": "harbor", "to": "inn"})
    store.append(EVENT_EXPLORATION_SETTLE, {"location_key": "market"})
    progress = derive_exploration(store.active_events(), registry)
    assert progress.current_location_key == "market"
    assert progress.visited == ("harbor", "inn", "market")


def test_derive_exploration_starts_where_replay_ended():
    """Stage2 收束于哪一场，续写就从那个地点开始（而不是地图起点）。

    否则「北来读信」演完点进入续写，人会被瞬移回第一场：在场名单、导演选项
    与配图全都跟着回到开场。
    """
    registry = build_location_registry(
        ExplorationMap(
            start_location_key="scene_1",
            locations=[
                ExplorationLocation(
                    location_key="scene_1", title="徐州", participants=["甲", "乙"]
                ),
                ExplorationLocation(
                    location_key="scene_2", title="读信", participants=["甲"]
                ),
            ],
        )
    )
    assert registry is not None
    events = [
        {"event_type": "replay_node_entered", "payload": {"scene_key": "scene:1"}},
        {"event_type": "replay_node_entered", "payload": {"scene_key": "scene:2"}},
        # 收尾落在分支节点上：它属于 scene_2 的空间，不能把基座冲掉
        {
            "event_type": "replay_node_entered",
            "payload": {"scene_key": "scene:2::branch:b1", "node_kind": "branch"},
        },
    ]
    progress = derive_exploration(events, registry)
    assert progress.current_location_key == "scene_2"
    assert progress.visited == ("scene_2",)


def test_explicit_scene_switch_beats_replay_position():
    registry = build_location_registry(
        ExplorationMap(
            start_location_key="scene_1",
            locations=[
                ExplorationLocation(location_key="scene_1", title="徐州", participants=[]),
                ExplorationLocation(location_key="scene_2", title="读信", participants=[]),
            ],
        )
    )
    assert registry is not None
    events = [
        {"event_type": "replay_node_entered", "payload": {"scene_key": "scene:2"}},
        {"event_type": "scene_switch", "payload": {"from": "scene_2", "to": "scene_1"}},
    ]
    assert derive_exploration(events, registry).current_location_key == "scene_1"


def test_present_names_is_locations_intersection():
    registry = build_location_registry(_map())
    assert registry is not None
    from app.domain.game.exploration import ExplorationDirector

    director = ExplorationDirector(registry)
    progress = ExplorationProgress(current_location_key="inn", visited=("harbor", "inn"))
    assert director.present_names(progress, ("乙", "丙", "丁")) == ("乙", "丙")
    empty = ExplorationProgress(current_location_key="market")
    assert director.present_names(empty, ("乙", "丙")) == ()


# ===== 运行时：探索回合 =====


async def test_stage3_settles_and_only_present_npcs_react():
    rt = _make_runtime()
    result = await _to_stage3(rt)
    assert result.state["stage"] == "stage3_extending"
    option_label = result.active_interaction["options"][0]["text"]

    result = await rt.submit(
        command_id="c-act", kind="choose_option", payload={"option_id": "0"}
    )

    settles = _events(rt, EVENT_EXPLORATION_SETTLE)
    assert len(settles) == 1
    assert settles[0]["location_key"] == "harbor"
    assert settles[0]["summary"] == f"在「渡口」：{option_label}"
    assert settles[0]["present"] == ["乙"]
    # 只有在场者（乙）说话；丙在别处
    speakers = {p["speaker"] for p in _events(rt, EVENT_CHARACTER_SPEECH)}
    assert speakers == {"乙"}
    assert any("在「渡口」" in line for line in rt.state.plot_log)
    assert rt.state.scene_key == "loc:harbor"


async def test_scene_options_are_projected():
    rt = _make_runtime()
    await _to_stage3(rt)
    scenes = rt.export_state()["scene_options"]
    assert {s["scene_key"] for s in scenes} == {
        "loc:harbor",
        "loc:inn",
        "loc:market",
    }
    current = [s for s in scenes if s["is_current"]]
    assert [s["scene_key"] for s in current] == ["loc:harbor"]


def test_scene_options_include_runtime_members():
    """在场名单与 present_names 同口径：静态 participants + 运行期拉入/新增。"""
    registry = build_location_registry(_map())
    assert registry is not None
    director = ExplorationDirector(registry)
    progress = ExplorationProgress(current_location_key="harbor", visited=("harbor",))
    world = WorldState(memberships={"loc:harbor": ("丁",)})

    options = director.scene_options(progress, world)
    current = next(item for item in options if item["is_current"])
    assert current["participants"] == ["乙", "丁"]


async def test_switch_scene_moves_and_present_npcs_react():
    rt = _make_runtime()
    await _to_stage3(rt)
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})

    result = await rt.submit(
        command_id="c-switch", kind="switch_scene", payload={"scene_key": "loc:inn"}
    )

    switches = _events(rt, EVENT_SCENE_SWITCH)
    assert switches[-1]["from"] == "harbor"
    assert switches[-1]["to"] == "inn"
    assert switches[-1]["participants"] == ["乙", "丙"]
    assert result.state["scene_key"] == "loc:inn"
    assert result.state["scene_title"] == "客栈"
    # 画师接线（M6）：到访无图地点时记一次 scene_montage 配图意图
    assert [(i.kind, i.scene_key) for i in result.asset_requests] == [
        ("scene_montage", "loc:inn")
    ]
    # 配图描述要带在场人物与此刻的动作：只给地点摘要，画师不知道画谁、在做什么
    request = result.asset_requests[0]
    assert "在场人物：乙、丙" in request.description
    assert "你走进了「客栈」" in request.description
    speakers = {p["speaker"] for p in _events(rt, EVENT_CHARACTER_SPEECH)}
    assert speakers == {"乙", "丙"}

    scenes = rt.export_state()["scene_options"]
    current = [s for s in scenes if s["is_current"]]
    assert [s["scene_key"] for s in current] == ["loc:inn"]


async def test_switch_to_unknown_or_current_location_rejected():
    rt = _make_runtime()
    await _to_stage3(rt)
    with pytest.raises(Error) as excinfo:
        await rt.submit(
            command_id="c-bad", kind="switch_scene", payload={"scene_key": "loc:nope"}
        )
    assert excinfo.value.code == codes.ENG_PLAYER_ACTION_INVALID
    with pytest.raises(Error) as excinfo:
        await rt.submit(
            command_id="c-same", kind="switch_scene", payload={"scene_key": "loc:harbor"}
        )
    assert excinfo.value.code == codes.ENG_PLAYER_ACTION_INVALID


async def test_empty_location_has_no_reactions():
    rt = _make_runtime()
    await _to_stage3(rt)
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    before = len(_events(rt, EVENT_CHARACTER_SPEECH))

    await rt.submit(
        command_id="c-switch", kind="switch_scene", payload={"scene_key": "loc:market"}
    )

    assert len(_events(rt, EVENT_CHARACTER_SPEECH)) == before


async def test_rollback_in_stage3_restores_location_progress():
    rt = _make_runtime()
    await _to_stage3(rt)
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    settle = next(
        e for e in rt.event_store.active_events() if e.event_type == EVENT_EXPLORATION_SETTLE
    )
    await rt.submit(
        command_id="c-switch", kind="switch_scene", payload={"scene_key": "loc:inn"}
    )
    assert rt._exploration_progress is not None
    assert rt._exploration_progress.current_location_key == "inn"

    result = await rt.rollback(command_id="c-rollback", target_event_id=settle.event_id)

    assert rt._exploration_progress is not None
    assert rt._exploration_progress.current_location_key == "harbor"
    assert result.state["scene_key"] == "loc:harbor"
    # 新分支上不再有那次换景
    assert not _events(rt, EVENT_SCENE_SWITCH)


async def test_switch_does_not_consume_stage3_round_budget():
    """换景不算续写回合：实时与重放同口径，否则回溯后轮次凭空多一拍。"""
    rt = _make_runtime()
    await _to_stage3(rt)
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    before = rt.state.stage3_round_taken
    assert before == 1

    await rt.submit(
        command_id="c-switch", kind="switch_scene", payload={"scene_key": "loc:inn"}
    )
    assert rt.state.stage3_round_taken == before

    events = [e.to_dict() for e in rt.event_store.active_events()]
    restored = GameRuntime(
        session_id="explore-session",
        script=_script(),
        llm=FakeLLMService(),
        event_store=rt.event_store,
        exploration_map=_map(),
    )
    restored.replay_from(None, events)
    assert restored.state.stage3_round_taken == before


async def test_scene_switch_message_is_narrative_with_scene_fields():
    """换景必须走 narrative 消息，前端才会应用 scene_key/title（背景/标题刷新）。"""
    import uuid

    from app.services.session_projection import project_messages

    rt = _make_runtime()
    await _to_stage3(rt)
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    await rt.submit(
        command_id="c-switch", kind="switch_scene", payload={"scene_key": "loc:inn"}
    )

    sid = uuid.UUID("0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910")
    msgs = project_messages(sid, rt.event_store)
    moved = [m for m in msgs if m["payload"].get("scene_key") == "loc:inn"]
    assert moved, "换景消息必须带目标 scene_key"
    assert moved[0]["type"] == "narrative"
    assert moved[0]["payload"]["scene_title"] == "客栈"
    assert moved[0]["payload"]["text"].startswith("你来到了「客栈」")


async def test_settle_carries_current_asset_from_event_index():
    """地点已有事件索引资产时，结算叙事要带上它（否则前端会清空背景）。"""
    import uuid

    from app.services.session_projection import project_messages

    rt = _make_runtime()
    await _to_stage3(rt)
    rt.event_store.append(
        EVENT_ASSET_READY,
        {
            "scene_key": "loc:harbor",
            "asset_id": "8a1d5f2b-6c3e-4d90-a2b7-5e9f0c1d8a44",
            "kind": "background",
            "status": "ready",
        },
    )
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})

    settle = _events(rt, EVENT_EXPLORATION_SETTLE)[-1]
    assert settle["current_asset"]["asset_id"] == "8a1d5f2b-6c3e-4d90-a2b7-5e9f0c1d8a44"

    sid = uuid.UUID("0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910")
    msgs = project_messages(sid, rt.event_store)
    settle_msgs = [
        m
        for m in msgs
        if m["type"] == "narrative" and "在「渡口」" in m["payload"]["text"]
    ]
    assert settle_msgs
    assert (
        settle_msgs[0]["payload"]["current_asset"]["asset_id"]
        == "8a1d5f2b-6c3e-4d90-a2b7-5e9f0c1d8a44"
    )


async def test_legacy_script_keeps_all_characters_reacting():
    rt = _make_runtime(with_map=False)
    result = await _to_stage3(rt)
    assert result.state["stage"] == "stage3_extending"
    assert rt._exploration_present() == ("乙", "丙")
    assert rt.export_state()["scene_options"] == []


async def test_director_options_drive_stage3_interaction():
    """M6：有导演输出时交互点用导演选项；没有时回退已验证提议。"""
    rt = _make_runtime(
        llm=FakeLLMService(director_output='{"options": ["与船夫攀谈", "检查船绳"]}')
    )
    result = await _to_stage3(rt)

    labels = [o["text"] for o in result.active_interaction["options"]]
    assert labels == ["与船夫攀谈", "检查船绳"]


async def test_director_options_drop_absent_characters():
    """导演点名不在当前地点的人时，该选项被丢弃，别的选项保留。"""
    rt = _make_runtime()
    await _to_stage3(rt)
    # 测试剧本用单字名，生产过滤会跳过单字名（避免与普通用字撞车），
    # 这里直接喂多字名验证过滤规则本身。
    rt._exploration_present = lambda: ("船夫",)  # type: ignore[method-assign]
    rt._known_names = lambda: ["船夫", "过路人"]  # type: ignore[method-assign]

    labels = rt._filter_absent_mentions(
        ["问船夫船何时开", "让过路人带路", "查看船绳"]
    )
    assert labels == ["问船夫船何时开", "查看船绳"]


async def test_absent_name_inside_longer_present_name_is_not_matched():
    """单字名「父」出现在在场的「父亲」里时不算点名缺席者。"""
    rt = _make_runtime()
    await _to_stage3(rt)
    rt._exploration_present = lambda: ("父亲",)  # type: ignore[method-assign]
    rt._known_names = lambda: ["父亲", "父"]  # type: ignore[method-assign]

    assert rt._filter_absent_mentions(
        ["向父亲问安", "向父问安"]
    ) == ["向父亲问安"]


async def test_character_speech_splits_stage_direction():
    """角色回复里的（动作）拆成 stage_direction，台词只留说出口的部分。"""
    rt = _make_runtime()
    await _to_stage3(rt)

    async def fake_react(name: str, action, stage: str) -> str:
        return "（点头）好，这就开船。"

    rt._react = fake_react  # type: ignore[method-assign]
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})

    speeches = _events(rt, EVENT_CHARACTER_SPEECH)
    assert speeches[-1]["text"] == "好，这就开船。"
    assert speeches[-1]["stage_direction"] == "点头"
