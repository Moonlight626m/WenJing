"""导演 Agent（工作人员）：为 Stage3 设计玩家行为选项（design §B1/§B2，M6）。

只设计选项、不出场、不写角色台词；不挂工具（上下文由运行时装配），输出结构化
JSON。解析失败/数量不足时返回空列表，由运行时回退到「已验证提议 + 地点 +
自由输入」的确定性选项——导演故障不能让玩家卡住。
"""

from __future__ import annotations

import logging

from app.contracts.enums import UsagePurpose
from app.domain.game.goals import extract_json_object
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.agents.director")

MIN_OPTIONS = 2
MAX_OPTIONS = 4


class DirectorAgent:
    """零工具的选项设计者：输出 2–4 条玩家可执行的行动文案。"""

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def design_options(
        self,
        *,
        location_title: str,
        visual_summary: str,
        player_role: str | None,
        present: list[tuple[str, str]],
        plot_log: list[str],
        direction: dict[str, str],
        goals: list[tuple[str, bool]],
        teaching_focus: list[str],
    ) -> list[str]:
        """返回选项文案（最多 4 条）；失败/解析不出返回空列表。"""
        present_text = "、".join(
            f"{name}（{background}）" if background else name
            for name, background in present
        ) or "（无人）"
        goals_text = "；".join(
            f"{desc}{'（已达成）' if done else ''}" for desc, done in goals
        ) or "（无）"
        recent = "\n".join(plot_log[-6:]) or "（无）"
        conflict = str(direction.get("conflict", "") or "（无）")
        focus = "；".join(teaching_focus) or "（未标注）"

        try:
            raw = await self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是语文课文情景演绎的导演 Agent（工作人员，不出场）。"
                            "你的任务是为玩家设计接下来可以执行的行动选项：具体、可演、"
                            "符合人物与时代，不替玩家决定结果，不引入与课文冲突的事实。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"当前地点：{location_title}。{visual_summary}\n"
                            f"玩家扮演：{player_role or '（未选）'}；在场：{present_text}\n"
                            f"教学重点：{focus}\n续写目标：{goals_text}\n"
                            f"当前处境：{conflict}\n最近发生：\n{recent}\n\n"
                            "请设计 "
                            f"{MIN_OPTIONS} 到 {MAX_OPTIONS} 个玩家行动选项"
                            "（每条一句话、不超过 30 字）。要求："
                            "至少 1 条推进续写目标、1 条处理人物关系、1 条探索环境或换景；"
                            "选项之间要有差异，不要都指向同一件事；不要写玩家已经做过的动作。"
                            '只输出 JSON：{"options": ["选项一", "选项二"]}'
                        ),
                    },
                ],
                purpose=UsagePurpose.AGENT,
            )
        except Exception:
            logger.warning("director_options_degraded", extra={"reason": "llm_failed"})
            return []

        return parse_options(raw)


def parse_options(raw: str) -> list[str]:
    """从 LLM 文本里取选项文案（容忍对象数组与代码块）。

    数量不足 `MIN_OPTIONS` 视为失败（返回空列表）：调用方会回退到
    「已验证提议 + 默认项」，一条孤零零的选项不如确定性回退。
    """
    data = extract_json_object(raw)
    if data is None:
        return []
    items = data.get("options")
    if not isinstance(items, list):
        return []
    options: list[str] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("label", "")).strip()
        else:
            text = ""
        if text and text not in options:
            options.append(text)
        if len(options) >= MAX_OPTIONS:
            break
    return options if len(options) >= MIN_OPTIONS else []
