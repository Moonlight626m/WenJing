"""VisionReviewAgent（P2 视觉评审）测试：全 fake LLM，不触网。"""

from __future__ import annotations

import json

from app.domain.game.media import AssetKind
from app.domain.game.vision_review import (
    VisionReviewAgent,
    VisionReviewReason,
    build_vision_review_prompt,
)

_PNG = b"\x89PNG\r\n\x1a\nfake"


class _ScriptedLLM:
    """按脚本返回文本的 LLM 假件；记录收到的消息形状。"""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.messages: list[list[dict]] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None) -> str:
        self.messages.append(messages)
        return self._outputs.pop(0)


def _encode(data: bytes) -> str:
    return f"data:image/png;base64,{data.hex()}"


async def test_review_sends_image_and_parses_verdict():
    llm = _ScriptedLLM(
        [
            json.dumps(
                {
                    "score": 0.9,
                    "character_match": True,
                    "composition_ok": True,
                    "quality_ok": True,
                    "feedback": "ok",
                }
            )
        ]
    )
    agent = VisionReviewAgent(llm, encode=_encode)

    verdict = await agent.review(
        _PNG,
        character_anchors="父亲（gender=男，age=四十上下）",
        scene_description="站台回望",
        kind=AssetKind.SCENE_MONTAGE,
    )

    assert verdict.accepted
    assert verdict.reason is VisionReviewReason.ACCEPTED
    assert verdict.score == 0.9
    # 消息是 OpenAI 多模态形状：图片 data URL + 文本
    content = llm.messages[0][0]["content"]
    assert content[0]["type"] == "image_url"
    assert _encode(_PNG) in content[0]["image_url"]["url"]
    assert "父亲" in content[1]["text"]


async def test_review_character_mismatch_rejected():
    llm = _ScriptedLLM(
        [
            json.dumps(
                {
                    "score": 0.3,
                    "character_match": False,
                    "composition_ok": True,
                    "quality_ok": True,
                    "feedback": "年龄画成了青年",
                }
            )
        ]
    )
    agent = VisionReviewAgent(llm, encode=_encode)

    verdict = await agent.review(
        _PNG,
        character_anchors="父亲（gender=男）",
        scene_description="站台",
        kind=AssetKind.AVATAR,
    )

    assert not verdict.accepted
    assert verdict.reason is VisionReviewReason.CHARACTER_MISMATCH
    assert "青年" in verdict.feedback


async def test_review_llm_failure_degrades_to_accept():
    """评审降级：放行原图（accepted=True + degraded=True），不阻断。"""
    llm = _ScriptedLLM(["这不是 JSON"])
    agent = VisionReviewAgent(llm, encode=_encode)

    verdict = await agent.review(
        _PNG, character_anchors="", scene_description="x",
        kind=AssetKind.BACKGROUND,
    )

    assert verdict.degraded
    assert verdict.accepted


async def test_review_prompt_contains_anchors_and_composition():
    prompt = build_vision_review_prompt(
        character_anchors="我（gender=男，age=二十岁）",
        scene_description="车站",
        kind=AssetKind.SCENE_MONTAGE,
    )
    assert "我" in prompt
    assert "性别" in prompt
    assert "完整场面" in prompt
