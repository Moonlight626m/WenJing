"""导演 Agent（工作人员）：为 Stage3 设计玩家行为选项（design §B1/§B2，M6）。

只设计选项、不出场、不写角色台词；不挂工具（上下文由运行时装配），输出结构化
JSON。解析失败/数量不足时返回空列表，由运行时回退到「已验证提议 + 地点 +
自由输入」的确定性选项——导演故障不能让玩家卡住。

Prompt 组装在 `domain/agents/prompting.py`（`build_director_prompt`）：稳定 system +
每轮变量 user，改那里即生效，不走 `prompts` 表的 DB 覆盖与版本号机制。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.contracts.enums import UsagePurpose
from app.domain.agents.prompting import build_director_prompt
from app.domain.game.goals import extract_json_object
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.agents.director")

MIN_OPTIONS = 2
MAX_OPTIONS = 4
DIMENSIONS = frozenset({"goal", "relationship", "environment"})


@dataclass(frozen=True)
class DirectorOption:
    """一条玩家行动选项；`dimension` 只用于日志与后续分析，不展示给玩家。"""

    label: str
    dimension: str | None = None


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
        recent_speeches: list[tuple[str, str]] | None = None,
        last_options: list[str] | None = None,
        public_facts: list[str] | None = None,
    ) -> list[DirectorOption]:
        """返回选项（最多 4 条）；失败/解析不出返回空列表。"""
        bundle = build_director_prompt(
            {
                "location_title": location_title,
                "visual_summary": visual_summary,
                "player_role": player_role,
                "present": present,
                "plot_log": plot_log,
                "direction": direction,
                "goals": goals,
                "teaching_focus": teaching_focus,
                "recent_speeches": recent_speeches or [],
                "last_options": last_options or [],
                "public_facts": public_facts or [],
            }
        )
        try:
            raw = await self.llm.chat(bundle.messages(), purpose=UsagePurpose.AGENT)
        except Exception:
            logger.warning("director_options_degraded", extra={"reason": "llm_failed"})
            return []

        options = parse_option_items(raw)
        _log_dimensions(options)
        return options


def parse_option_items(raw: str) -> list[DirectorOption]:
    """从 LLM 文本里取选项（容忍对象数组与代码块）。

    数量不足 `MIN_OPTIONS` 视为失败（返回空列表）：调用方会回退到
    「已验证提议 + 默认项」，一条孤零零的选项不如确定性回退。
    `dimension` 缺失或非法不阻断，归一为 `None`，由调用方记日志。
    """
    data = extract_json_object(raw)
    if data is None:
        return []
    items = data.get("options")
    if not isinstance(items, list):
        return []
    options: list[DirectorOption] = []
    labels: set[str] = set()
    for item in items:
        if isinstance(item, str):
            label, dimension = item.strip(), None
        elif isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            dimension = _dimension(item.get("dimension"))
        else:
            label, dimension = "", None
        if label and label not in labels:
            labels.add(label)
            options.append(DirectorOption(label=label, dimension=dimension))
        if len(options) >= MAX_OPTIONS:
            break
    return options if len(options) >= MIN_OPTIONS else []


def _dimension(value: object) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in DIMENSIONS else None


def _log_dimensions(options: list[DirectorOption]) -> None:
    """dimension 只记日志、不强校验：导演一次不合规不该让玩家看到兜底选项。"""
    if not options:
        return
    missing = [option.label for option in options if option.dimension is None]
    covered = {option.dimension for option in options if option.dimension}
    if missing or len(covered) < 2:
        logger.info(
            "director_dimension_thin",
            extra={
                "wj_extra": {
                    "count": len(options),
                    "covered": sorted(covered),
                    "missing": missing,
                }
            },
        )
