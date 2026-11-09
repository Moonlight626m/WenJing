"""导演 Agent（M6）：选项解析的容错、去重与上限。

导演是工作人员、不挂工具；解析失败必须返回空列表，让运行时回退到
「已验证提议 + 默认项」，故障不能让玩家卡住。
"""

from __future__ import annotations

from app.domain.agents.director import (
    MAX_OPTIONS,
    DirectorAgent,
    parse_option_items,
)


def _labels(raw: str) -> list[str]:
    return [item.label for item in parse_option_items(raw)]


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


def test_parse_options_accepts_string_and_dict_items():
    raw = (
        '{"options": ['
        '"走向船夫打听水路", '
        '{"label": "回到客栈等雨停"}, '
        '{"text": "被忽略的字段"}, '
        '"走向船夫打听水路"'
        "]}"
    )
    assert _labels(raw) == ["走向船夫打听水路", "回到客栈等雨停"]


def test_parse_option_items_keeps_valid_dimension_and_ignores_invalid():
    raw = (
        '{"options": ['
        '{"label": "沿河查看脚印", "dimension": "goal"}, '
        '{"label": "问船夫昨夜的事", "dimension": "Relationship"}, '
        '{"label": "去渡口另一边", "dimension": "teleport"}'
        "]}"
    )
    items = parse_option_items(raw)
    assert [o.label for o in items] == ["沿河查看脚印", "问船夫昨夜的事", "去渡口另一边"]
    assert [o.dimension for o in items] == ["goal", "relationship", None]


def test_parse_options_tolerates_code_fence():
    raw = '```json\n{"options": ["看看四周", "问问船夫"]}\n```'
    assert _labels(raw) == ["看看四周", "问问船夫"]


def test_parse_options_rejects_fewer_than_min():
    # 一条选项不如回退到「已验证提议 + 默认项」（数量不足 = 解析失败）
    assert _labels('{"options": ["看看四周"]}') == []


def test_parse_options_caps_at_max():
    raw = '{"options": ["一", "二", "三", "四", "五"]}'
    assert len(_labels(raw)) == MAX_OPTIONS
    assert _labels(raw) == ["一", "二", "三", "四"]


def test_parse_options_fail_closed_shapes():
    assert _labels("我去质询对方") == []
    assert _labels('{"options": "not-a-list"}') == []
    assert _labels('{"options": [1, null, ""]}') == []


async def test_design_options_never_raises_on_llm_failure():
    agent = DirectorAgent(_BoomLLM())
    options = await agent.design_options(
        location_title="渡口",
        visual_summary="雨后的渡口",
        player_role="甲",
        present=[("乙", "船夫")],
        plot_log=["船靠岸"],
        direction={"conflict": "船要走了"},
        goals=[("劝船夫再等一会儿", False)],
        teaching_focus=["同舟共济"],
    )
    assert options == []


async def test_design_options_returns_parsed_list():
    agent = DirectorAgent(
        _FixedLLM(
            '{"options": ['
            '{"label": "与船夫攀谈", "dimension": "relationship"}, '
            '{"label": "检查船绳", "dimension": "environment"}'
            "]}"
        )
    )
    options = await agent.design_options(
        location_title="渡口",
        visual_summary="雨后的渡口",
        player_role=None,
        present=[],
        plot_log=[],
        direction={},
        goals=[],
        teaching_focus=[],
    )
    assert [o.label for o in options] == ["与船夫攀谈", "检查船绳"]
    assert [o.dimension for o in options] == ["relationship", "environment"]


async def test_design_options_passes_new_context_to_prompt():
    llm = _FixedLLM('{"options": ["问船夫昨夜的事", "沿河查看脚印"]}')
    agent = DirectorAgent(llm)
    await agent.design_options(
        location_title="渡口",
        visual_summary="雨后的渡口",
        player_role="甲",
        present=[("乙", "船夫")],
        plot_log=["船靠岸"],
        direction={"conflict": "船要走了"},
        goals=[("劝船夫再等一会儿", False)],
        teaching_focus=["同舟共济"],
        recent_speeches=[("船夫", "再不走就涨潮了")],
        last_options=["看看四周"],
        public_facts=["昨夜上游下了暴雨"],
    )
    prompt = "\n".join(str(m.get("content", "")) for m in llm.calls[0])
    assert "再不走就涨潮了" in prompt
    assert "看看四周" in prompt
    assert "昨夜上游下了暴雨" in prompt
