"""PromptBundle：稳定 system 的 golden 指纹、槽位契约与纯函数性质。

改 prompt 文本会让 system 指纹变化——这是有意的：同步升 `*_PROMPT_VERSION` 并更新
本文件的期望指纹，别让 system 悄悄漂移。
"""

from __future__ import annotations

import hashlib

from app.domain.agents.prompting import (
    CHARACTER_MEMORY_LIMIT,
    CHARACTER_SLOTS,
    CHRONICLER_SLOTS,
    DIRECTOR_LAST_OPTIONS_LIMIT,
    DIRECTOR_PLOT_LIMIT,
    DIRECTOR_PUBLIC_FACTS_LIMIT,
    DIRECTOR_RECENT_SPEECH_LIMIT,
    DIRECTOR_SLOTS,
    VERIFIER_SLOTS,
    WORLD_BUILDER_SLOTS,
    build_character_prompt,
    build_character_system,
    build_chronicler_prompt,
    build_director_prompt,
    build_verify_prompt,
    build_world_builder_prompt,
)
from app.domain.game.types import Proposal

FINGERPRINTS = {
    "character": "c63aec53bf63fffa201870595b856208fe0a1b3c0aec91f4f662ff36ea56be0a",
    "director": "0987240d856be917fd3f38ae50b00b4ccf6f13d473dc5d20fcd9922aa6073779",
    "world_builder": "ed4bb34355b1b1084ff310fe9829cdb25ab7f750e4956dbaf945db5fcb3d1130",
    "verify": "c64f9583f351e61aa4f2800b7a9673dba5255faf2ea37fa04243b6bc09e90bbd",
    "chronicler": "d56cc9f7dd9e663f98aa16d540eea3736f99cb3bb0dfb5377b3701eb771ef743",
}


def _character_system() -> str:
    return build_character_system()


def _director_context() -> dict:
    return {
        "location_title": "渡口",
        "visual_summary": "雨后的渡口",
        "player_role": "甲",
        "present": [("乙", "船夫")],
        "plot_log": ["船靠岸"],
        "direction": {"conflict": "船要走了"},
        "chronicle_tail": "渡口起风了，船夫把船绳收紧。",
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


def test_system_prompt_fingerprints_are_golden():
    verify = build_verify_prompt(
        Proposal(proposal_id=1, proposed_by="杜甫", description="把船拉回岸边"), "stage3"
    )
    chronicler = build_chronicler_prompt(
        chronicle_tail="上一段", events_text="本轮发生的事"
    )
    fingerprints = {
        "character": hashlib.sha256(_character_system().encode()).hexdigest(),
        "director": build_director_prompt(_director_context()).system_fingerprint(),
        "world_builder": build_world_builder_prompt(
            "叫船夫过来", _world_builder_context()
        ).system_fingerprint(),
        "verify": verify.system_fingerprint(),
        "chronicler": chronicler.system_fingerprint(),
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
            "chronicle_tail": "另一段编年史",
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


def test_character_system_is_shared_and_persona_lives_in_user():
    system = build_character_system()
    first = build_character_prompt(
        name="甲",
        background="渡客",
        knows=["甲知道船夫收了官府的银子"],
        chronicle="甲在渡口看见船夫收了一封信。",
        instruction="propose_action",
    )
    other = build_character_prompt(
        name="乙",
        background="船夫",
        knows=["乙收了官府的银子"],
        chronicle="乙在渡口收了一封信。",
        instruction="react",
    )
    assert first.system == other.system == system
    assert "甲" in first.user
    assert "乙" not in first.user
    assert "船夫收了官府的银子" in first.user
    assert "不知道的事" not in first.user
    assert "剧情还原" not in first.user
    assert "甲在渡口看见" in first.user


def test_slot_declarations_cover_required_memory_layers():
    character_names = {slot.name for slot in CHARACTER_SLOTS}
    assert {
        "persona",
        "private_knowledge",
        "chronicle",
        "recent_speech",
        "personal_log",
        "rejected_proposals",
        "current_situation",
        "world_facts",
        "long_term_summary",
    } <= character_names
    director_names = {slot.name for slot in DIRECTOR_SLOTS}
    assert {
        "location",
        "visual_summary",
        "present",
        "player_role",
        "direction",
        "recent_plot",
        "recent_speeches",
        "public_facts",
        "last_options",
        "chronicle_tail",
        "teaching_focus",
    } <= director_names
    assert "goals" not in director_names
    assert {slot.name for slot in WORLD_BUILDER_SLOTS} >= {"current_location", "budgets"}
    assert {slot.name for slot in VERIFIER_SLOTS} >= {"proposal"}
    assert {slot.name for slot in CHRONICLER_SLOTS} >= {
        "previous_chronicle",
        "round_events",
    }
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
        *CHRONICLER_SLOTS,
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


def test_chronicler_prompt_is_incremental():
    bundle = build_chronicler_prompt(
        chronicle_tail="渡口起风了。", events_text="- 乙：船要走了。"
    )
    assert "只写本轮" in bundle.user
    assert "渡口起风了" in bundle.user
    assert "船要走了" in bundle.user
    assert bundle.system == build_chronicler_prompt(
        chronicle_tail="", events_text=""
    ).system
