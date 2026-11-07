"""制作人 Agent（工作人员）：解析玩家干涉（design §B5，M6）。

玩家用自然语言说「建一个雨夜客栈 / 让一个乞丐加入 / 叫船夫过来」，制作人把它
解析成结构化意图；**校验与应用在运行时**（预算、canon、事件化），这里只做解析。
不挂工具、不出场；解析失败或无法归类一律返回 `reject`（fail-closed），
运行时据此写 `intervention_rejected` 并提示玩家。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.game.goals import extract_json_object
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.agents.producer")

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


class ProducerAgent:
    """干涉解析器：自然语言 → `InterventionIntent`（四类之一，其余拒绝）。"""

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def parse_intervention(
        self, text: str, *, context: dict[str, Any]
    ) -> InterventionIntent:
        current_title = _text(context.get("location_title"))
        visited = "、".join(str(v) for v in context.get("visited_titles", [])) or "（无）"
        locations = (
            "、".join(
                f"{item.get('title', '')}={item.get('key', '')}"
                for item in context.get("locations", [])
                if isinstance(item, dict)
            )
            or "（无）"
        )
        roster = "、".join(str(n) for n in context.get("roster", [])) or "（无）"
        player_role = _text(context.get("player_role")) or "（未选）"
        budgets = context.get("budgets", {})

        try:
            raw = await self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是语文课文情景演绎的制作人 Agent（工作人员，不出场）。"
                            "把玩家的干涉请求解析成四类意图之一，只输出 JSON，不要解释。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"玩家在「{current_title}」。已访问地点：{visited}。\n"
                            f"已存在地点（标题=key）：{locations}；地点参数请填 key，"
                            "留空表示当前地点。\n"
                            f"可拉入的角色：{roster}。玩家扮演：{player_role}。\n"
                            f"剩余预算：新场景 {budgets.get('scenes_left', 0)} 个、"
                            f"新角色 {budgets.get('characters_left', 0)} 个。\n"
                            f"玩家请求：{text}\n\n"
                            "允许的意图与字段：\n"
                            "- 新建场景：{\"kind\":\"create_scene\",\"title\":\"地点名\","
                            "\"participants\":[\"在场人物\"],\"visual_summary\":\"一句画面\","
                            "\"parent_location_key\":\"锚定的已访问地点 key（可留空=当前）\"}\n"
                            "- 新增角色：{\"kind\":\"add_character\",\"name\":\"姓名\","
                            "\"brief\":\"身份与来意\",\"personality\":\"性格一句\","
                            "\"location_key\":\"所在地点 key（可留空=当前）\"}\n"
                            "- 拉人入场：{\"kind\":\"pull_in_character\",\"name\":\"角色名\","
                            "\"reason\":\"一句到场理由（可留空=他闻讯赶来）\"}\n"
                            "- 不允许：{\"kind\":\"reject\",\"reason\":\"原因（给学生看）\"}\n"
                            "规则：不得改写已发生事实或课文结局；新角色不得是玩家角色；"
                            "不在可拉入名单里的角色只能走 add_character；拿不准就 reject。"
                        ),
                    },
                ],
                purpose=UsagePurpose.AGENT,
            )
        except Exception:
            logger.warning("producer_parse_degraded", extra={"reason": "llm_failed"})
            return InterventionIntent(kind=KIND_REJECT, reason="制作人暂时无法处理，请稍后再试。")

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
