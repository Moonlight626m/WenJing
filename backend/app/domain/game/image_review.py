"""图片审核 agent：相关 / 画质 / 许可判定（ADR-0005 §6，issue #45）。

供 SceneDesigner（#47）在"检索 → 审核 → 回退生成"链路中决定候选是否采用：

- **许可**：确定性白名单（`evaluate_license`），不消耗 LLM——不兼容直接拒绝，
  免署名许可放行、需署名许可放行但标记 `attribution_required`（学生端须折叠署名）。
- **相关 / 画质**：便宜模型 + 结构化 JSON 输出，按 `UsagePurpose.IMAGE_REVIEW` 计量。
- **降级**：LLM 失败或输出不可解析时**拒绝**该候选（交由 SceneDesigner 回退文生图），
  绝不采用未经审核的开放版权素材。

当前 `LLMService` 为纯文本端口，审核依据候选的标题/描述/尺寸元数据（非视觉）。
分层：domain 只依赖 `LLMService` 端口；prompt 内联（与 verifier/screenwriter 同）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.contracts.enums import UsagePurpose
from app.domain.game.media import AssetKind, ImageCandidate
from app.domain.generation.json_text import extract_json
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.game.image_review")


class LicenseStatus(StrEnum):
    """候选许可的处置类别（ADR-0005 §6 署名合规）。"""

    ATTRIBUTION_FREE = "attribution_free"       # CC0 / Public Domain：免署名
    ATTRIBUTION_REQUIRED = "attribution_required"  # CC BY / BY-SA：需署名
    INCOMPATIBLE = "incompatible"               # NC/ND/未知/保留所有权利：拒绝


class ReviewReason(StrEnum):
    """审核结论原因（区分"不合格"与"审核降级"，供 SceneDesigner 决定是否付费回退生成）。"""

    ACCEPTED = "accepted"
    LICENSE_INCOMPATIBLE = "license_incompatible"
    IRRELEVANT = "irrelevant"
    LOW_QUALITY = "low_quality"
    REVIEW_FAILED = "review_failed"  # 降级：provider 失败 / 输出不可解析


_TOKEN_RE = re.compile(r"[A-Z0-9]+")
# 免署名许可标识（含常见拼写别名）。
_PUBLIC_DOMAIN_TOKENS = frozenset({"CC0", "PDM", "PDDC"})
# 不兼容标识：非商用（NC）/ 禁演绎（ND），含拼写别名。
_DISALLOWED_TOKENS = frozenset(
    {"NC", "NONCOMMERCIAL", "NONCOMMERCIALUSE", "ND", "NODERIVATIVES", "NODERIVATIVE"}
)
# 需署名标识：CC BY / BY-SA，含拼写别名。
_ATTRIBUTION_TOKENS = frozenset({"BY", "ATTRIBUTION"})


def evaluate_license(raw: str) -> LicenseStatus:
    """按许可字符串判定处置类别；未知/空/不兼容一律 INCOMPATIBLE（宁拒勿用）。

    识别基于许可标识中的 token（如 `CC BY-NC-SA 4.0` → BY + NC），
    不依赖大小写/连字符/空格拼写，并兼容 `Creative Commons Zero` 等拼写别名。
    """
    tokens = set(_TOKEN_RE.findall((raw or "").upper()))
    if not tokens:
        return LicenseStatus.INCOMPATIBLE
    if tokens & _DISALLOWED_TOKENS:
        return LicenseStatus.INCOMPATIBLE
    if tokens & _ATTRIBUTION_TOKENS:
        return LicenseStatus.ATTRIBUTION_REQUIRED
    if tokens & _PUBLIC_DOMAIN_TOKENS:
        return LicenseStatus.ATTRIBUTION_FREE
    if {"PUBLIC", "DOMAIN"} <= tokens:
        return LicenseStatus.ATTRIBUTION_FREE
    # `Creative Commons Zero` / `CC Zero`：ZERO 与 CC/Commons/Creative 同现即 CC0。
    if "ZERO" in tokens and tokens & {"CC", "COMMONS", "CREATIVE"}:
        return LicenseStatus.ATTRIBUTION_FREE
    return LicenseStatus.INCOMPATIBLE


@dataclass(frozen=True)
class ImageReviewResult:
    """审核结论：是否采用 + 各维度判定 + 署名要求 + 原因（含降级标记）。"""

    accepted: bool
    license_status: LicenseStatus
    reason: ReviewReason
    attribution_required: bool = False
    relevant: bool = False
    quality_ok: bool = False
    score: float = 0.0

    @property
    def degraded(self) -> bool:
        """审核降级（provider 失败/输出不可解析）：调用方可据此避免重复付费回退。"""
        return self.reason is ReviewReason.REVIEW_FAILED


class _LLMVerdict(BaseModel):
    """便宜模型的结构化输出契约（内部，不落对外契约）。"""

    relevant: bool
    quality_ok: bool
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


_REVIEW_CONTRACT = """\
{
  "relevant": true 或 false,
  "quality_ok": true 或 false,
  "score": 0.0 到 1.0 之间的数,
  "reason": "一句话说明判定依据"
}"""


def build_review_prompt(
    *,
    candidate: ImageCandidate,
    scene_description: str,
    kind: AssetKind,
) -> str:
    """构造审核 prompt：候选元数据 + 场景描述 + 输出契约。"""
    return "\n".join(
        [
            "你是剧本配图审核 agent。判断候选图片是否适合作为该场景的配图。",
            "",
            "【判定维度】",
            "- 相关：候选标题/描述与场景描述是否指向同一事物；背景图不应含主要人物。",
            "- 画质：分辨率是否足够（背景建议 ≥1280x720，头像 ≥512x512），过低判不合格。",
            "- 许可：由系统确定性判定，无需你判断。",
            "",
            "【输出契约（只输出此 JSON）】",
            _REVIEW_CONTRACT,
            "",
            f"【资产类别】{kind.value}",
            f"【场景描述】{scene_description}",
            "【候选】",
            f"- 标题：{candidate.title or '(无)'}",
            f"- 描述：{candidate.description or '(无)'}",
            f"- 尺寸：{candidate.width}x{candidate.height}",
            f"- 来源：{candidate.source_url}",
        ]
    )


@runtime_checkable
class ImageReviewerPort(Protocol):
    """审核端口（#47 SceneDesigner 依赖的形状；`ImageReviewAgent` 是它的实现）。

    **不抛异常**：LLM 失败或输出不可解析时返回 `reason=REVIEW_FAILED` 的拒绝结论，
    由调用方决定是否付费回退生成（#45 的降级语义）。
    """

    async def review(
        self,
        candidate: ImageCandidate,
        *,
        scene_description: str,
        kind: AssetKind,
    ) -> ImageReviewResult: ...


class ImageReviewAgent:
    """图片审核 agent（便宜模型 + 结构化输出）。"""

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def review(
        self,
        candidate: ImageCandidate,
        *,
        scene_description: str,
        kind: AssetKind,
    ) -> ImageReviewResult:
        """审核单个候选；不抛异常（LLM 失败按拒绝降级）。"""
        status = evaluate_license(candidate.credit.license)
        if status is LicenseStatus.INCOMPATIBLE:
            logger.info(
                "image_review_license_rejected license=%r source=%s",
                candidate.credit.license,
                candidate.source_url,
            )
            return ImageReviewResult(
                accepted=False,
                license_status=status,
                reason=ReviewReason.LICENSE_INCOMPATIBLE,
            )

        prompt = build_review_prompt(
            candidate=candidate, scene_description=scene_description, kind=kind
        )
        try:
            raw = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                purpose=UsagePurpose.IMAGE_REVIEW,
            )
            verdict = _LLMVerdict.model_validate_json(extract_json(raw))
        except Exception as exc:  # noqa: BLE001 - 审核失败不阻断，降级为拒绝
            logger.warning("image_review_degraded reason=%s", exc)
            return ImageReviewResult(
                accepted=False,
                license_status=status,
                reason=ReviewReason.REVIEW_FAILED,
            )

        logger.debug(
            "image_review_verdict relevant=%s quality_ok=%s score=%.2f reason=%s",
            verdict.relevant,
            verdict.quality_ok,
            verdict.score,
            verdict.reason,
        )
        accepted = verdict.relevant and verdict.quality_ok
        if accepted:
            reason = ReviewReason.ACCEPTED
        elif not verdict.relevant:
            reason = ReviewReason.IRRELEVANT
        else:
            reason = ReviewReason.LOW_QUALITY
        return ImageReviewResult(
            accepted=accepted,
            license_status=status,
            reason=reason,
            # 仅在采用时标记署名要求（未采用无需展示署名）。
            attribution_required=accepted and status is LicenseStatus.ATTRIBUTION_REQUIRED,
            relevant=verdict.relevant,
            quality_ok=verdict.quality_ok,
            score=verdict.score,
        )


__all__ = [
    "ImageReviewAgent",
    "ImageReviewerPort",
    "ImageReviewResult",
    "LicenseStatus",
    "ReviewReason",
    "build_review_prompt",
    "evaluate_license",
]
