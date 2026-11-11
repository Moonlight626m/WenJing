"""旧 Stage3 目标事件的读兼容（已停止写入）。

2026-11 起 Stage3 改为无目标、无轮次上限的自由续写，`stage3_goals_set` /
`stage3_goal_achieved` 不再产生。这里只保留折叠逻辑，让历史会话仍能把目标
投影到 `RuntimeState.stage3_goals`（恒为空的新会话不受影响）；下一主版本随
契约字段一起删除。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.game.event import EVENT_STAGE3_GOAL_ACHIEVED, EVENT_STAGE3_GOALS_SET


@dataclass
class GoalState:
    goal_id: int
    description: str
    achieved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "achieved": self.achieved,
        }


def apply_goal_event(
    goals: list[GoalState], event_type: str, payload: dict[str, Any]
) -> list[GoalState]:
    """单条事件作用于目标列表，返回新列表（不改入参）。无关事件原样返回。"""
    if event_type == EVENT_STAGE3_GOALS_SET:
        return [
            GoalState(goal_id=int(g["goal_id"]), description=str(g.get("description", "")))
            for g in payload.get("goals", [])
            if isinstance(g, dict) and "goal_id" in g
        ]
    if event_type == EVENT_STAGE3_GOAL_ACHIEVED:
        gid = payload.get("goal_id")
        return [
            GoalState(g.goal_id, g.description, g.achieved or g.goal_id == gid) for g in goals
        ]
    return goals
