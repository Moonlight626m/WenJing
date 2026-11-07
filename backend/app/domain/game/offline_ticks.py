"""离线 tick 的确定性部分（design play-through-redesign §B6，里程碑 M7）。

只做**零 LLM、可重放**的事：按墙上时间决定补算几次 tick、生成 tick 的稳定 id、
把被接受的 NPC 行动折叠成 `world_fact` 载荷、生成 `offline_hint` 提示。
「NPC 提议 → 验证」由 `GameRuntime.offline_tick` 用角色 Agent 执行（LLM），
本模块不碰 agent。
"""

from __future__ import annotations

import uuid
from datetime import datetime

#: 一次登录最多补算的离线 tick 数（§B6 的硬上限）
MAX_OFFLINE_TICKS = 3


def plan_offline_ticks(
    *,
    now: datetime,
    last_at: datetime | None,
    interval_minutes: int,
    max_ticks: int = MAX_OFFLINE_TICKS,
) -> int:
    """按距上次活动的时间算出本次应补算的 tick 数（0 = 不补）。

    `last_at` 缺失（无 tick 台账且无会话创建时间）或时间倒退 → 0；
    `interval_minutes <= 0` 视作关闭离线 tick。
    """
    if last_at is None or interval_minutes <= 0:
        return 0
    elapsed_seconds = (now - last_at).total_seconds()
    if elapsed_seconds <= 0:
        return 0
    ticks = int(elapsed_seconds // (interval_minutes * 60))
    return max(0, min(ticks, max_ticks))


def tick_id_for(session_id: uuid.UUID, tick_index: int) -> str:
    """tick 的稳定 id（§B6）：`uuid5(session_id, tick_index)` 的可读形式。"""
    return str(uuid.uuid5(session_id, f"tick:{tick_index}"))


def npc_action_fact(
    *,
    tick_id: str,
    index: int,
    actor: str,
    description: str,
    location_key: str | None,
) -> dict:
    """一条被接受的 NPC 行动 → `world_fact` 载荷（public，进公屏与所有角色视图）。"""
    return {
        "fact_id": f"{tick_id}:{index}",
        "kind": "npc_action",
        "text": f"{actor}：{description}",
        "visibility": "public",
        "audience": [],
        "location_key": location_key,
        "tick_id": tick_id,
    }


def offline_hint_payload(*, ticks: list[str], facts: int) -> dict:
    """「你不在的这段时间」提示（§B6）：不写详细摘要，只指路时间线。"""
    return {
        "ticks": list(ticks),
        "facts": facts,
        "text": (
            f"你不在的这段时间，世界发生了 {facts} 件事（离线 {len(ticks)} 个时段）。"
            "可以在时间线里回看。"
            if facts
            else f"你不在的这段时间里，世界安静地过了 {len(ticks)} 个时段。"
        ),
    }


__all__ = [
    "MAX_OFFLINE_TICKS",
    "npc_action_fact",
    "offline_hint_payload",
    "plan_offline_ticks",
    "tick_id_for",
]
