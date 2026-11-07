"""珊瑚图纯 IO 播放（M4）：图派生、决策点、回主干、结局、回溯重演。

约定：
- 旧剧本（无 options/endings）不派生图，运行时仍走 agent 线性路径；
- 珊瑚图播放全程零 LLM：测试用一调就炸的假 LLM 钉住；
- 玩家所选角色的预写台词不播（不替玩家说话），旁白（speaker=None）转叙述。
"""

from __future__ import annotations

import pytest

from app.contracts.script import ScriptPackage
from app.domain.game.event import (
    EVENT_CHARACTER_SPEECH,
    EVENT_PLAYER_ACTION,
    EVENT_REPLAY_CHOICE,
    EVENT_REPLAY_ENDING_REACHED,
    EVENT_REPLAY_NARRATION,
    EVENT_REPLAY_NODE_ENTERED,
    EventStore,
)
from app.domain.game.game_runtime import GameRuntime
from app.domain.game.replay import (
    ReplayDirector,
    ReplayState,
    build_replay_graph,
)
from app.domain.game.script_adapter import script_package_to_script
from app.infrastructure.errx import Error


class _ExplodingLLM:
    """任何调用都算失败：珊瑚图播放不允许碰 LLM。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, *, session_id: str = "", purpose=None):
        self.calls += 1
        raise AssertionError("replay must not call LLM")

    async def astream(self, messages, *, session_id: str = "", purpose=None):
        self.calls += 1
        raise AssertionError("replay must not call LLM")
        yield ""  # pragma: no cover


def _package() -> ScriptPackage:
    """两场珊瑚图：场 1 决策（主线去场 2 / 干扰回决策点），场 2 决策到结局。"""
    return ScriptPackage.model_validate(
        {
            "title": "渡口",
            "characters": [
                {"name": "甲", "public_background": "渡客", "is_player_playable": {"value": True}},
                {"name": "乙", "public_background": "船夫"},
            ],
            "playable_roles": ["甲"],
            "teaching_focus": ["同舟共济"],
            "stage2_ending_beat_id": 3,
            "scenes": [
                {
                    "scene_id": 1,
                    "title": "相遇",
                    "participants": ["甲", "乙"],
                    "beats": [
                        {
                            "beat_id": 1,
                            "description": "两人在渡口相遇",
                            "dialogue": [
                                {"speaker": "乙", "text": "船要开了。"},
                                {"speaker": "甲", "text": "等等我。"},
                                {"text": "江风很冷。"},
                            ],
                        },
                        {"beat_id": 2, "description": "乙提议同行"},
                    ],
                    "interaction_point": {"what_player_can_do": "决定是否上船"},
                    "options": [
                        {
                            "option_id": "o1",
                            "label": "一同上船",
                            "kind": "canonical",
                            "target_scene_id": 2,
                        },
                        {
                            "option_id": "o2",
                            "label": "先看看行李",
                            "kind": "distractor",
                            "branch_id": "b1",
                        },
                    ],
                    "branches": [
                        {
                            "branch_id": "b1",
                            "label": "查看行李",
                            "title": "渡口边",
                            "beats": [{"beat_id": 1, "description": "甲翻看行李"}],
                            "dialogue": [{"speaker": "乙", "text": "快点吧。"}],
                            "return_mode": "choice",
                        }
                    ],
                },
                {
                    "scene_id": 2,
                    "title": "江上",
                    "participants": ["甲", "乙"],
                    "beats": [{"beat_id": 3, "description": "船行江上"}],
                    "interaction_point": {"what_player_can_do": "结束这段路"},
                    "options": [
                        {
                            "option_id": "o3",
                            "label": "抵达",
                            "kind": "canonical",
                            "ending_id": "e1",
                        }
                    ],
                },
            ],
            "endings": [
                {
                    "ending_id": "e1",
                    "title": "同舟",
                    "kind": "canonical",
                    "description": "两人同舟共济。",
                }
            ],
        }
    )


def _make_runtime() -> tuple[GameRuntime, _ExplodingLLM]:
    pkg = _package()
    llm = _ExplodingLLM()
    runtime = GameRuntime(
        session_id="replay-session",
        script=script_package_to_script(pkg),
        llm=llm,
        event_store=EventStore(),
        replay_graph=build_replay_graph(pkg),
    )
    return runtime, llm


def _payloads(rt: GameRuntime, event_type: str) -> list[dict]:
    return [e.payload for e in rt.event_store.active_events() if e.event_type == event_type]


def _option_ids(result) -> list[str]:
    return [str(o["id"]) for o in result.active_interaction["options"]]


# ===== 图派生 =====


def test_legacy_package_has_no_graph():
    legacy = ScriptPackage.model_validate(
        {
            "title": "线性",
            "characters": [{"name": "甲", "public_background": "背景"}],
            "playable_roles": ["甲"],
            "stage2_ending_beat_id": 1,
            "scenes": [
                {"scene_id": 1, "title": "一", "beats": [{"beat_id": 1, "description": "d"}]}
            ],
        }
    )
    assert build_replay_graph(legacy) is None


def test_graph_nodes_and_mainline_ending():
    graph = build_replay_graph(_package())
    assert graph is not None
    assert graph.mainline == ("scene:1", "scene:2")
    assert "scene:1::branch:b1" in graph.by_node
    assert graph.mainline_ending is not None
    assert graph.mainline_ending.ending_id == "e1"


def test_resolve_folds_events_to_state():
    graph = build_replay_graph(_package())
    assert graph is not None
    director = ReplayDirector(graph)
    state, cues = director.start("甲")
    events = [
        {"event_type": cue.event_type, "payload": cue.payload} for cue in cues
    ]
    assert director.resolve(events) == state
    assert state == ReplayState(node_id="scene:1")


# ===== 运行时：开局与台词 =====


async def test_replay_start_plays_narration_and_skips_player_lines():
    rt, llm = _make_runtime()
    await rt.start()
    result = await rt.submit(
        command_id="c1", kind="select_role", payload={"role_name": "甲"}
    )

    assert rt.state.stage == "stage2_reenacting"
    assert _option_ids(result) == ["o1", "o2"]
    assert result.active_interaction["context"] == "决定是否上船"
    # 珊瑚图播放不推 beat 游标；场景信息从播放位置解析
    assert result.state["beat_cursor"] == 0
    assert result.state["scene_key"] == "scene:1"
    assert result.state["scene_title"] == "相遇"

    nodes = _payloads(rt, EVENT_REPLAY_NODE_ENTERED)
    assert [p["node_id"] for p in nodes] == ["scene:1"]
    narration = [p["text"] for p in _payloads(rt, EVENT_REPLAY_NARRATION)]
    assert narration == ["两人在渡口相遇", "江风很冷。", "乙提议同行"]
    speech = [
        (p["speaker"], p["text"], p.get("source"))
        for p in _payloads(rt, EVENT_CHARACTER_SPEECH)
    ]
    # 甲的台词被跳过（玩家自己说）；source=replay 供 Stage3 的 speech_log 使用
    assert speech == [("乙", "船要开了。", "replay")]
    assert llm.calls == 0


# ===== 运行时：决策点 =====


async def test_distractor_branch_returns_to_decision_point():
    rt, _ = _make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "甲"})

    result = await rt.submit(
        command_id="c2", kind="choose_option", payload={"option_id": "o2"}
    )

    assert _option_ids(result) == ["o1", "o2"]
    assert result.active_interaction["context"] == "回到刚才的选择"
    assert _payloads(rt, EVENT_REPLAY_CHOICE)
    assert _payloads(rt, EVENT_REPLAY_NODE_ENTERED)[-1]["node_id"] == (
        "scene:1::branch:b1"
    )
    speech = [p["text"] for p in _payloads(rt, EVENT_CHARACTER_SPEECH)]
    assert speech[-1] == "快点吧。"


async def test_canonical_choice_reaches_ending_and_terminal():
    rt, _ = _make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "甲"})
    result = await rt.submit(
        command_id="c2", kind="choose_option", payload={"option_id": "o1"}
    )
    assert result.state["scene_title"] == "江上"
    assert _option_ids(result) == ["o3"]

    ending = await rt.submit(
        command_id="c3", kind="choose_option", payload={"option_id": "o3"}
    )
    assert ending.state["beat_cursor"] == 3  # 到达结局时游标对齐到末尾
    assert _option_ids(ending) == ["0", "1"]
    assert "同舟" in ending.active_interaction["context"]
    assert [p["ending_id"] for p in _payloads(rt, EVENT_REPLAY_ENDING_REACHED)] == ["e1"]

    done = await rt.submit(
        command_id="c4", kind="choose_option", payload={"option_id": "1"}
    )
    assert done.terminal
    assert done.state["ended"]


async def test_stage2_free_input_is_rejected():
    rt, _ = _make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "甲"})
    with pytest.raises(Error):
        await rt.submit(
            command_id="c2", kind="free_input", payload={"text": "我随便说说"}
        )


async def test_unknown_option_is_rejected():
    rt, _ = _make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "甲"})
    with pytest.raises(Error):
        await rt.submit(
            command_id="c2", kind="choose_option", payload={"option_id": "o9"}
        )


# ===== 运行时：回溯重演 =====


async def test_replay_messages_and_timeline_are_projected():
    import uuid

    from app.services.session_projection import (
        project_messages,
        project_state,
        project_timeline,
    )

    rt, _ = _make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "甲"})
    sid = uuid.UUID("0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910")
    allowed = ["choose_option", "rollback_to_event", "exit_game"]
    state = project_state(sid, rt.event_store, rt.export_state())

    msgs = project_messages(
        sid,
        rt.event_store,
        interaction=state.active_interaction,
        allowed_commands=allowed,
    )
    texts = [m["payload"].get("text") for m in msgs]
    assert "场景：相遇" in texts
    assert "两人在渡口相遇" in texts
    assert any(
        m["type"] == "character_speech" and m["payload"]["speaker"] == "乙"
        for m in msgs
    )
    assert msgs[-1]["type"] == "interaction"
    assert msgs[-1]["payload"]["allowed_commands"] == allowed

    timeline = project_timeline(
        sid,
        rt.event_store,
        stage="stage2_reenacting",
        allowed_commands=allowed,
        max_rollback_steps=100,
    )
    assert timeline.can_rollback
    assert any(e.kind.value == "narrative" and e.rollbackable for e in timeline.entries)


async def test_rollback_replays_target_node_on_new_branch():
    rt, _ = _make_runtime()
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "甲"})
    first_node = next(
        e for e in rt.event_store.active_events() if e.event_type == EVENT_REPLAY_NODE_ENTERED
    )
    await rt.submit(command_id="c2", kind="choose_option", payload={"option_id": "o1"})
    assert rt.state.scene_key == "scene:2"

    old_branch = rt.event_store.active_branch_id
    result = await rt.rollback(command_id="c3", target_event_id=first_node.event_id)

    assert rt.event_store.active_branch_id != old_branch
    assert result.state["scene_key"] == "scene:1"
    assert result.state["scene_title"] == "相遇"
    assert _option_ids(result) == ["o1", "o2"]
    # 新分支路径 = 阶段事件 + 回溯 + 目标节点整拍重演；旧分支的选择不在新路径上
    kinds = [e.event_type for e in rt.event_store.active_events()]
    assert EVENT_PLAYER_ACTION not in kinds
    assert _payloads(rt, EVENT_REPLAY_NODE_ENTERED)[-1]["node_id"] == "scene:1"
    assert _payloads(rt, EVENT_REPLAY_NARRATION)
