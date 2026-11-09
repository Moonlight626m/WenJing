"""验证 Agent：质量门禁。

两个职责：
- `verify_proposal`：评估角色提议是否合规、可执行，输出结构化判定；
- `judge_stage3_goals`：每轮之后判断哪些续写目标已经达成。

验证不生产内容，只评估合规；LLM 失败或输出无法解析时按「不阻塞主流程」降级：
提议验证退回条件通过，目标判定视为本轮未达成。

Prompt 组装在 `domain/agents/prompting.py`（`build_verify_prompt` /
`build_goal_judge_prompt`）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.agents.prompting import build_goal_judge_prompt, build_verify_prompt
from app.domain.game.goals import GoalState, extract_json_object, parse_achieved
from app.domain.game.types import Proposal, Rejection, VerificationResult
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.agents.verifier")

_VERDICTS = frozenset({"pass", "conditional_pass", "reject"})


class VerifierAgent:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def verify_proposal(self, proposal: Proposal, stage: str) -> VerificationResult:
        """验证单个角色提议；LLM 失败时按条件通过，不阻塞主流程。"""
        bundle = build_verify_prompt(proposal, stage)
        try:
            raw = await self.llm.chat(bundle.messages(), purpose=UsagePurpose.VERIFY)
        except Exception:
            # LLM 失败降级（design_00 D4）：按条件通过，不阻塞主流程
            logger.warning("verify_degraded", extra={"proposal": proposal.proposal_id})
            return VerificationResult(verdict="conditional_pass", score=0.5)

        verdict, score, reason, suggestion = _parse_verdict(raw)
        rejections: list[Rejection] = []
        if verdict == "reject":
            rejections = [
                Rejection(
                    reason=reason or "提议不符合当前剧情。",
                    suggestion=suggestion or "请调整行动方向。",
                )
            ]
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
        bundle = build_goal_judge_prompt(
            pending,
            player_role=player_role,
            action=action,
            reactions=reactions,
        )
        try:
            raw = await self.llm.chat(bundle.messages(), purpose=UsagePurpose.VERIFY)
        except Exception:
            logger.warning("goal_judge_degraded", extra={"pending": len(pending)})
            return [], ""
        return parse_achieved(raw, {g.goal_id for g in pending})


def _parse_verdict(raw: str) -> tuple[str, float, str, str]:
    """解析验证输出为 (verdict, score, reason, suggestion)。

    兼容旧的纯文本输出（`reject` / `conditional` / 其他视为通过）：真实 LLM 应走
    JSON；确定性 LLM 与遗留测试仍可能返回文本，不能因此改变既有机制。
    """
    data = extract_json_object(raw)
    if data is not None:
        verdict = str(data.get("verdict", "")).strip().lower()
        reason = str(data.get("reason") or "").strip()[:120]
        suggestion = str(data.get("suggestion") or "").strip()[:120]
        if verdict not in _VERDICTS:
            # 结构不对也不阻塞推进：按条件通过，保留模型给的理由供排障
            return "conditional_pass", 0.5, reason, suggestion
        return verdict, _score(data.get("score"), verdict), reason, suggestion

    text = raw.strip().lower()
    if "reject" in text:
        return "reject", 0.2, "", "请调整行动方向。"
    if "conditional" in text or "warning" in text:
        return "conditional_pass", 0.5, "", ""
    return "pass", 0.9, "", ""


def _score(value: Any, verdict: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return {"pass": 0.9, "conditional_pass": 0.5, "reject": 0.2}[verdict]
    return min(1.0, max(0.0, score))
