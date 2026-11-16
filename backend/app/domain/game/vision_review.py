"""图片视觉评审 agent（P2，2026-11）：候选生成图的「看图」质检。

与 `image_review.py`（检索候选的元数据审核）互补：
- `ImageReviewAgent`：审**检索候选**的标题/描述/许可（无视觉，候选本身没到眼前）；
- `VisionReviewAgent`（本模块）：审**生成产物**——图已到手，纯文本 LLM 判不了
  「性别画错没有」，必须视觉模型。低成本策略：一张图一次评审调用，
  结构化 JSON 输出；单图 rubric 内置，不落库（与 prompt_writer 同理，
  媒体路径 prompt 内联）。

分层：domain 只依赖 `LLMService` 端口；多模态消息是 OpenAI content 数组形状
（`{"type": "image_url", ...}`），`ChatLLMService._request` 原样透传给 SDK。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

from app.contracts.enums import UsagePurpose
from app.domain.game.media import AssetKind
from app.domain.generation.json_text import extract_json
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.game.vision_review")


class VisionReviewReason(StrEnum):
    """评审结论原因（区分「不合格」与「评审降级」）。"""

    ACCEPTED = "accepted"
    CHARACTER_MISMATCH = "character_mismatch"  # 外貌/性别/年龄与锚点不符
    COMPOSITION_MISMATCH = "composition_mismatch"  # 构图/画幅/人数与要求不符
    LOW_QUALITY = "low_quality"
    REVIEW_FAILED = "review_failed"  # 视觉模型失败/输出不可解析：降级，放行原图


@dataclass(frozen=True)
class VisionReviewVerdict:
    """一次视觉评审的结论。"""

    accepted: bool
    reason: VisionReviewReason
    score: float = 0.0
    feedback: str = ""

    @property
    def degraded(self) -> bool:
        """评审通道本身故障：调用方应放行原图（完整性优先于质量）。"""
        return self.reason is VisionReviewReason.REVIEW_FAILED


class _VisionVerdict(BaseModel):
    """视觉模型的结构化输出契约（内部，不落对外契约）。"""

    score: float = Field(default=0.0, ge=0.0, le=1.0)
    character_match: bool = False
    composition_ok: bool = False
    quality_ok: bool = False
    feedback: str = ""


#: 图片字节 → data URL（组合根注入；见 VisionReviewAgent docstring）。
EncodeFn = Callable[[bytes], str]


_CONTRACT = """\
{
  "score": 0.0 到 1.0 之间的数（综合分）,
  "character_match": true 或 false（人物是否匹配锚点）,
  "composition_ok": true 或 false（构图是否符合要求）,
  "quality_ok": true 或 false（画质是否合格：清晰、无文字伪影、无肢体畸变）,
  "feedback": "一句话：不合格时给出最关键的修改方向"
}"""


def build_vision_review_prompt(
    *,
    character_anchors: str,
    scene_description: str,
    kind: AssetKind,
) -> str:
    """构造视觉评审 prompt：锚点/情节/构图要求 + 输出契约。"""
    composites = {
        AssetKind.AVATAR: "单人半身肖像，四分之三侧身，姿态自然；非证件照式正面大头照",
        AssetKind.FULLBODY: "单人全身立绘，直立",
        AssetKind.SCENE_MONTAGE: "完整场面：人物在环境中做情节动作",
        AssetKind.BACKGROUND: "空镜环境，画面中不出现任何人物",
    }
    return "\n".join(
        [
            "你是课文插图质检员。看这张生成图，对照要求判定是否可用。",
            "",
            "【判定维度】",
            "- character_match：人物长相/性别/年龄段/服装是否与锚点一致；",
            "  尤其性别与年龄段——画错即为不合格。",
            "- composition_ok：是否符合该类别构图；人数是否相符。",
            "- quality_ok：清晰无伪影、肢体正常、无乱入文字。",
            "",
            "【输出契约（只输出此 JSON）】",
            _CONTRACT,
            "",
            f"【资产类别】{kind.value}",
            f"【构图要求】{composites.get(kind, composites[AssetKind.SCENE_MONTAGE])}",
            f"【人物锚点】{character_anchors or '（无人物或未提供）'}",
            f"【情节/环境】{scene_description}",
        ]
    )


class VisionReviewAgent:
    """生成图的视觉评审（便宜模型 + 多模态 + 结构化输出）。

    **不抛异常**：视觉模型失败或输出不可解析时返回 `REVIEW_FAILED` 的降级结论，
    调用方放行原图——评审失败不应让一张本来就生成的图白花。

    `_encode`：图片字节 → data URL 的可调用（组合根注入 `image_encode.data_url`；
    domain 不 import infrastructure 的运行期符号，与 SceneDesigner 的 transcode
    注入同一取舍）。
    """

    def __init__(self, llm: LLMService, *, encode: EncodeFn) -> None:
        self._llm = llm
        self._encode = encode

    async def review(
        self,
        image_bytes: bytes,
        *,
        character_anchors: str,
        scene_description: str,
        kind: AssetKind,
    ) -> VisionReviewVerdict:
        prompt = build_vision_review_prompt(
            character_anchors=character_anchors,
            scene_description=scene_description,
            kind=kind,
        )
        message = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": ""},  # 填充见下方 _attach
                },
                {"type": "text", "text": prompt},
            ],
        }
        try:
            # domain 不 import infra 的运行期符号：mime 探测/编码由组合根注入。
            message["content"][0]["image_url"]["url"] = self._encode(image_bytes)
            raw = await self._llm.chat(
                [message], session_id="", purpose=UsagePurpose.IMAGE_REVIEW
            )
            data = _VisionVerdict.model_validate_json(extract_json(raw))
        except Exception as exc:  # noqa: BLE001 - 评审降级不阻断
            logger.warning(
                "vision_review_failed reason=%s", str(exc).replace("\n", " ")[:200]
            )
            return VisionReviewVerdict(
                accepted=True, reason=VisionReviewReason.REVIEW_FAILED
            )
        ok = data.quality_ok and (
            data.character_match or kind in (AssetKind.BACKGROUND,)
        )
        if ok and data.composition_ok:
            reason = VisionReviewReason.ACCEPTED
        elif not data.character_match:
            reason = VisionReviewReason.CHARACTER_MISMATCH
        elif not data.composition_ok:
            reason = VisionReviewReason.COMPOSITION_MISMATCH
        else:
            reason = VisionReviewReason.LOW_QUALITY
        return VisionReviewVerdict(
            accepted=reason is VisionReviewReason.ACCEPTED,
            reason=reason,
            score=data.score,
            feedback=data.feedback,
        )


__all__ = [
    "VisionReviewAgent",
    "VisionReviewReason",
    "VisionReviewVerdict",
    "build_vision_review_prompt",
]
