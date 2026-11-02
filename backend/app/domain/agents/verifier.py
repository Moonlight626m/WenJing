"""验证 Agent：质量门禁（精简版）。

design_01 §3：验证不生产内容，只评估合规。MVP 阶段输出可被 mock 的确定性
verdict，聚焦"通过/条件通过/驳回 + 重试（≤2 次）+ 僵局检测"机制本身，
不评估真实剧情质量。
"""

from __future__ import annotations

import logging

from app.contracts.enums import UsagePurpose
from app.domain.game.goals import GoalState, parse_achieved
from app.domain.game.types import Proposal, Rejection, VerificationResult
from app.domain.llm import LLMService

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


    async def judge_stage3_goals(
        self,
        goals: list[GoalState],
        *,
        player_role: str | None,
        action: str,
        reactions: list[tuple[str, str]],
    ) -> tuple[list[int], str]:
        """判定这一轮之后哪些续写目标已经达成，返回 (目标编号, 一句理由)。

        只看还没达成的目标。LLM 失败或输出无法解析时视为本轮没有达成——宁可少判，
        不让续写被一次异常输出提前收掉。
        """
        pending = [g for g in goals if not g.achieved]
        if not pending:
            return [], ""
        listing = "\n".join(f"{g.goal_id}. {g.description}" for g in pending)
        said = "\n".join(f"{name}：{text}" for name, text in reactions) or "（无人回应）"
        try:
            raw = await self.llm.chat(
                [
                    {"role": "system", "content": "你是验证 Agent，判断续写目标是否已经达成。"},
                    {
                        "role": "user",
                        "content": (
                            f"未达成的续写目标：\n{listing}\n\n"
                            f"这一轮学生（扮演{player_role or '某角色'}）的行动：{action}\n"
                            f"各角色的回应：\n{said}\n\n"
                            "只依据这一轮实际发生的内容，判断哪些目标已经达成；没有把握就不算。"
                            '只输出 JSON：{"achieved": [目标编号], "reason": "一句话说明"}'
                        ),
                    },
                ],
                purpose=UsagePurpose.VERIFY,
            )
        except Exception:
            logger.warning("goal_judge_degraded", extra={"pending": len(pending)})
            return [], ""
        return parse_achieved(raw, {g.goal_id for g in pending})


def _parse_verdict(raw: str) -> tuple[str, float]:
    """解析 mock 输出为 (verdict, score)。不严格，供机制测试。"""
    s = raw.strip().lower()
    if "reject" in s:
        return "reject", 0.2
    if "conditional" in s or "warning" in s:
        return "conditional_pass", 0.5
    return "pass", 0.9
