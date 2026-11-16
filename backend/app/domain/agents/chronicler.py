"""编年史作者（staff）：每轮把已发生的事写成一段增量叙事。

只读、不出场、不修改世界。失败/空输出回退到运行时给的确定性摘要，绝不阻塞
玩家推进。Prompt 组装在 `domain/agents/prompting.py::build_chronicler_prompt`。
"""

from __future__ import annotations

import logging

from app.contracts.enums import UsagePurpose
from app.domain.agents.prompting import build_chronicler_prompt
from app.domain.llm import LLMService
from app.infrastructure.errx import exc_reason

logger = logging.getLogger("wenjing.agents.chronicler")


class ChroniclerAgent:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def write(
        self,
        *,
        chronicle_tail: str,
        events_text: str,
        fallback: str,
    ) -> str:
        bundle = build_chronicler_prompt(
            chronicle_tail=chronicle_tail, events_text=events_text
        )
        try:
            raw = await self.llm.chat(bundle.messages(), purpose=UsagePurpose.AGENT)
        except Exception as exc:  # noqa: BLE001 - 编年史失败不能阻塞游玩
            logger.warning(
                "chronicler_degraded", extra={"reason": exc_reason(exc)}
            )
            return fallback
        text = (raw or "").strip()
        if not text:
            logger.info("chronicler_empty_fallback")
            return fallback
        return text
