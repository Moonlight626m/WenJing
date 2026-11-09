"""剧情主持 Agent（DM）：运行期剧情推进、方向确认、交互设计与续写目标。

**不是剧本生成 Agent**。剧本由 `domain/generation/workflow` 生成（`write_script` /
`write_dialogue` 等节点，prompt 在 `domain/prompts/` 的 DB 注册表），本类只服务运行期：
- 旧剧本路径（无珊瑚图 / 无探索图）的确定性 `advance_plot` / `confirm_direction` /
  `design_interaction`；
- 进入 Stage3 时按教学重点定 2–3 个续写目标（本类唯一的 LLM 调用）。
新版 Stage2 珊瑚图是纯 IO 播放，Stage3 探索的每轮推进由确定性
`ExplorationDirector.settle` 承担，都不会调用本类。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.contracts.enums import UsagePurpose
from app.domain.agents.prompting import build_stage3_goals_prompt
from app.domain.game.goals import fallback_goals, parse_goal_list
from app.domain.game.types import (
    Beat,
    Direction,
    InteractionPoint,
    PlotAdvancement,
    Proposal,
    Scene,
    Script,
)
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.agents.game_master")



@dataclass
class _BeatCtx:
    scene: Scene
    beat: Beat


class GameMasterAgent:
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


    async def design_stage3_goals(
        self,
        script: Script,
        *,
        player_role: str | None,
        plot_log: list[str],
    ) -> list[str]:
        """为续写定 2–3 个小目标：学生能靠自己角色的言行达成、并落在教学重点上。

        LLM 失败或输出解析不出目标时退回 `fallback_goals`（直接从教学重点出题），
        续写不因出题失败而卡住。
        """
        bundle = build_stage3_goals_prompt(
            script, player_role=player_role, plot_log=plot_log
        )
        try:
            raw = await self.llm.chat(bundle.messages(), purpose=UsagePurpose.AGENT)
        except Exception:
            logger.warning("stage3_goals_degraded", extra={"reason": "llm_failed"})
            return fallback_goals(script.teaching_focus, player_role)

        goals = parse_goal_list(raw)
        if len(goals) < 2:
            logger.info("stage3_goals_fallback", extra={"parsed": len(goals)})
            return fallback_goals(script.teaching_focus, player_role)
        return goals


def total_beats(script: Script) -> int:
    return sum(len(scene.beats) for scene in script.scenes)
