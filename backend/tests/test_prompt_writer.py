"""画师层（LLMPromptWriter）单元测试：dict 桥接 / 消息纪律 / 画风笔调。

回归重点：workflow 与 asset_jobs 只能传 JSON 安全 dict，writer 曾直接对 dict
取 `.era` 抛 AttributeError，被上层吞掉后画师层**每次都静默回退**。
"""

from __future__ import annotations

import pytest

from app.domain.game.media import AssetKind
from app.domain.game.prompt_writer import (
    SCENE_PROMPT_VERSION,
    LLMPromptWriter,
    ScenePromptContext,
    render_appearance,
)

_CTX = {
    "title": "月台上的背影",
    "beats": ["父亲攀爬月台买橘子", "我望着他的背影流泪"],
    "visual_notes": {"era": "民国初年", "location": "浦口车站月台", "weather": "冬日下午"},
    "participants": [
        {
            "name": "父亲",
            "face": "紫色圆脸",
            "hair": "短平头",
            "clothing": "深青布棉袍",
            "accessories": "",
            "build": "微胖",
        }
    ],
    "kind": "scene_montage",
}


class FakeLLM:
    def __init__(
        self, reply: str = '{"description":"父亲在月台上攀爬的背影"}', error: bool = False
    ):
        self.reply = reply
        self._error = error
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None, **kwargs):
        self.calls.append(messages)
        if self._error:
            raise RuntimeError("llm down")
        return self.reply


def test_from_dict_maps_structured_fields():
    ctx = ScenePromptContext.from_dict(_CTX)

    assert ctx.title == "月台上的背影"
    assert ctx.beats == _CTX["beats"]
    assert ctx.visual_notes["era"] == "民国初年"
    assert ctx.kind is AssetKind.SCENE_MONTAGE
    father = ctx.participants[0]
    assert father.name == "父亲"
    assert father.face == "紫色圆脸"
    assert father.clothing == "深青布棉袍"


def test_from_dict_defaults_and_tolerates_bad_kind():
    ctx = ScenePromptContext.from_dict({"kind": "not-a-kind", "participants": []})
    assert ctx.kind is AssetKind.SCENE_MONTAGE
    assert ctx.participants == []

    avatar = ScenePromptContext.from_dict({"kind": "avatar"})
    assert avatar.kind is AssetKind.AVATAR


def test_appearance_fragment_fills_unstated_fields_neutrally():
    fragment = render_appearance({"name": "父亲"}, "父亲").fragment()
    assert "原文未交代" not in fragment, "占位词绝不能原样送 provider"
    assert "父亲" in fragment
    assert "面容" in fragment and "发型" in fragment and "穿着" in fragment


async def test_write_accepts_dict_context():
    llm = FakeLLM()
    writer = LLMPromptWriter(llm=llm)

    text = await writer.write(_CTX, max_chars=500)

    assert text == "父亲在月台上攀爬的背影"
    message = llm.calls[0][0]["content"]
    assert SCENE_PROMPT_VERSION in message
    assert "【情节（按序发生）】" in message
    assert "紫色圆脸" in message, "外貌锚点必须逐字进入转写输入"
    assert "课本插画" in message and "水墨" in message, "笔调与默认画风一致"
    assert '{"description"' in message


async def test_write_rejects_empty_output():
    """空产物的契约是 ValueError（pydantic ValidationError 即其子类）。"""
    writer = LLMPromptWriter(llm=FakeLLM(reply='{"description":""}'))
    with pytest.raises(ValueError):
        await writer.write(_CTX, max_chars=500)
