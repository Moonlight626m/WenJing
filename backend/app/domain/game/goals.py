"""续写目标（Stage3）：目标导向的自然收敛。

进入续写时编剧 Agent 定 2–3 个小目标，每轮玩家行动、角色回应之后由验证 Agent
判定哪些已经达成；全部达成即收束（`stage3_rounds` 仍是兜底上限）。

**事件是唯一权威**，目标状态不进 `_RState`：
- `stage3_goals_set {goals: [{goal_id, description}]}`：进入续写时写一次；
- `stage3_goal_achieved {goal_id, description, reason}`：某轮判定达成时写。

`derive_goals` 从活动分支事件派生当前目标——回溯切到新分支、重连、快照重放都
自然得到正确的达成状态，不需要额外对账（与 `assets.RuntimeAssets.rebuild` 同一思路）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.domain.game.event import EVENT_STAGE3_GOAL_ACHIEVED, EVENT_STAGE3_GOALS_SET

# 目标条数上限：多了学生记不住，三轮续写也走不完
MAX_GOALS = 3
# 单条目标的字数上限：要一眼读完；LLM 偶尔写成一段话，超出部分截掉
GOAL_MAX_CHARS = 40


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


def derive_goals(events: Iterable[Any]) -> list[GoalState]:
    """按序折叠事件得到当前目标。接受 `GameEvent` 或其 `to_dict()` 形状。"""
    goals: list[GoalState] = []
    for ev in events:
        if isinstance(ev, dict):
            etype = ev.get("event_type") or ev.get("type") or ""
            payload = ev.get("payload") or {}
        else:
            etype = ev.event_type
            payload = ev.payload or {}
        goals = apply_goal_event(goals, etype, payload)
    return goals


def fallback_goals(teaching_focus: list[str], player_role: str | None) -> list[str]:
    """LLM 不可用或输出无法解析时的确定性目标：直接从教学重点出题。

    没有教学重点时给两条通用目标——续写阶段本就是「课文之外」，这两条对任何课文都成立。
    """
    focus = [f.strip() for f in teaching_focus if f and f.strip()][:MAX_GOALS]
    if focus:
        return [_clip(f"在续写中体现：{f}") for f in focus]
    who = player_role or "你的角色"
    return [
        _clip(f"让{who}做出一个课文里没有的选择"),
        "让一位角色的态度发生明显变化",
    ]


def parse_goal_list(raw: str) -> list[str]:
    """从 LLM 输出里取 `{"goals": [...]}`；取不到或为空返回 []（调用方走兜底）。"""
    obj = extract_json_object(raw)
    items = obj.get("goals") if obj else None
    if not isinstance(items, list):
        return []
    goals = [_clip(str(x).strip()) for x in items if isinstance(x, str) and x.strip()]
    return goals[:MAX_GOALS]


def parse_achieved(raw: str, pending_ids: set[int]) -> tuple[list[int], str]:
    """从 LLM 输出里取 `{"achieved": [...], "reason": "..."}`。

    只认仍未达成的目标编号；解析失败视为本轮没有达成任何目标——宁可少判，
    不让一次胡乱输出把续写提前收掉。
    """
    obj = extract_json_object(raw)
    if not obj:
        return [], ""
    ids: list[int] = []
    for x in obj.get("achieved", []) or []:
        try:
            gid = int(x)
        except (TypeError, ValueError):
            continue
        if gid in pending_ids and gid not in ids:
            ids.append(gid)
    reason = obj.get("reason")
    return ids, (str(reason).strip()[:120] if reason else "")


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(raw: str) -> dict[str, Any] | None:
    """取出文本里的第一个 JSON 对象（容忍 ```json 代码块与前后说明文字）。"""
    match = _JSON_OBJECT.search(raw or "")
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _clip(text: str) -> str:
    return text if len(text) <= GOAL_MAX_CHARS else text[: GOAL_MAX_CHARS - 1] + "…"
