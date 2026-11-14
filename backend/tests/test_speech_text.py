"""角色发言的舞台提示拆分：`（动作）台词` → 台词 + 动作。"""

from app.domain.game.speech_text import split_stage_direction


def test_leading_fullwidth_direction_is_split():
    assert split_stage_direction("（点头）好，这就开船。") == ("好，这就开船。", "点头")


def test_leading_halfwidth_direction_is_split():
    assert split_stage_direction("(sighs) I see.") == ("I see.", "sighs")


def test_trailing_direction_is_split():
    assert split_stage_direction("我明白了。（把橘子放下）") == ("我明白了。", "把橘子放下")


def test_multiple_directions_are_joined():
    assert split_stage_direction("（叹气）（摇头）不行。") == ("不行。", "叹气；摇头")


def test_mid_sentence_parentheses_are_kept():
    text = "这（大概）不是他的本意。"
    assert split_stage_direction(text) == (text, "")


def test_whole_action_kept_as_text():
    """整句都是动作时原样保留，免得字幕只剩动作、角色像没说话。"""
    raw = "（沉默良久）"
    assert split_stage_direction(raw) == (raw, "")


def test_plain_speech_untouched():
    assert split_stage_direction("船要开了。") == ("船要开了。", "")
