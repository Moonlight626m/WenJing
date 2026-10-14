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
    """基于 `GameRuntime` 显式状态的 `WorldView` 实现。

    视图**按角色裁剪**（机制层知识边界）：`bind(viewer)` 返回绑定了观众身份的
    代理对象，工具查询只回该角色在场/可公开的信息。`GameRuntime` 在建
    `CharacterAgent` 时逐角色传一个 scoped 视图；全局自用（内部日志、调试）
    仍可用未绑定实例，但那不是给 agent 的。
    """

    def __init__(self, runtime: GameRuntime, viewer: str | None = None) -> None:
        self._runtime = runtime
        # None = 未绑定（仅引擎内部/测试用）：工具消费方一律走 for(name)
        self._viewer = viewer

    def bind(self, viewer: str) -> RuntimeWorldView:
        """返回绑定到某角色的裁剪视图（无状态共享同一 runtime 引用）。"""
        return RuntimeWorldView(self._runtime, viewer=viewer)

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
        state = self._runtime.state
        entries: list[str] = []
        # 剧情推进只记**我参与**的场景：_{viewer} 在场判定看 scene.participants
        viewer = self._viewer
        cursor = 0
        for scene in self._runtime.script.scenes:
            for beat in scene.beats:
                if viewer is None or viewer in scene.participants:
                    entries.append(f"{scene.title}：{beat.description}")
                cursor += 1
                if cursor >= state.beat_cursor:
                    break
            if cursor >= state.beat_cursor:
                break
        # 公开发言台账：只回我在场（scene_key 的场景有我）时的发言
        spoken = [
            f"{speaker}说：{text}"
            for speaker, scene_key, text in state.speech_log
            if self._in_scene(scene_key)
        ]
        return [*entries[:limit], *spoken[-limit:]]

    def _in_scene(self, scene_key: str | None) -> bool:
        """该角色是否在 scene_key 指的场景里（viewer 未绑 = 看不到发言台账）。"""
        if self._viewer is None or scene_key is None:
            return False
        scene = self._runtime._scene_by_key(scene_key)  # noqa: SLF001 - 同包适配器
        return scene is not None and self._viewer in scene.participants

    def direction(self) -> dict[str, str]:
        return dict(self._runtime.state.direction)

    def outline(self) -> list[dict[str, Any]]:
        viewer = self._viewer
        return [
            {
                "scene_id": scene.scene_id,
                "title": scene.title,
                "participants": list(scene.participants),
                "beats": [b.description for b in scene.beats],
            }
            for scene in self._runtime.script.scenes
            if viewer is None or viewer in scene.participants
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
