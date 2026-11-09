"""PromptBundle：稳定 system 的 golden 指纹、槽位契约与纯函数性质。

改 prompt 文本会让 system 指纹变化——这是有意的：同步升 `*_PROMPT_VERSION` 并更新
本文件的期望指纹，别让 system 悄悄漂移。
"""

from __future__ import annotations

import hashlib

from app.domain.agents.prompting import (
    CHARACTER_MEMORY_LIMIT,
    CHARACTER_SLOTS,
    DIRECTOR_LAST_OPTIONS_LIMIT,
    DIRECTOR_PLOT_LIMIT,
    DIRECTOR_PUBLIC_FACTS_LIMIT,
    DIRECTOR_RECENT_SPEECH_LIMIT,
    DIRECTOR_SLOTS,
    GOAL_JUDGE_SLOTS,
    STAGE3_GOALS_SLOTS,
    VERIFIER_SLOTS,
    WORLD_BUILDER_SLOTS,
    build_character_system,
    build_director_prompt,
    build_goal_judge_prompt,
    build_stage3_goals_prompt,
    build_verify_prompt,
    build_world_builder_prompt,
)
from app.domain.game.goals import GoalState
from app.domain.game.types import Beat, CharacterSetting, Proposal, Scene, Script

FINGERPRINTS = {
    "character": "14f6c4b3e540f779b77ce9d64aeeefc1cd6c8b55c9da8ba155813084b40b1d1e",
    "director": "ec08fd83a6f71494e3bc559dce2f054ab45a790de4e0176e2e19efb989112202",
    "world_builder": "ed4bb34355b1b1084ff310fe9829cdb25ab7f750e4956dbaf945db5fcb3d1130",
    "verify": "c64f9583f351e61aa4f2800b7a9673dba5255faf2ea37fa04243b6bc09e90bbd",
    "goal_judge": "e5cf73ba51fe7cf595794386878f19e1102142f927319c74d6e85b0c6dc2c00f",
    "stage3_goals": "9469f9edc39546e47d65b269566241f082147bd46194c4bae2325230e5772d83",
}


def _character_system() -> str:
    return build_character_system(
        name="杜甫",
        public_background="诗人，与李白同游",
        personality_traits=["沉郁", "重情"],
        speech_style="自称「甫」",
        knows=["与李白同游"],
        not_knows=["高适的军情"],
    )


def _director_context() -> dict:
    return {
        "location_title": "渡口",
        "visual_summary": "雨后的渡口",
        "player_role": "甲",
        "present": [("乙", "船夫")],
        "plot_log": ["船靠岸"],
        "direction": {"conflict": "船要走了"},
        "goals": [("劝船夫再等一会儿", False)],
        "teaching_focus": ["同舟共济"],
        "recent_speeches": [("船夫", "再不走就涨潮了")],
        "last_options": ["看看四周"],
        "public_facts": ["昨夜上游下了暴雨"],
    }


def _world_builder_context() -> dict:
    return {
        "location_title": "客栈",
        "visited_titles": ["渡口", "客栈"],
        "locations": [{"key": "inn", "title": "客栈"}],
        "roster": ["船夫", "丙"],
        "player_role": "甲",
        "budgets": {"scenes_left": 3, "characters_left": 2},
    }


def _script() -> Script:
    return Script(
        title="最小集测试剧本",
        characters=[CharacterSetting(name="李白", public_background="诗人")],
        scenes=[Scene(scene_id=1, title="相遇", beats=[Beat(beat_id=1, description="相遇")])],
        stage2_ending_beat_id=1,
        teaching_focus=["同舟共济"],
    )


def _pending_goals() -> list[GoalState]:
    return [GoalState(1, "劝船夫留下"), GoalState(2, "让船夫改变态度")]


def test_system_prompt_fingerprints_are_golden():
    verify = build_verify_prompt(
        Proposal(proposal_id=1, proposed_by="杜甫", description="把船拉回岸边"), "stage3"
    )
    goal_judge = build_goal_judge_prompt(
        _pending_goals(),
        player_role="甲",
        action="向船夫道歉",
        reactions=[("船夫", "好吧，再等一会儿。")],
    )
    stage3_goals = build_stage3_goals_prompt(
        _script(), player_role="李白", plot_log=["船靠岸"]
    )
    fingerprints = {
        "character": hashlib.sha256(_character_system().encode()).hexdigest(),
        "director": build_director_prompt(_director_context()).system_fingerprint(),
        "world_builder": build_world_builder_prompt(
            "叫船夫过来", _world_builder_context()
        ).system_fingerprint(),
        "verify": verify.system_fingerprint(),
        "goal_judge": goal_judge.system_fingerprint(),
        "stage3_goals": stage3_goals.system_fingerprint(),
    }
    assert fingerprints == FINGERPRINTS


def test_dynamic_context_never_leaks_into_system():
    base = build_director_prompt(_director_context())
    changed = build_director_prompt(
        {
            **_director_context(),
            "recent_speeches": [("丙", "另外一个人说的话")],
            "public_facts": ["另一个世界事实"],
            "last_options": ["另一个选项"],
        }
    )
    assert base.system == changed.system
    assert "另外一个人说的话" not in base.system
    assert "另外一个人说的话" in changed.user


def test_prompt_bundle_messages_shape_and_purity():
    bundle = build_director_prompt(_director_context())
    assert bundle.messages() == [
        {"role": "system", "content": bundle.system},
        {"role": "user", "content": bundle.user},
    ]
    assert bundle == build_director_prompt(_director_context())


def test_character_system_is_stable_and_identity_sensitive():
    first = _character_system()
    assert first == _character_system()
    other = build_character_system(
        name="高适",
        public_background="边塞诗人",
        personality_traits=["豪迈"],
        speech_style="",
        knows=[],
        not_knows=[],
    )
    assert other != first


def test_slot_declarations_cover_required_memory_layers():
    character_names = {slot.name for slot in CHARACTER_SLOTS}
    assert {
        "persona",
        "knowledge_boundary",
        "recent_speech",
        "personal_log",
        "rejected_proposals",
        "current_situation",
        "world_facts",
        "long_term_summary",
    } <= character_names
    assert {slot.name for slot in DIRECTOR_SLOTS} >= {
        "location",
        "visual_summary",
        "present",
        "player_role",
        "direction",
        "recent_plot",
        "recent_speeches",
        "public_facts",
        "last_options",
        "goals",
        "teaching_focus",
    }
    assert {slot.name for slot in WORLD_BUILDER_SLOTS} >= {"current_location", "budgets"}
    assert {slot.name for slot in VERIFIER_SLOTS} >= {"proposal"}
    assert {slot.name for slot in GOAL_JUDGE_SLOTS} >= {"pending_goals", "reactions"}
    assert {slot.name for slot in STAGE3_GOALS_SLOTS} >= {"teaching_focus", "recent_plot"}
    recent_speech = next(slot for slot in CHARACTER_SLOTS if slot.name == "recent_speech")
    assert recent_speech.limit == CHARACTER_MEMORY_LIMIT
    long_term = next(slot for slot in CHARACTER_SLOTS if slot.name == "long_term_summary")
    assert long_term.note, "未接线槽位必须标注 note，避免契约名不副实"


def test_slot_metadata_uses_known_values():
    slots = [
        *CHARACTER_SLOTS,
        *DIRECTOR_SLOTS,
        *WORLD_BUILDER_SLOTS,
        *VERIFIER_SLOTS,
        *GOAL_JUDGE_SLOTS,
        *STAGE3_GOALS_SLOTS,
    ]
    for slot in slots:
        assert slot.visibility in {"self", "public", "scoped", "staff", "n/a"}, slot.name
        assert (
            slot.section in {"system", "user", "not_injected"}
            or slot.section.startswith("tool:")
        ), slot.name
        assert slot.fallback, slot.name
        assert slot.limit is None or slot.limit > 0, slot.name


def test_director_slot_limits_are_applied():
    context = _director_context()
    context["plot_log"] = [f"第{i}拍" for i in range(DIRECTOR_PLOT_LIMIT + 3)]
    context["recent_speeches"] = [
        (f"角色{i}", f"台词{i}")
        for i in range(DIRECTOR_RECENT_SPEECH_LIMIT + 3)
    ]
    context["public_facts"] = [
        f"事实{i}" for i in range(DIRECTOR_PUBLIC_FACTS_LIMIT + 3)
    ]
    context["last_options"] = [
        f"选项{i}" for i in range(DIRECTOR_LAST_OPTIONS_LIMIT + 3)
    ]
    user = build_director_prompt(context).user
    assert f"第{DIRECTOR_PLOT_LIMIT + 2}拍" in user
    assert "第0拍" not in user
    assert f"角色{DIRECTOR_RECENT_SPEECH_LIMIT + 2}" in user
    assert "角色0：台词0" not in user
    assert f"事实{DIRECTOR_PUBLIC_FACTS_LIMIT + 2}" in user
    assert "事实0" not in user
    assert f"选项{DIRECTOR_LAST_OPTIONS_LIMIT + 2}" in user
    assert "选项0" not in user
    assert CHARACTER_MEMORY_LIMIT == 10
