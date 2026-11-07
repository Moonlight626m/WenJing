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
    EVENT_CHARACTER_SPEECH,
    EVENT_EXPLORATION_SETTLE,
    EVENT_SCENE_SWITCH,
    EventStore,
)
from app.domain.game.exploration import (
    ExplorationProgress,
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


def _make_runtime(*, with_map: bool = True) -> GameRuntime:
    return GameRuntime(
        session_id="explore-session",
        script=_script(),
        llm=FakeLLMService(),
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


async def test_legacy_script_keeps_all_characters_reacting():
    rt = _make_runtime(with_map=False)
    result = await _to_stage3(rt)
    assert result.state["stage"] == "stage3_extending"
    assert rt._exploration_present() == ("乙", "丙")
    assert rt.export_state()["scene_options"] == []
