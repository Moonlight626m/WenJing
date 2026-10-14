"""per-character 世界视图（机制层知识边界）的筛选语义测试。"""

from __future__ import annotations

import pytest

from app.domain.game.game_runtime import GameRuntime
from app.domain.game.types import Beat, CharacterSetting, Scene, Script


@pytest.fixture
def two_scene_script() -> Script:
    """两场景：玉碎.mkv第 1 幕是我+李白，第 2 幕只杜甫+高适。"""
    return Script(
        title="视图测试",
        characters=[
            CharacterSetting(name="李白", public_background="诗人", is_player_playable=True),
            CharacterSetting(name="杜甫", public_background="诗人"),
            CharacterSetting(name="高适", public_background="边塞诗人"),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="相遇",
                participants=["李白", "杜甫", "高适"],
                beats=[Beat(beat_id=1, description="相遇"), Beat(beat_id=2, description="作别")],
            ),
            Scene(
                scene_id=2,
                title="边塞",
                participants=["杜甫", "高适"],
                beats=[Beat(beat_id=3, description="出征")],
            ),
        ],
        stage2_ending_beat_id=3,
    )


def make_rt(script: Script) -> GameRuntime:
    from tests.test_agent_tools import ToolCallingLLM

    return GameRuntime(session_id="rt-view", script=script, llm=ToolCallingLLM())


def _advance_to(rt: GameRuntime, beats: int) -> None:
    """直接推进游标模拟播过若干拍（绕过玩家命令，纯视图测试）。"""
    rt.state.beat_cursor = beats
    rt.state.scene_key = f"scene:{1 if beats <= 2 else 2}"


def test_bind_isolates_viewer_views(two_scene_script):
    """bind(name) 各给一份；互不影响，且共享同一 runtime。"""
    rt = make_rt(two_scene_script)
    vf = rt.world_view.bind("杜甫")
    vs = rt.world_view.bind("高适")
    assert vf is not vs
    assert vf._runtime is rt


def test_outline_excludes_scenes_viewer_not_in(two_scene_script):
    """杜甫参与两幕；李白只见第 1 幕。"""
    rt = make_rt(two_scene_script)
    du_titles = [s["title"] for s in rt.world_view.bind("杜甫").outline()]
    li_titles = [s["title"] for s in rt.world_view.bind("李白").outline()]
    assert du_titles == ["相遇", "边塞"]
    assert li_titles == ["相遇"]


def test_plot_log_excludes_foreign_scene(two_scene_script):
    """游标推进到第 3 拍（边塞场景）后：只想看 自己参与的 beats。"""
    rt = make_rt(two_scene_script)
    _advance_to(rt, 3)
    li_log = rt.world_view.bind("李白").plot_log()
    du_log = rt.world_view.bind("杜甫").plot_log()
    # 李白只参与了第 1 幕的两拍
    assert len(li_log) == 2
    assert "边塞" not in "".join(li_log)
    # 杜甫两幕都参与：3 条 beats
    assert len(du_log) == 3


def test_speech_log_only_contains_in_scene_heard(two_scene_script):
    """发言台账只在「我参与该场景」时可见：李白听不见边塞场景的发言。"""
    rt = make_rt(two_scene_script)
    _advance_to(rt, 2)
    rt.state.speech_log = [
        ("杜甫", "scene:1", "想一同远游吗"),
        ("高适", "scene:2", "出发边塞"),
    ]
    li_view = rt.world_view.bind("李白")
    du_view = rt.world_view.bind("杜甫")
    li_log = li_view.plot_log()
    du_log = du_view.plot_log()
    assert any("想一同远游吗" in x for x in li_log)
    assert not any("出发边塞" in x for x in li_log)
    assert any("出发边塞" in x for x in du_log)


def test_speech_log_replay_rebuilt_from_events(two_scene_script):
    """重放路径：character_speech 事件重建 speech_log（快照缺口兜底）。"""
    rt = make_rt(two_scene_script)
    # 无快照重放会重置 _RState——scene_key 由重放的 plot_advancement 重建，
    # 故事件序列里要带一条真实重放语义的事件
    rt.replay_from(
        None,
        [
            {
                "event_type": "plot_advancement",
                "payload": {"summary": "s", "scene_key": "scene:1", "scene_title": "相遇"},
            },
            {"event_type": "character_speech", "payload": {"speaker": "杜甫", "text": "同游去"}},
        ],
    )
    assert rt.state.speech_log == [("杜甫", "scene:1", "同游去")]


def test_state_roundtrip_carries_speech_log(two_scene_script):
    """export_state / restore 不丢发言台账（快照对账用）。"""
    rt = make_rt(two_scene_script)
    rt.state.speech_log = [("杜甫", "scene:1", "同游去"), ("李白", "scene:1", "好")]
    dump = rt.export_state()
    rt2 = make_rt(two_scene_script)
    rt2.restore(dump)
    assert rt2.state.speech_log == rt.state.speech_log
