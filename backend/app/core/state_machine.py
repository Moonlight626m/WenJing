"""游戏状态机：GameStage（顶层阶段）+ InteractionPhase（8 步交互阶段）。

基于 design_03 §2 的实现；MVP 阶段砍掉 LangGraph，改为纯枚举 + 显式转换表。

`GameStage` / `InteractionPhase` 自 Shared Contracts（app.contracts.runtime）提升，
此处仅转发引用；值向后兼容（ticket #2 冻结契约层，ticket #7 重构引擎时消费）。
"""

from __future__ import annotations

from app.contracts.runtime import GameStage, InteractionPhase
from app.errx import codes, new

# 允许的顶层阶段转换（INIT 仅由引擎注入剧本后跳过创建进入 Stage1_complete）
_TRANSITIONS: dict[GameStage, set[GameStage]] = {
    GameStage.INIT: {GameStage.STAGE1_COMPLETE, GameStage.ENDED},
    GameStage.STAGE1_CREATING: {GameStage.STAGE1_COMPLETE, GameStage.ENDED},
    GameStage.STAGE1_COMPLETE: {GameStage.STAGE2_REENACTING, GameStage.ENDED},
    GameStage.STAGE2_REENACTING: {GameStage.STAGE2_COMPLETE, GameStage.ENDED},
    GameStage.STAGE2_COMPLETE: {GameStage.STAGE3_EXTENDING, GameStage.ENDED},
    GameStage.STAGE3_EXTENDING: {GameStage.ENDED},
    GameStage.ENDED: set(),
}


class GameStateMachine:
    """阶段状态机：负责父级阶段的转换与当前交互 phase 的跟踪。"""

    def __init__(self) -> None:
        self._stage: GameStage = GameStage.INIT
        self._phase: InteractionPhase | None = None

    @property
    def stage(self) -> GameStage:
        return self._stage

    @property
    def phase(self) -> InteractionPhase | None:
        return self._phase

    def set_stage(self, target: GameStage) -> None:
        if target not in _TRANSITIONS[self._stage]:
            raise new(
                codes.ENG_INVALID_TRANSITION,
                extra={"src": self._stage.value, "dst": target.value},
            )
        self._stage = target

    def enter_phase(self, phase: InteractionPhase) -> None:
        self._phase = phase

    def clear_phase(self) -> None:
        self._phase = None

    def snapshot(self) -> dict:
        return {
            "stage": self._stage.value,
            "phase": self._phase.value if self._phase else None,
        }

    def restore(self, snapshot: dict) -> None:
        self._stage = GameStage(snapshot["stage"])
        self._phase = (
            InteractionPhase(snapshot["phase"]) if snapshot.get("phase") else None
        )
