"""`WorldView` 的运行时实现：把 GameRuntime 的显式状态投影为角色 Agent 可查询的只读视图。

引擎是状态权威；本适配器只读 `runtime.state` / `script`，不持有可变状态，
因此快照恢复 / 事件重放后工具查询立即返回最新世界进度（ADR-0004）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.domain.agents.screenwriter import total_beats

if TYPE_CHECKING:  # 仅类型提示，避免与 game_runtime 循环导入
    from app.domain.game.game_runtime import GameRuntime


class RuntimeWorldView:
    """基于 `GameRuntime` 显式状态的 `WorldView` 实现。"""

    def __init__(self, runtime: GameRuntime) -> None:
        self._runtime = runtime

    def progress(self) -> dict[str, Any]:
        state = self._runtime.state
        return {
            "stage": state.stage,
            "phase": state.phase,
            "beat_cursor": state.beat_cursor,
            "total_beats": total_beats(self._runtime.script),
            "player_role": state.player_role,
            "ended": state.ended,
        }

    def plot_log(self, limit: int = 5) -> list[str]:
        return list(self._runtime.state.plot_log[-limit:])

    def direction(self) -> dict[str, str]:
        return dict(self._runtime.state.direction)

    def outline(self) -> list[dict[str, Any]]:
        return [
            {
                "scene_id": scene.scene_id,
                "title": scene.title,
                "participants": list(scene.participants),
                "beats": [b.description for b in scene.beats],
            }
            for scene in self._runtime.script.scenes
        ]

    def roster(self) -> list[dict[str, Any]]:
        state = self._runtime.state
        return [
            {
                "name": c.name,
                "public_background": c.public_background,
                "is_player_role": c.name == state.player_role,
            }
            for c in self._runtime.script.characters
        ]


__all__ = ["RuntimeWorldView"]
