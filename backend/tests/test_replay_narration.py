"""Stage2 播放的 beat 叙述：`goal` 只作 agent 上下文，不得漏进旁白。

v3 剧本书写提示词把「事件骨架 + 戏剧目标」写进同一个 `beat.description`，
播放器原样把它当旁白念给玩家（现象：消息流里满是「目标：…」）。v4 起目标在
独立 `Beat.goal`；存量剧本包在投影处剥掉那条作者注记。
"""

from __future__ import annotations

from app.contracts.script import (
    Beat,
    CharacterProfile,
    Ending,
    Scene,
    SceneOption,
    ScriptPackage,
)
from app.domain.game import event as evt
from app.domain.game.replay import ReplayDirector, build_replay_graph


def _package(beats: list[Beat]) -> ScriptPackage:
    return ScriptPackage(
        title="背影",
        characters=[
            CharacterProfile(name="父亲", public_background="中年父亲"),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="月台",
                participants=["父亲"],
                beats=beats,
                options=[
                    SceneOption(
                        option_id="o1",
                        label="目送父亲",
                        kind="canonical",
                        ending_id="e1",
                    )
                ],
            )
        ],
        playable_roles=["父亲"],
        stage2_ending_beat_id=1,
        endings=[Ending(ending_id="e1", title="别后", kind="canonical")],
    )


def _narration_texts(beats: list[Beat]) -> list[str]:
    graph = build_replay_graph(_package(beats))
    assert graph is not None
    _, cues = ReplayDirector(graph).start(None)
    return [
        str(cue.payload["text"])
        for cue in cues
        if cue.event_type == evt.EVENT_REPLAY_NARRATION
    ]


def test_legacy_goal_note_is_stripped_from_narration():
    """存量包（目标写进 description）播放时只剩场面叙述。"""
    texts = _narration_texts(
        [
            Beat(
                beat_id=1,
                description="父亲把橘子堆在皮大衣上。目标：让儿子看见父亲的笨拙。",
            ),
            Beat(
                beat_id=2,
                description="他扑扑衣上的泥土，心里很轻松似的。目标：父亲掩饰离别的沉重。",
            ),
        ]
    )
    assert texts == [
        "父亲把橘子堆在皮大衣上。",
        "他扑扑衣上的泥土，心里很轻松似的。",
    ]


def test_description_that_is_only_a_goal_note_is_not_narrated():
    """整条描述都是作者注记时不产出空旁白。"""
    texts = _narration_texts(
        [
            Beat(beat_id=1, description="（目标：让玩家感到沉重。）"),
            Beat(beat_id=2, description="月台上只剩父子两人。"),
        ]
    )
    assert texts == ["月台上只剩父子两人。"]


def test_goal_note_after_closing_quote_is_stripped():
    """v3 包常在人物台词后接注记（`。」目标：…`），收尾引号要留在叙述里。"""
    texts = _narration_texts(
        [
            Beat(
                beat_id=1,
                description="他说：「进去吧，里边没人。」目标：父亲以叮嘱收束关心。",
            )
        ]
    )
    assert texts == ["他说：「进去吧，里边没人。」"]


def test_mid_sentence_goal_word_is_kept():
    """句中的「目标：」不是作者注记，不能误删。"""
    texts = _narration_texts(
        [Beat(beat_id=1, description="他反复念叨目标：养活一家人。")]
    )
    assert texts == ["他反复念叨目标：养活一家人。"]


def test_goal_field_never_reaches_player_narration():
    """v4 包：description 是旁白，goal 只进 agent 上下文。"""
    texts = _narration_texts(
        [
            Beat(
                beat_id=1,
                description="父亲转身走向车门，背影混进来往的人群。",
                goal="父亲不愿儿子看到自己攀爬月台的吃力。",
            )
        ]
    )
    assert texts == ["父亲转身走向车门，背影混进来往的人群。"]
    assert not any("目标" in text for text in texts)
