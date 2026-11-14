"""生成期探索地图派生（design stage3-chronicle-redesign §5.1）。"""

from __future__ import annotations

import pytest

from app.contracts.script import (
    Beat,
    CharacterProfile,
    Scene,
    ScriptPackage,
    VisualNotes,
)
from app.domain.generation.workflow.nodes import WorkflowNodes, derive_exploration_map
from app.infrastructure.errx import Error, codes


def _package() -> ScriptPackage:
    return ScriptPackage(
        title="渡口",
        characters=[
            CharacterProfile(name="甲", public_background="渡客"),
            CharacterProfile(name="乙", public_background="船夫"),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="渡口",
                participants=["甲", "乙"],
                beats=[Beat(beat_id=1, description="船靠岸")],
                visual_notes=VisualNotes(location="渡口", weather="雨后"),
            ),
            Scene(
                scene_id=2,
                title="客栈",
                participants=["乙"],
                beats=[Beat(beat_id=2, description="灯下对坐")],
            ),
        ],
        teaching_focus=["同舟共济", "人物关系的转变"],
        playable_roles=["甲"],
        stage2_ending_beat_id=1,
    )


def test_derive_exploration_map_from_scenes():
    exploration = derive_exploration_map(_package())

    assert exploration.start_location_key == "scene_1"
    assert [loc.location_key for loc in exploration.locations] == [
        "scene_1",
        "scene_2",
    ]
    assert exploration.locations[0].title == "渡口"
    assert exploration.locations[0].participants == ["甲", "乙"]
    # 摘要带字段标签：画师要知道哪一段是地点、哪一段是天气/服饰
    assert exploration.locations[0].visual_summary == "地点：渡口；天气：雨后"
    # 没有 visual_notes 时退回场景标题，不编造地点
    assert exploration.locations[1].visual_summary == "客栈的场景"
    assert exploration.ending_brief == "同舟共济；人物关系的转变"


def test_visual_summary_keeps_era_anchors_and_drops_placeholders():
    """era 里的服饰/器物是画师定年代与人物的依据；「原文未交代」不该进提示词。"""
    package = _package()
    package.scenes[0].visual_notes = VisualNotes(
        era="黑布小帽、深青布棉袍",
        location="渡口",
        time_of_day="原文未交代",
        weather="",
        mood="离别感伤",
    )

    summary = derive_exploration_map(package).locations[0].visual_summary

    assert summary == "时代与服饰：黑布小帽、深青布棉袍；地点：渡口；氛围：离别感伤"
    assert "原文未交代" not in summary


async def test_design_exploration_node_is_idempotent_and_fills_package():
    nodes = WorkflowNodes(llm=None)  # 该节点不调用 LLM
    package = _package()

    result = await nodes.design_exploration({"package": package})

    assert result["package"].exploration is not None
    assert result["package"].exploration.start_location_key == "scene_1"

    # 已有地图（教师编辑/重跑带回）保持原样
    again = await nodes.design_exploration({"package": result["package"]})
    assert again["package"].exploration == result["package"].exploration


def test_unknown_participants_are_dropped():
    package = _package()
    package.scenes[0].participants = ["甲", "不存在的人"]

    exploration = derive_exploration_map(package)
    assert exploration.locations[0].participants == ["甲"]


def test_empty_scenes_fail_explicitly():
    package = _package()
    package.scenes = []

    with pytest.raises(Error) as excinfo:
        derive_exploration_map(package)
    assert excinfo.value.code == codes.CNT_GENERATION_FAILED


def test_audit_pass_routes_to_design_exploration():
    nodes = WorkflowNodes(llm=None)
    assert nodes.route_after_audit({"audit_verdict": "pass"}) == "design_exploration"
