"""事件溯源存储（内存实现，issue #8 分支语义）。

MVP 阶段使用 design_03 的内存版 `EventStore`，事件只追加（append-only）。
每条 `GameEvent` 同时以 structured 日志输出（「事件即日志」），使纯内存运行
也能从日志还原整场剧情，便于调试与回溯。

issue #8 分支语义：
- 回溯不物理删除历史；`rollback_to` 创建新活动分支（root 指向目标事件），
  旧分支事件保留可审计。
- `branch_path(branch_id)` 按血缘链（root → … → parent → branch）重建该分支
  的完整有序历史（继承前缀只取到子分支的 root 事件为止）。
- 事件 ID 全局单调递增；分支用整数 id（1 = 主分支）以保持确定性。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.errx import codes, new

logger = logging.getLogger("wenjing.core.event")

# 事件类型（对齐 design_03 §4.1）
EVENT_STAGE_TRANSITION = "stage_transition"
EVENT_PLOT_ADVANCEMENT = "plot_advancement"
EVENT_DIRECTION = "direction"
EVENT_PROPOSAL = "proposal"
EVENT_VERIFICATION = "verification"
EVENT_PLAYER_ACTION = "player_action"
EVENT_CHARACTER_SPEECH = "character_speech"
EVENT_SYSTEM = "system"
EVENT_ROLLBACK = "rollback"

MAIN_BRANCH_ID = 1


@dataclass
class BranchMeta:
    """事件分支元数据：血缘链 + 继承历史终点。"""

    branch_id: int
    parent_branch_id: int | None
    root_event_id: int = 0  # 继承历史终止于该事件（含）；主分支恒为 0
    created_by_command_id: str = ""


@dataclass
class GameEvent:
    """单条游戏事件。"""

    event_id: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    parent_id: int | None = None
    timestamp: float = field(default_factory=time.time)
    branch_id: int = MAIN_BRANCH_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "branch_id": self.branch_id,
        }


class EventStore:
    """内存事件流。MVP 全程常驻内存；PostgreSQL 落库作为后续收尾里程碑。

    issue #8 起带分支语义：append 写入当前活动分支；`rollback_to` 新建分支
    并切换活动分支，旧事件保留。
    """

    def __init__(self) -> None:
        self._events: list[GameEvent] = []
        self._counter = 0
        self._branch_counter = MAIN_BRANCH_ID
        self._active_branch = MAIN_BRANCH_ID
        self._branch_meta: dict[int, BranchMeta] = {
            MAIN_BRANCH_ID: BranchMeta(
                branch_id=MAIN_BRANCH_ID, parent_branch_id=None, root_event_id=0
            )
        }

    @property
    def events(self) -> list[GameEvent]:
        return self._events

    def __len__(self) -> int:
        return len(self._events)

    @property
    def latest_event_id(self) -> int:
        return self._events[-1].event_id if self._events else 0

    @property
    def active_branch_id(self) -> int:
        return self._active_branch

    @property
    def branches(self) -> list[BranchMeta]:
        """按创建顺序返回分支元数据（主分支在前），供审计。"""
        return [self._branch_meta[i] for i in sorted(self._branch_meta)]

    def branch_meta(self, branch_id: int) -> BranchMeta:
        if branch_id not in self._branch_meta:
            raise new(codes.ENG_ROLLBACK_TARGET_MISSING, extra={"event_id": branch_id})
        return self._branch_meta[branch_id]

    def events_in_branch(self, branch_id: int) -> list[GameEvent]:
        """仅该分支自己追加的事件（不含继承前缀）。"""
        return [e for e in self._events if e.branch_id == branch_id]

    def branch_path(self, branch_id: int) -> list[GameEvent]:
        """重建分支完整有序历史：沿血缘链继承前缀 + 本分支事件。"""
        self.branch_meta(branch_id)  # 校验分支存在
        lineage: list[int] = []
        cur: int | None = branch_id
        while cur is not None:
            lineage.append(cur)
            cur = self._branch_meta[cur].parent_branch_id
        lineage.reverse()

        out: list[GameEvent] = []
        for i, bid in enumerate(lineage):
            limit = (
                self._branch_meta[lineage[i + 1]].root_event_id
                if i < len(lineage) - 1
                else None
            )
            for e in self._events:
                if e.branch_id == bid and (limit is None or e.event_id <= limit):
                    out.append(e)
        return out

    def active_events(self) -> list[GameEvent]:
        """活动分支的完整有序历史（回放/审计的权威序列）。"""
        return self.branch_path(self._active_branch)

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        parent_id: int | None = None,
        *,
        session_id: str = "",
    ) -> GameEvent:
        self._counter += 1
        event = GameEvent(
            event_id=self._counter,
            event_type=event_type,
            payload=payload,
            parent_id=parent_id,
            branch_id=self._active_branch,
        )
        self._events.append(event)
        # 事件即日志：以结构化形式输出，便于纯内存运行还原剧情
        logger.info(
            "event",
            extra={
                "event_id": event.event_id,
                "event_type": event.event_type,
                "payload": payload,
                "session_id": session_id or None,
                "branch_id": event.branch_id,
            },
        )
        return event

    def rollback_to(
        self, target_event_id: int, *, session_id: str = "", command_id: str = ""
    ) -> list[GameEvent]:
        """回溯到指定事件（保留目标事件），创建新活动分支。

        返回旧活动分支中被「放弃」的事件（目标之后的事件），它们仍保留在
        事件流中可审计，只是不再属于活动路径。
        """
        target_idx = next(
            (i for i, e in enumerate(self._events) if e.event_id == target_event_id),
            -1,
        )
        if target_idx == -1:
            raise new(
                codes.ENG_ROLLBACK_TARGET_MISSING, extra={"event_id": target_event_id}
            )
        target = self._events[target_idx]

        superseded = [
            e
            for e in self._events
            if e.branch_id == self._active_branch and e.event_id > target_event_id
        ]

        self._branch_counter += 1
        new_branch = self._branch_counter
        self._branch_meta[new_branch] = BranchMeta(
            branch_id=new_branch,
            parent_branch_id=target.branch_id,
            root_event_id=target_event_id,
            created_by_command_id=command_id,
        )
        self._active_branch = new_branch
        logger.info(
            "rollback_new_branch",
            extra={
                "target_event_id": target_event_id,
                "superseded": len(superseded),
                "new_branch_id": new_branch,
                "session_id": session_id or None,
            },
        )
        return superseded
