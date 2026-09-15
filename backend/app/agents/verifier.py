"""验证 Agent：质量门禁（精简版）。

design_01 §3：验证不生产内容，只评估合规。MVP 阶段输出可被 mock 的确定性
verdict，聚焦"通过/条件通过/驳回 + 重试（≤2 次）+ 僵局检测"机制本身，
不评估真实剧情质量。
"""

from __future__ import annotations

import logging

from app.agents.llm_service import LLMService
from app.contracts.enums import UsagePurpose
from app.core.types import Proposal, Rejection, VerificationResult

logger = logging.getLogger("wenjing.agents.verifier")


class VerifierAgent:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def verify_proposal(self, proposal: Proposal, stage: str) -> VerificationResult:
        """验证单个角色提议。MVP 以 mock LLM 输出判定；默认 pass。"""
        try:
            raw = await self.llm.chat(
                [
                    {"role": "system", "content": "你是验证 Agent，评估剧情提议是否合规。"},
                    {"role": "user", "content": f"stage={stage}\nproposal={proposal.description}"},
                ],
                purpose=UsagePurpose.VERIFY,
            )
        except Exception:
            # LLM 失败降级（design_00 D4）：按条件通过，不阻塞主流程
            logger.warning("verify_degraded", extra={"proposal": proposal.proposal_id})
            return VerificationResult(verdict="conditional_pass", score=0.5)

        verdict, score = _parse_verdict(raw)
        rejections = []
        if verdict == "reject":
            rejections = [Rejection(reason="mock 驳回", suggestion="请调整行动方向")]
        logger.debug(
            "verify_proposal",
            extra={"proposal": proposal.proposal_id, "verdict": verdict, "score": score},
        )
        return VerificationResult(
            verdict=verdict,
            score=score,
            rejections=rejections,
        )


def _parse_verdict(raw: str) -> tuple[str, float]:
    """解析 mock 输出为 (verdict, score)。不严格，供机制测试。"""
    s = raw.strip().lower()
    if "reject" in s:
        return "reject", 0.2
    if "conditional" in s or "warning" in s:
        return "conditional_pass", 0.5
    return "pass", 0.9
