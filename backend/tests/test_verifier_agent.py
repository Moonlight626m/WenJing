"""验证 Agent：结构化判定与降级口径。

提议验证走 JSON（兼容旧的纯文本输出）；LLM 失败按条件通过，不阻塞主流程。
"""

from __future__ import annotations

from app.domain.agents.verifier import VerifierAgent, _parse_verdict
from app.domain.game.types import Proposal


class _FixedLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None):
        self.calls.append(messages)
        return self._text


class _BoomLLM:
    async def chat(self, messages, *, session_id: str = "", purpose=None):
        raise RuntimeError("provider down")


def test_parse_verdict_structured():
    raw = (
        '{"verdict":"reject","score":0.1,'
        '"reason":"船已经离岸","suggestion":"改为追问岸上的人"}'
    )
    assert _parse_verdict(raw) == ("reject", 0.1, "船已经离岸", "改为追问岸上的人")


def test_parse_verdict_clamps_score_and_invalid_verdict_is_conditional():
    assert _parse_verdict('{"verdict":"pass","score":9}')[0:2] == ("pass", 1.0)
    verdict, score, _reason, _suggestion = _parse_verdict('{"verdict":"teleport","score":0.2}')
    assert (verdict, score) == ("conditional_pass", 0.5)


def test_parse_verdict_keeps_legacy_text_output():
    assert _parse_verdict("reject")[0] == "reject"
    assert _parse_verdict("conditional")[0] == "conditional_pass"
    assert _parse_verdict("pass")[0] == "pass"


async def test_verify_proposal_structured_reject_builds_rejection():
    llm = _FixedLLM(
        '{"verdict":"reject","score":0.1,"reason":"违背课文","suggestion":"换个方向"}'
    )
    result = await VerifierAgent(llm).verify_proposal(
        Proposal(proposal_id=1, proposed_by="杜甫", description="把船拉回岸边"), "stage3"
    )
    assert result.verdict == "reject"
    assert result.rejections[0].reason == "违背课文"
    assert result.rejections[0].suggestion == "换个方向"
    prompt = "\n".join(str(m.get("content", "")) for m in llm.calls[0])
    assert "杜甫" in prompt and "把船拉回岸边" in prompt


async def test_verify_proposal_degrades_to_conditional_without_llm():
    result = await VerifierAgent(_BoomLLM()).verify_proposal(
        Proposal(proposal_id=1, proposed_by="杜甫", description="提议"), "stage2"
    )
    assert result.verdict == "conditional_pass"
    assert result.score == 0.5
