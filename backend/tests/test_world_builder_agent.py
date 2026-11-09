"""世界构建 Agent（M6）：干涉意图解析与 fail-closed 口径。

解析失败/未知类型/缺字段/未配置 LLM 一律 `reject`——运行时据事件
`intervention_rejected` 提示玩家，绝不让模型输出直接改世界。
"""

from __future__ import annotations

from app.domain.agents.world_builder import (
    KIND_ADD_CHARACTER,
    KIND_CREATE_SCENE,
    KIND_PULL_IN_CHARACTER,
    KIND_REJECT,
    WorldBuilderAgent,
    parse_intent,
)


class _BoomLLM:
    async def chat(self, messages, *, session_id: str = "", purpose=None):
        raise RuntimeError("provider down")


class _FixedLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None):
        self.calls.append(messages)
        return self._text


def test_parse_create_scene():
    raw = (
        '{"kind": "create_scene", "title": "雨夜客栈", '
        '"participants": ["船夫", "船夫", ""], '
        '"visual_summary": "油灯照着小院，雨丝斜织", '
        '"parent_location_key": "harbor"}'
    )
    intent = parse_intent(raw)
    assert intent.kind == KIND_CREATE_SCENE
    assert intent.title == "雨夜客栈"
    assert intent.participants == ("船夫",)  # 去重 + 去空
    assert intent.parent_location_key == "harbor"


def test_parse_create_scene_requires_title():
    assert parse_intent('{"kind": "create_scene"}').kind == KIND_REJECT


def test_parse_add_character():
    raw = (
        '{"kind": "add_character", "name": "老乞丐", '
        '"brief": "在渡口讨生活的老乞丐", "personality": "狡黠", '
        '"location_key": "inn"}'
    )
    intent = parse_intent(raw)
    assert intent.kind == KIND_ADD_CHARACTER
    assert intent.name == "老乞丐"
    assert intent.brief == "在渡口讨生活的老乞丐"
    assert intent.location_key == "inn"


def test_parse_add_character_requires_name_and_brief():
    assert parse_intent('{"kind": "add_character", "name": "老乞丐"}').kind == KIND_REJECT
    assert parse_intent('{"kind": "add_character", "brief": "少一个名字"}').kind == KIND_REJECT


def test_parse_pull_in_character_reason_defaults():
    intent = parse_intent('{"kind": "pull_in_character", "name": "船夫"}')
    assert intent.kind == KIND_PULL_IN_CHARACTER
    assert intent.name == "船夫"
    assert intent.reason
    explicit = parse_intent(
        '{"kind": "pull_in_character", "name": "船夫", "reason": "他闻讯赶来"}'
    )
    assert explicit.reason == "他闻讯赶来"


def test_parse_reject_passthrough():
    intent = parse_intent('{"kind": "reject", "reason": "不能改写课文结局"}')
    assert intent.kind == KIND_REJECT
    assert intent.reason == "不能改写课文结局"


def test_parse_unknown_kind_is_rejected():
    assert parse_intent('{"kind": "teleport", "name": "甲"}').kind == KIND_REJECT


def test_parse_non_json_is_rejected():
    assert parse_intent("让一个乞丐加入").kind == KIND_REJECT


async def test_parse_intervention_degrades_to_reject_without_llm():
    agent = WorldBuilderAgent(_BoomLLM())
    intent = await agent.parse_intervention("建一个客栈", context={})
    assert intent.kind == KIND_REJECT
    assert intent.rejected


async def test_parse_intervention_passes_world_context():
    llm = _FixedLLM('{"kind": "pull_in_character", "name": "船夫"}')
    agent = WorldBuilderAgent(llm)
    intent = await agent.parse_intervention(
        "叫船夫过来",
        context={
            "location_title": "客栈",
            "visited_titles": ["渡口", "客栈"],
            "roster": ["船夫", "丙"],
            "player_role": "甲",
            "budgets": {"scenes_left": 3, "characters_left": 2},
        },
    )
    assert intent.kind == KIND_PULL_IN_CHARACTER
    # 世界上下文必须进 prompt（staff 不挂工具，输入由运行时装配）
    prompt = "\n".join(str(m.get("content", "")) for m in llm.calls[0])
    assert "客栈" in prompt and "船夫" in prompt and "甲" in prompt
