"""玩家干涉世界（M6）：WorldBuilder 解析 → 确定性校验 → 事件化应用 → 可回滚。

覆盖 design play-through-redesign §B5：建场景/新增角色/拉人入场、预算
（每会话 3 场景 / 2 角色、每轮 ≤1 次）、驳回路径、回溯到创建之前即不存在。
"""

from __future__ import annotations

from conftest import FakeLLMService
from test_exploration import _events, _map, _script, _to_stage3

from app.domain.agents.world_builder import (
    KIND_ADD_CHARACTER,
    KIND_CREATE_SCENE,
    KIND_PULL_IN_CHARACTER,
    InterventionIntent,
)
from app.domain.game.event import (
    EVENT_CHARACTER_CREATED,
    EVENT_EXPLORATION_SETTLE,
    EVENT_INTERVENTION_REJECTED,
    EVENT_INTERVENTION_REQUESTED,
    EVENT_PULL_IN_CHARACTER,
    EVENT_SCENE_CREATED,
    EVENT_SCENE_SWITCH,
    EventStore,
)
from app.domain.game.game_runtime import GameRuntime


def _make_runtime(
    *, world_builder_output: str = '{"kind":"reject","reason":"测试环境不做干涉"}',
) -> GameRuntime:
    return GameRuntime(
        session_id="intervene-session",
        script=_script(),
        llm=FakeLLMService(world_builder_output=world_builder_output),
        event_store=EventStore(),
        exploration_map=_map(),
    )


class _IntentWorldBuilder:
    """按顺序返回预设意图的 WorldBuilder 桩（绕过 LLM，把校验/应用留给运行时）。"""

    def __init__(self, intents: list[InterventionIntent]) -> None:
        self._intents = list(intents)

    async def parse_intervention(self, text: str, *, context: dict) -> InterventionIntent:
        if self._intents:
            return self._intents.pop(0)
        return InterventionIntent(kind="reject", reason="没有更多预设意图")


def _create_scene(
    title: str = "雨夜客栈", participants: tuple[str, ...] = ("乙",)
) -> InterventionIntent:
    return InterventionIntent(
        kind=KIND_CREATE_SCENE,
        title=title,
        participants=participants,
        visual_summary="油灯照着小院，雨丝斜织。",
    )


def _add_character(
    name: str = "老乞丐",
    brief: str = "在渡口讨生活的老乞丐",
    location_key: str | None = None,
) -> InterventionIntent:
    return InterventionIntent(
        kind=KIND_ADD_CHARACTER,
        name=name,
        brief=brief,
        personality="狡黠",
        location_key=location_key,
    )


def _pull_in(name: str) -> InterventionIntent:
    return InterventionIntent(kind=KIND_PULL_IN_CHARACTER, name=name, reason="他闻讯赶来。")


async def _intervene(rt: GameRuntime, cid: str, text: str = "干涉一下"):
    return await rt.submit(command_id=cid, kind="intervene", payload={"text": text})


async def test_create_scene_applies_event_and_joins_scene_options():
    rt = _make_runtime(world_builder_output=(
        '{"kind":"create_scene","title":"雨夜客栈","participants":["乙"],'
        '"visual_summary":"油灯照着小院"}'
    ))
    await _to_stage3(rt)

    result = await _intervene(rt, "c-i1", "建一个雨夜客栈")

    assert _events(rt, EVENT_INTERVENTION_REQUESTED)[0]["text"] == "建一个雨夜客栈"
    created = _events(rt, EVENT_SCENE_CREATED)
    assert created[0]["scene_key"] == "loc:雨夜客栈"
    assert created[0]["participants"] == ["乙"]
    assert not _events(rt, EVENT_INTERVENTION_REJECTED)
    # 换景列表追加动态场景；配图意图随结果下发（scene_montage，§B5 画师接线）
    options = result.state["scene_options"]
    assert "loc:雨夜客栈" in {o["scene_key"] for o in options}
    assert [i.kind for i in result.asset_requests] == ["scene_montage"]
    assert result.asset_requests[0].scene_key == "loc:雨夜客栈"


async def test_switch_into_created_scene_and_settle_there():
    rt = _make_runtime(world_builder_output=(
        '{"kind":"create_scene","title":"雨夜客栈","participants":["乙"],'
        '"visual_summary":"油灯照着小院"}'
    ))
    await _to_stage3(rt)
    await _intervene(rt, "c-i1")

    result = await rt.submit(
        command_id="c-switch",
        kind="switch_scene",
        payload={"scene_key": "loc:雨夜客栈"},
    )

    switch = _events(rt, EVENT_SCENE_SWITCH)[-1]
    assert switch["to"] == "雨夜客栈"
    assert result.state["scene_title"] == "雨夜客栈"
    assert result.state["scene_key"] == "loc:雨夜客栈"

    # 动态地点同样走确定性结算：在场者（乙）发言，摘要带地点名
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    settle = _events(rt, EVENT_EXPLORATION_SETTLE)[-1]
    assert settle["location_key"] == "雨夜客栈"
    assert "在「雨夜客栈」" in settle["summary"]


async def test_create_scene_budget_caps_at_three_per_session():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder(  # type: ignore[method-assign]
        [_create_scene(f"新地{i}") for i in range(4)]
    ).parse_intervention
    await _to_stage3(rt)

    for n in range(4):
        await _intervene(rt, f"c-i{n}")
        # 每轮 ≤1 次：推进一轮（结算）后才能再次干涉
        if n < 3:
            await rt.submit(
                command_id=f"c-act-{n}", kind="choose_option", payload={"option_id": "0"}
            )

    assert len(_events(rt, EVENT_SCENE_CREATED)) == 3
    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert len(rejections) == 1
    assert "新场景最多 3 个" in rejections[0]["reason"]


async def test_add_character_joins_present_with_provenance_memory():
    rt = _make_runtime(world_builder_output=(
        '{"kind":"add_character","name":"老乞丐",'
        '"brief":"在渡口讨生活的老乞丐","personality":"狡黠"}'
    ))
    await _to_stage3(rt)

    await _intervene(rt, "c-i1", "让一个乞丐加入")

    created = _events(rt, EVENT_CHARACTER_CREATED)
    assert created[0]["name"] == "老乞丐"
    assert created[0]["location_key"] == "harbor"
    assert created[0]["origin"] == "player_intervention"
    # 与剧本角色同一条创建路径：manager 有 agent、当前地点在场列表包含他
    assert "老乞丐" in rt.characters.agents
    assert "老乞丐" in rt._exploration_present()
    # provenance 记忆由事件折叠（与重放同一写者）
    memory = rt.characters.agents["老乞丐"].memory
    assert any("为何" in line or "登场" in line for line in memory.personal_log)


async def test_add_character_rejects_existing_and_player_names():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder([  # type: ignore[method-assign]
        _add_character(name="甲"),  # 玩家自己
        _add_character(name="乙"),  # 剧本角色同名
    ]).parse_intervention
    await _to_stage3(rt)

    await _intervene(rt, "c-i1")
    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert len(rejections) == 1 and "戏里" in rejections[0]["reason"]

    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    await _intervene(rt, "c-i2")
    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert len(rejections) == 2
    assert not _events(rt, EVENT_CHARACTER_CREATED)


async def test_add_character_budget_caps_at_two_per_session():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder(  # type: ignore[method-assign]
        [_add_character(f"新人{i}") for i in range(3)]
    ).parse_intervention
    await _to_stage3(rt)

    for n in range(3):
        await _intervene(rt, f"c-i{n}")
        if n < 2:
            await rt.submit(
                command_id=f"c-act-{n}", kind="choose_option", payload={"option_id": "0"}
            )

    assert len(_events(rt, EVENT_CHARACTER_CREATED)) == 2
    assert "新角色最多 2 个" in _events(rt, EVENT_INTERVENTION_REJECTED)[0]["reason"]


async def test_pull_in_brings_absent_character_and_rejects_present_one():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder(
        [_pull_in("丙"), _pull_in("乙")]
    ).parse_intervention
    await _to_stage3(rt)

    await _intervene(rt, "c-i1", "叫丙过来")
    pulled = _events(rt, EVENT_PULL_IN_CHARACTER)
    assert pulled[0]["name"] == "丙"
    assert pulled[0]["to_scene"] == "loc:harbor"
    assert pulled[0]["reason"] == "他闻讯赶来。"
    assert "丙" in rt._exploration_present()
    # 到场后本轮重新收集提议：丙开始参与
    assert any(p["proposed_by"] == "丙" for p in _events(rt, "proposal"))

    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    await _intervene(rt, "c-i2", "把乙也叫来")
    assert any("已经在这里了" in r["reason"] for r in _events(rt, EVENT_INTERVENTION_REJECTED))


async def test_rejected_intervention_keeps_interaction_point():
    rt = _make_runtime()  # 默认 world_builder_output = reject
    result = await _to_stage3(rt)
    before = result.active_interaction

    result = await _intervene(rt, "c-i1", "把天捅破")

    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert rejections[0]["reason"] == "测试环境不做干涉"
    assert result.active_interaction is not None
    assert result.active_interaction["mode"] == before["mode"]
    assert not _events(rt, EVENT_SCENE_CREATED)


async def test_intervention_does_not_consume_round_budget():
    rt = _make_runtime(world_builder_output='{"kind":"create_scene","title":"雨夜客栈"}')
    result = await _to_stage3(rt)
    rounds_before = result.state["stage3_round_taken"]

    result = await _intervene(rt, "c-i1")

    assert result.state["stage3_round_taken"] == rounds_before


async def test_only_one_intervention_per_round():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder(
        [_create_scene(), _create_scene("另一处")]
    ).parse_intervention
    await _to_stage3(rt)

    await _intervene(rt, "c-i1")
    assert len(_events(rt, EVENT_SCENE_CREATED)) == 1

    await _intervene(rt, "c-i2")  # 同一轮第二次：确定性拒绝，不调 WorldBuilder
    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert len(rejections) == 1 and "本轮" in rejections[0]["reason"]
    assert len(_events(rt, EVENT_SCENE_CREATED)) == 1

    # 推进一轮后再次允许
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    await _intervene(rt, "c-i3")
    assert len(_events(rt, EVENT_SCENE_CREATED)) == 2


async def test_rollback_before_intervention_erases_created_scene():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder([_create_scene()]).parse_intervention
    await _to_stage3(rt)

    # 拍 = exploration_settle：回溯到它之前，之后创建的场景不再存在
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    settle_event = next(
        e for e in rt.event_store.active_events() if e.event_type == EVENT_EXPLORATION_SETTLE
    )
    await _intervene(rt, "c-i1", "建一个客栈")
    assert "loc:雨夜客栈" in {o["scene_key"] for o in rt.export_state()["scene_options"]}

    await rt.submit(
        command_id="c-rb",
        kind="rollback_to_event",
        payload={"target_event_id": settle_event.event_id},
    )

    assert "loc:雨夜客栈" not in {
        o["scene_key"] for o in rt.export_state()["scene_options"]
    }
    assert not _events(rt, EVENT_SCENE_CREATED)


async def test_rollback_before_intervention_erases_created_character():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder([_add_character()]).parse_intervention
    await _to_stage3(rt)

    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    settle_event = next(
        e for e in rt.event_store.active_events() if e.event_type == EVENT_EXPLORATION_SETTLE
    )
    await _intervene(rt, "c-i1", "让乞丐加入")
    assert "老乞丐" in rt.characters.agents

    await rt.submit(
        command_id="c-rb",
        kind="rollback_to_event",
        payload={"target_event_id": settle_event.event_id},
    )

    assert "老乞丐" not in rt.characters.agents
    assert not _events(rt, EVENT_CHARACTER_CREATED)


async def test_create_scene_duplicate_title_rejected():
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder(
        [
            _create_scene(title="渡口"),
            _create_scene(title="雨夜客栈"),
            _create_scene(title="雨夜客栈"),
        ]
    ).parse_intervention
    await _to_stage3(rt)

    await _intervene(rt, "c-i1")  # 与静态地点同名
    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert "已经存在" in rejections[0]["reason"]

    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    await _intervene(rt, "c-i2")
    await rt.submit(command_id="c-act-2", kind="choose_option", payload={"option_id": "0"})
    await _intervene(rt, "c-i3")  # 动态场景同名
    rejections = _events(rt, EVENT_INTERVENTION_REJECTED)
    assert len(rejections) == 2


async def test_add_character_accepts_title_or_key_location():
    """WorldBuilder 的 location_key 可能回标题（LLM 只见标题）：两种都认（§B5 修复）。"""
    rt = _make_runtime()
    rt.world_builder.parse_intervention = _IntentWorldBuilder(
        [
            _add_character(name="阿四", location_key="客栈"),  # 标题
            _add_character(name="阿五", location_key="market"),  # key
        ]
    ).parse_intervention
    await _to_stage3(rt)

    await _intervene(rt, "c-i1", "让阿四去客栈")
    created = _events(rt, EVENT_CHARACTER_CREATED)[0]
    assert created["location_key"] == "inn"
    assert "阿四" in rt._world.members_at("loc:inn")

    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    await _intervene(rt, "c-i2", "让阿五去集市")
    created = _events(rt, EVENT_CHARACTER_CREATED)[1]
    assert created["location_key"] == "market"
    assert "阿五" not in rt._exploration_present()  # 他不在当前地点
