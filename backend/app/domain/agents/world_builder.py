"""世界构建 Agent（工作人员）：解析玩家干涉（design §B5，M6）。

玩家用自然语言说「建一个雨夜客栈 / 让一个乞丐加入 / 叫船夫过来」，世界构建把它
解析成结构化意图；**校验与应用在运行时**（预算、canon、事件化），这里只做解析。
不挂工具、不出场；解析失败或无法归类一律返回 `reject`（fail-closed），
运行时据此写 `intervention_rejected` 并提示玩家。

Prompt 组装在 `domain/agents/prompting.py`（`build_world_builder_prompt`）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.agents.parsing import extract_json_object
from app.domain.agents.prompting import build_world_builder_prompt
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.agents.world_builder")

KIND_CREATE_SCENE = "create_scene"
KIND_ADD_CHARACTER = "add_character"
KIND_PULL_IN_CHARACTER = "pull_in_character"
KIND_REJECT = "reject"

_KINDS = frozenset(
    {KIND_CREATE_SCENE, KIND_ADD_CHARACTER, KIND_PULL_IN_CHARACTER, KIND_REJECT}
)


@dataclass(frozen=True)
class InterventionIntent:
    """一条干涉的结构化意图（事件 payload 由此构建）。"""

    kind: str
    # create_scene
    title: str = ""
    participants: tuple[str, ...] = ()
    visual_summary: str = ""
    parent_location_key: str | None = None
    # add_character / pull_in_character
    name: str = ""
    brief: str = ""
    personality: str = ""
    location_key: str | None = None
    # reject
    reason: str = ""

    @property
    def rejected(self) -> bool:
        return self.kind == KIND_REJECT


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _participants(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        name = _text(item, 20)
        if name and name not in names:
            names.append(name)
    return tuple(names)


class WorldBuilderAgent:
    """干涉解析器：自然语言 → `InterventionIntent`（四类之一，其余拒绝）。"""

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def parse_intervention(
        self, text: str, *, context: dict[str, Any]
    ) -> InterventionIntent:
        bundle = build_world_builder_prompt(text, context)
        try:
            raw = await self.llm.chat(bundle.messages(), purpose=UsagePurpose.AGENT)
        except Exception:
            logger.warning("world_builder_parse_degraded", extra={"reason": "llm_failed"})
            return InterventionIntent(kind=KIND_REJECT, reason="世界构建暂时无法处理，请稍后再试。")

        return parse_intent(raw)


def parse_intent(raw: str) -> InterventionIntent:
    """从 LLM 文本解析意图；字段缺失/未知 kind → reject（fail-closed）。"""
    data = extract_json_object(raw)
    if data is None:
        return InterventionIntent(kind=KIND_REJECT, reason="没有听清你的请求，请换个说法。")
    kind = str(data.get("kind", "")).strip()
    if kind not in _KINDS:
        return InterventionIntent(kind=KIND_REJECT, reason="这个请求不在可干涉的范围内。")
    if kind == KIND_REJECT:
        reason = _text(data.get("reason"), 60) or "这个请求无法实现。"
        return InterventionIntent(kind=KIND_REJECT, reason=reason)
    if kind == KIND_CREATE_SCENE:
        title = _text(data.get("title"), 40)
        if not title:
            return InterventionIntent(kind=KIND_REJECT, reason="新场景需要一个地点名。")
        return InterventionIntent(
            kind=kind,
            title=title,
            participants=_participants(data.get("participants")),
            visual_summary=_text(data.get("visual_summary"), 200),
            parent_location_key=_text(data.get("parent_location_key"), 40) or None,
        )
    if kind == KIND_ADD_CHARACTER:
        name = _text(data.get("name"), 20)
        brief = _text(data.get("brief"), 200)
        if not name or not brief:
            return InterventionIntent(kind=KIND_REJECT, reason="新增角色需要姓名与来意。")
        return InterventionIntent(
            kind=kind,
            name=name,
            brief=brief,
            personality=_text(data.get("personality"), 120),
            location_key=_text(data.get("location_key"), 40) or None,
        )
    # pull_in_character
    name = _text(data.get("name"), 20)
    if not name:
        return InterventionIntent(kind=KIND_REJECT, reason="要拉谁入场？请说出角色名。")
    return InterventionIntent(
        kind=kind,
        name=name,
        reason=_text(data.get("reason"), 60) or "他闻讯赶来了。",
    )
