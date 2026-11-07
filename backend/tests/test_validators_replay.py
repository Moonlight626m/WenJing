"""珊瑚图确定性校验（`validate_replay`）单元测试。

旧剧本（无 options/dialogue/endings）必须恒通过；新剧本的选项目标、
结局、返回边、环、台词 speaker 由这里把关。文本质量仍归 doubter。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.script import ScriptPackage
from app.domain.generation.validators import validate_replay

_FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def _scene(scene_id: int = 1, **overrides) -> dict:
    scene = {
        "scene_id": scene_id,
        "title": f"场景{scene_id}",
        "participants": ["甲"],
        "beats": [{"beat_id": scene_id, "description": f"节拍{scene_id}"}],
    }
    scene.update(overrides)
    return scene


def _pkg(scenes: list[dict], endings: list[dict] | None = None) -> ScriptPackage:
    data = {
        "title": "校验样例",
        "characters": [{"name": "甲", "public_background": "背景"}],
        "scenes": scenes,
        "playable_roles": ["甲"],
        "stage2_ending_beat_id": 1,
    }
    if endings is not None:
        data["endings"] = endings
    return ScriptPackage.model_validate(data)


_CANONICAL = [
    {
        "ending_id": "e1",
        "title": "正途",
        "kind": "canonical",
        "description": "",
    }
]


def test_legacy_package_without_graph_passes():
    assert validate_replay(_pkg([_scene()])) == []


def test_fixture_package_passes():
    pkg = ScriptPackage.model_validate(
        json.loads((_FIXTURES / "script_package.json").read_text())
    )
    assert validate_replay(pkg) == []


def test_unknown_option_targets_are_reported():
    scene = _scene(
        options=[
            {"option_id": "o1", "label": "去分支", "kind": "canonical", "branch_id": "b9"},
            {"option_id": "o2", "label": "去场景", "kind": "canonical", "target_scene_id": 9},
            {"option_id": "o3", "label": "去结局", "kind": "canonical", "ending_id": "e9"},
        ]
    )
    issues = validate_replay(_pkg([scene], _CANONICAL))
    assert any("unknown branch b9" in i for i in issues)
    assert any("unknown scene 9" in i for i in issues)
    assert any("unknown ending e9" in i for i in issues)


def test_option_with_multiple_targets_rejected():
    scene = _scene(
        options=[
            {
                "option_id": "o1",
                "label": "x",
                "kind": "canonical",
                "branch_id": "b1",
                "ending_id": "e1",
            }
        ],
        branches=[
            {
                "branch_id": "b1",
                "label": "分支",
                "title": "分支",
                "beats": [{"beat_id": 1, "description": "d"}],
            }
        ],
    )
    issues = validate_replay(_pkg([scene], _CANONICAL))
    assert any("multiple targets" in i for i in issues)


def test_too_many_distractors_rejected():
    options = [
        {"option_id": f"d{i}", "label": "干扰", "kind": "distractor"}
        for i in range(3)
    ]
    issues = validate_replay(_pkg([_scene(options=options)], _CANONICAL))
    assert any("2 distractor" in i for i in issues)


def test_dialogue_speaker_must_be_participant():
    scene = _scene(
        beats=[
            {
                "beat_id": 1,
                "description": "d",
                "dialogue": [{"text": "你好", "speaker": "乙"}],
            }
        ]
    )
    issues = validate_replay(_pkg([scene]))
    assert any("speaker not in participants: 乙" in i for i in issues)


def test_branch_dialogue_limit():
    branch = {
        "branch_id": "b1",
        "label": "分支",
        "title": "分支",
        "beats": [{"beat_id": 1, "description": "d"}],
        "dialogue": [{"text": "话"} for _ in range(5)],
    }
    scene = _scene(branches=[branch])
    issues = validate_replay(_pkg([scene], _CANONICAL))
    assert any("more than 4 dialogue" in i for i in issues)


def test_implicit_cycle_rejected():
    scenes = [
        _scene(
            1,
            options=[
                {"option_id": "o1", "label": "去二", "kind": "canonical", "target_scene_id": 2}
            ],
        ),
        _scene(
            2,
            options=[
                {"option_id": "o2", "label": "回一", "kind": "canonical", "target_scene_id": 1}
            ],
        ),
    ]
    issues = validate_replay(_pkg(scenes, _CANONICAL))
    assert any("implicit cycle" in i for i in issues)


def test_choice_return_is_not_a_cycle():
    """`choice` 回决策点是同一决策点重展示，不算环。"""
    branch = {
        "branch_id": "b1",
        "label": "分支",
        "title": "分支",
        "beats": [{"beat_id": 1, "description": "d"}],
        "return_mode": "choice",
    }
    scene = _scene(
        options=[{"option_id": "o1", "label": "看分支", "kind": "canonical", "branch_id": "b1"}],
        branches=[branch],
    )
    assert not any("implicit cycle" in i for i in validate_replay(_pkg([scene], _CANONICAL)))


def test_canonical_path_without_canonical_ending_rejected():
    branch = {
        "branch_id": "b1",
        "label": "分支",
        "title": "分支",
        "beats": [{"beat_id": 1, "description": "d"}],
        "return_mode": "choice",
    }
    scenes = [
        _scene(
            1,
            options=[
                {"option_id": "o1", "label": "去二", "kind": "canonical", "target_scene_id": 2}
            ],
        ),
        _scene(
            2,
            options=[
                {"option_id": "o2", "label": "看分支", "kind": "canonical", "branch_id": "b1"}
            ],
            branches=[branch],
        ),
    ]
    issues = validate_replay(_pkg(scenes, _CANONICAL))
    assert any("canonical path does not reach" in i for i in issues)


def test_graph_requires_canonical_ending():
    scene = _scene(
        options=[{"option_id": "o1", "label": "x", "kind": "canonical"}],
    )
    issues = validate_replay(_pkg([scene], []))
    assert any("requires endings" in i for i in issues)
