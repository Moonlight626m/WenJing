"""编剧 Agent：剧情推进 + 方向确认 + 交互设计（精简版）。

本 MVP 阶段不测试剧本生成链路（Stage1 的 Script 由外部 mock 提供），
编剧 Agent 聚焦 Stage2/3 的推进与交互设计机制：
- `advance_plot`：推进到下一 beat，产出 PlotAdvancement
- `confirm_direction`：D5 两段式第一步，产出当前矛盾
- `design_interaction`：决定模式（A/B/C）并生成交互点
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.llm_service import LLMService
from app.core.types import (
    Beat,
    Direction,
    InteractionPoint,
    PlotAdvancement,
    Proposal,
    Scene,
    Script,
)

logger = logging.getLogger("wenjing.agents.screenwriter")


@dataclass
class _BeatCtx:
    scene: Scene
    beat: Beat


class ScreenwriterAgent:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm
        self.beat_index = 0

    def reset(self) -> None:
        self.beat_index = 0

    def _current(self, script: Script) -> _BeatCtx:
        total = total_beats(script)
        idx = min(self.beat_index, max(0, total - 1))
        count = 0
        for scene in script.scenes:
            for beat in scene.beats:
                if count == idx:
                    return _BeatCtx(scene, beat)
                count += 1
        raise IndexError("beat index out of range")

    def advance_plot(self, script: Script, stage: str) -> PlotAdvancement:
        """推进到当前 beat 并返回剧情摘要；移动游标。"""
        ctx = self._current(script)
        summary = f"[{stage}] 场景：{ctx.scene.title} — {ctx.beat.description}"
        self.beat_index += 1
        logger.info(
            "advance_plot",
            extra={"beat_id": ctx.beat.beat_id, "summary": summary},
        )
        return PlotAdvancement(
            summary=summary,
            scene_description=f"{ctx.scene.title}：{ctx.beat.description}",
        )

    def confirm_direction(self, script: Script, stage: str) -> Direction:
        """D5 第一步：确认当前矛盾/关键处境。MVP 以当前 beat 描述承担。"""
        ctx = self._current(script)
        return Direction(
            conflict=ctx.beat.description,
            context=f"当前阶段 {stage}，关键处境：{ctx.beat.description}",
        )

    def design_interaction(
        self,
        *,
        stage: str,
        proposals: list[Proposal],
        reached_ending: bool,
    ) -> InteractionPoint:
        """决定交互模式并生成交互点（design_01 §2.5 规则精简版）。"""
        if reached_ending:
            # 到达课文结局：给玩家确认是否进入 Stage3（D14）
            return InteractionPoint(
                mode="options",
                context="已到达课文结局，选择是否进入剧情续写。",
                options=[
                    {"id": 0, "text": "进入剧情续写（Stage3）", "proposed_by": "system"},
                    {"id": 1, "text": "到此结束", "proposed_by": "system"},
                ],
            )
        if stage == "stage2":
            return InteractionPoint(
                mode="options",
                context="请选择你的行动",
                options=[
                    {"id": i, "text": p.description, "proposed_by": p.proposed_by}
                    for i, p in enumerate(proposals or [])
                ],
            )
        return InteractionPoint(
            mode="options_with_fallback",
            context="请选择你的行动，或自定义输入",
            options=[
                {"id": i, "text": p.description, "proposed_by": p.proposed_by}
                for i, p in enumerate(proposals or [])
            ],
            hint="可自定义输入",
        )


def total_beats(script: Script) -> int:
    return sum(len(scene.beats) for scene in script.scenes)
