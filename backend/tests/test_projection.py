"""契约投影与剧本转换测试（#5 接缝①③的纯单元部分，无 DB 依赖）。"""

from __future__ import annotations

import uuid

from app.contracts.runtime import RuntimeUpdate
from app.domain.game.script_adapter import script_package_to_script
from app.services.session_projection import project_state, project_update

_SID = uuid.UUID("0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910")


def test_script_package_to_script_maps_engine_fields():
    from app.contracts.script import (
        Beat,
        CharacterProfile,
        Scene,
        ScriptPackage,
    )

    pkg = ScriptPackage(
        title="背影",
        characters=[
            CharacterProfile(
                name="父亲",
                public_background="中年父亲",
                is_player_playable=False,
            ),
            CharacterProfile(
                name="儿子",
                public_background="二十岁青年",
                is_player_playable=True,
            ),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="浦口送别",
                participants=["父亲", "儿子"],
                beats=[
                    Beat(beat_id=1, description="父亲送行"),
                    Beat(beat_id=2, description="买橘子"),
                ],
            )
        ],
        teaching_focus=["白描手法"],
        playable_roles=["儿子"],
        stage2_ending_beat_id=2,
    )
    script = script_package_to_script(pkg)
    assert script.title == "背影"
    assert [c.name for c in script.characters] == ["父亲", "儿子"]
    # playable_roles 是可扮演的权威来源
    assert [c.is_player_playable for c in script.characters] == [False, True]
    assert script.scenes[0].beats[1].description == "买橘子"
    assert script.stage2_ending_beat_id == 2


async def test_project_update_from_runtime_step(make_runtime):
    """StepResult/export_state → RuntimeUpdate：契约可往返、UUID/sequence 确定性。"""
    rt = make_runtime(session_id=str(_SID))
    await rt.start()
    result = await rt.submit(
        command_id="c1", kind="select_role", payload={"role_name": "李白"}
    )

    update = project_update(_SID, rt.event_store, result)
    dumped = update.model_dump(mode="json")
    again = RuntimeUpdate.model_validate(dumped)
    assert again == update

    assert update.session_id == _SID
    assert update.state.stage.value == "stage2_reenacting"
    assert update.state.plot_context["player_role"] == "李白"
    assert update.new_events, "新命令应产生事件引用"
    # 确定性：同一事件重复投影得到同一 UUID
    ev = update.new_events[0]
    dup = project_update(_SID, rt.event_store, result).new_events[0]
    assert ev.event_id == dup.event_id
    assert ev.sequence == dup.sequence


async def test_project_state_attributes(make_runtime):
    rt = make_runtime(session_id=str(_SID))
    await rt.start()
    export = rt.export_state()
    state = project_state(_SID, rt.event_store, export)
    assert state.stage.value == "stage1_complete"
    assert state.last_sequence == len(rt.event_store.active_events()) - 1
    assert state.active_interaction is None  # stage1 停靠点无交互
    assert isinstance(state.character_memories, dict)


async def test_project_interaction_options(make_runtime):
    rt = make_runtime(session_id=str(_SID))
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    export = rt.export_state()
    state = project_state(_SID, rt.event_store, export)
    ix = state.active_interaction
    assert ix is not None
    assert ix.mode.value == "options"
    assert ix.options, "交互点应带选项"
    assert all(o.option_id and o.label for o in ix.options)
