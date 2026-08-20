"""游戏引擎：状态机驱动 + 事件循环 + Agent 编排 + 回溯（design_03）。

MVP 阶段：
- `Script` 由外部 mock 提供（不测 Stage1 生成链路）
- 纯内存事件流与角色记忆；PostgreSQL 落库作为后续收尾里程碑
- 玩家操作的"驱动"由调用方注入的 `player_decision` 提供（同步 callable），
  未来接入 WebSocket 时替换为该回调即可，引擎编排不变
- 状态机为纯枚举（砍掉 LangGraph），8 步 phase cycle 手写
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.character import CharacterAgentManager
from app.agents.llm_service import LLMService
from app.agents.screenwriter import ScreenwriterAgent
from app.agents.verifier import VerifierAgent
from app.core import event as evt
from app.core.engine_config import EngineConfig
from app.core.event import EventStore
from app.core.state_machine import GameStage, GameStateMachine, InteractionPhase
from app.core.types import InteractionPoint, PlayerAction, Proposal, Script

logger = logging.getLogger("wenjing.core.engine")

# 玩家决策回调：输入当前交互点，返回玩家的写死动作。
PlayerDecision = Callable[[InteractionPoint], Awaitable[PlayerAction]]


class GameEngine:
    """文境游戏引擎主类。"""

    def __init__(
        self,
        *,
        session_id: str,
        script: Script,
        llm: LLMService,
        config: EngineConfig | None = None,
        enable_logging: bool = True,
        event_store: EventStore | None = None,
        on_flush: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        from app.core.logging_config import configure_logging, get_logger

        if enable_logging:
            configure_logging()
        self._log = get_logger("core.engine", session_id=session_id)

        self.session_id = session_id
        self.script = script
        self.state_machine = GameStateMachine()
        self.event_store: EventStore = event_store or EventStore()
        self._on_flush = on_flush
        self.config = config or EngineConfig()
        self._log.debug("engine_init", extra={"config": self.config})

        self.screenwriter = ScreenwriterAgent(llm)
        self.verifier = VerifierAgent(llm)
        self.characters = CharacterAgentManager(llm)
        self.characters.create_agents(script.characters)
        self.player_role = self.characters.player_role

        # 每轮 cycle 开头的角色记忆快照（用于回溯恢复）：[(event_id_at_start, snapshot)]
        self._memory_snapshots: list[tuple[int, dict[str, Any]]] = []
        self.ended: bool = False
        self.stage3_round_taken: int = 0

    # ===== 对外生命周期 =====

    async def run(self, player_decision: PlayerDecision) -> dict:
        """从剧本推进到游戏结束，返回游戏终止摘要。"""
        self._transition_to(GameStage.STAGE1_COMPLETE)
        await self._run_stage2(player_decision)
        if self.ended:
            return self.summary()
        await self._run_stage3(player_decision)
        return self.summary()

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "stage": self.state_machine.stage.value,
            "player_role": self.player_role,
            "event_count": len(self.event_store),
            "latest_event_id": self.event_store.latest_event_id,
            "ended": self.ended,
        }

    # ===== Stage 流程 =====

    async def _run_stage2(self, player_decision: PlayerDecision) -> None:
        self._transition_to(GameStage.STAGE2_REENACTING)
        self._log.info("stage2_start", extra={"player": self.player_role})

        while True:
            self._snapshot_memories()
            result = await self._execute_phase_cycle(
                stage="stage2", player_decision=player_decision
            )

            if result["rollback"]:
                await self._execute_rollback(result["steps"])
                continue
            if result["ended"]:
                self.ended = True
                self._transition_to(GameStage.ENDED)
                return
            if result["stage_complete"]:
                break

        # 到达课文结局，进入 Stage2_complete → 玩家确认进 Stage3
        self._transition_to(GameStage.STAGE2_COMPLETE)
        self._log.info("stage2_complete")

    async def _run_stage3(self, player_decision: PlayerDecision) -> None:
        self._transition_to(GameStage.STAGE3_EXTENDING)
        self._log.info("stage3_start")

        for _ in range(self.config.stage3_rounds):
            self._snapshot_memories()
            result = await self._execute_phase_cycle(
                stage="stage3", player_decision=player_decision
            )
            self.stage3_round_taken += 1
            if result["rollback"]:
                await self._execute_rollback(result["steps"])
                continue
            if result["ended"]:
                break

        self._transition_to(GameStage.ENDED)
        self.ended = True
        self._log.info("stage3_end", extra={"rounds": self.stage3_round_taken})

    # ===== 8 步 phase cycle =====

    async def _execute_phase_cycle(
        self, *, stage: str, player_decision: PlayerDecision
    ) -> dict:
        # Step 1: 编剧推进剧情
        self._enter_phase(InteractionPhase.NARRATIVE)
        adv = self.screenwriter.advance_plot(self.script, stage)
        self.event_store.append(
            evt.EVENT_PLOT_ADVANCEMENT,
            {"summary": adv.summary, "scene": adv.scene_description},
            session_id=self.session_id,
        )
        self.characters.broadcast_plot_context(adv.summary)

        # Step 2: 方向确认（D5 第一步）
        self._enter_phase(InteractionPhase.DIRECTION)
        direction = self.screenwriter.confirm_direction(self.script, stage)
        self.event_store.append(
            evt.EVENT_DIRECTION,
            {"conflict": direction.conflict, "context": direction.context},
            session_id=self.session_id,
        )
        self.characters.broadcast_direction(
            {"conflict": direction.conflict, "context": direction.context}
        )

        # Step 3: 角色并行提议
        self._enter_phase(InteractionPhase.AGENT_PROPOSAL)
        proposals = await self._collect_proposals(stage)

        # Step 4: 验证（含重试 ≤2）
        self._enter_phase(InteractionPhase.VERIFICATION)
        valid = await self._verify_proposals(proposals, stage)

        # Step 5: 交互设计（判定是否到达结局以便给确认选项）
        self._enter_phase(InteractionPhase.INTERACTION_DESIGN)
        reached_ending = (
            stage == "stage2"
            and self.screenwriter.beat_index >= _total_beats(self.script)
        )
        interaction = self.screenwriter.design_interaction(
            stage=stage, proposals=valid, reached_ending=reached_ending
        )

        # Step 6: 玩家操作
        self._enter_phase(InteractionPhase.PLAYER_TURN)
        action = await player_decision(interaction)
        self.event_store.append(
            evt.EVENT_PLAYER_ACTION,
            {"type": action.type, "text": action.text, "option_id": action.option_id},
            session_id=self.session_id,
        )

        if action.type == "rollback":
            self._log.info("player_rollback", extra={"steps": action.steps})
            return {"rollback": True, "steps": action.steps, "ended": False}
        if action.type == "exit":
            return {"rollback": False, "ended": True, "stage_complete": False}

        # 到达结局且玩家确认进入续写 → 标 stage_complete
        if reached_ending:
            choice = action.option_id
            self._log.info("ending_choice", extra={"choice": choice})
            if choice == 1:  # 到此结束
                return {"rollback": False, "ended": True, "stage_complete": False}
            return {"rollback": False, "ended": False, "stage_complete": True}

        # Step 7: 角色反应
        self._enter_phase(InteractionPhase.AGENT_REACTION)
        if stage == "stage3":
            await self._collect_reactions(action, stage)
        else:
            await self._collect_reactions(action, stage)

        # Step 8: Stage 结束检测
        self._enter_phase(InteractionPhase.STAGE_CHECK)
        await self._flush_events()
        return {"rollback": False, "ended": False, "stage_complete": False}

    # ===== Agent 调度 =====

    async def _collect_proposals(self, stage: str) -> list[Proposal]:
        names = self.characters.active_names()
        self._log.info("propose_start", extra={"characters": names})

        async def _one(name: str) -> Proposal:
            return await self.characters.get(name).propose_action(stage)

        results = await asyncio.gather(
            *[_one(n) for n in names], return_exceptions=True
        )
        proposals: list[Proposal] = []
        for name, res in zip(names, results):
            if isinstance(res, BaseException):
                self._log.error("propose_failed", extra={"name": name, "err": str(res)})
                continue
            self.event_store.append(
                evt.EVENT_PROPOSAL,
                {"proposed_by": name, "description": res.description},
                session_id=self.session_id,
            )
            proposals.append(res)
        self._log.info("propose_done", extra={"count": len(proposals)})
        return proposals

    async def _verify_proposals(self, proposals: list[Proposal], stage: str) -> list[Proposal]:
        valid: list[Proposal] = []
        pending = proposals
        attempts_left = self.config.max_proposal_retries
        while pending and attempts_left >= 0:
            results = await asyncio.gather(
                *[self.verifier.verify_proposal(p, stage) for p in pending],
                return_exceptions=True,
            )
            still_pending: list[Proposal] = []
            for prop, res in zip(pending, results):
                if isinstance(res, BaseException):
                    self._log.error("verify_failed", extra={"proposal": prop.proposal_id})
                    valid.append(prop)  # 降级收录
                    continue
                self.event_store.append(
                    evt.EVENT_VERIFICATION,
                    {"proposal_id": prop.proposal_id, "verdict": res.verdict, "score": res.score},
                    session_id=self.session_id,
                )
                if res.verdict == "reject" and attempts_left > 0:
                    revised = self.characters.get(prop.proposed_by).revise_proposal(
                        res.rejections[0].suggestion if res.rejections else None
                    )
                    still_pending.append(revised)
                elif res.verdict == "reject":
                    # 重试用尽，放弃
                    self._log.info(
                        "proposal_dropped", extra={"proposed_by": prop.proposed_by}
                    )
                else:
                    valid.append(prop)
            pending = still_pending
            attempts_left -= 1
        return valid

    async def _collect_reactions(self, action: PlayerAction, stage: str) -> None:
        names = self.characters.active_names()
        results = await asyncio.gather(
            *[self.characters.get(n).react_to(action, stage) for n in names],
            return_exceptions=True,
        )
        for name, res in zip(names, results):
            if isinstance(res, BaseException):
                self._log.error("react_failed", extra={"name": name, "err": str(res)})
                continue
            self.event_store.append(
                evt.EVENT_CHARACTER_SPEECH,
                {"speaker": name, "text": res},
                session_id=self.session_id,
            )

    # ===== 回溯 =====

    async def _execute_rollback(self, steps: int) -> None:
        if steps <= 0 or steps > self.config.max_rollback_steps:
            from app.errx import codes, new

            raise new(
                codes.ENG_ROLLBACK_OVERFLOW,
                extra={"steps": steps, "max_steps": self.config.max_rollback_steps},
            )
        current = self.event_store.latest_event_id
        target = current - steps
        if target < 1:
            from app.errx import codes, new

            raise new(
                codes.ENG_ROLLBACK_TARGET_MISSING, extra={"event_id": target}
            )
        # 恢复角色记忆到最近的不晚于 target 的快照
        restore_to = 0
        snapshot = {}
        for mark_event_id, snap in self._memory_snapshots:
            if mark_event_id <= target:
                restore_to, snapshot = mark_event_id, snap
        if snapshot:
            self.characters.restore_memories(snapshot)
        trunc = self.event_store.rollback_to(target, session_id=self.session_id)
        self.event_store.append(
            evt.EVENT_ROLLBACK,
            {"steps": steps, "target": target, "truncated": len(trunc)},
            session_id=self.session_id,
        )
        self._log.info(
            "rollback_done",
            extra={"steps": steps, "target": target, "restore_to": restore_to},
        )

    # ===== 辅助 =====

    def _snapshot_memories(self) -> None:
        self._memory_snapshots.append(
            (self.event_store.latest_event_id, self.characters.snapshot_memories())
        )

    def _enter_phase(self, phase: InteractionPhase) -> None:
        self.state_machine.enter_phase(phase)

    def _transition_to(self, stage: GameStage) -> None:
        self.state_machine.set_stage(stage)
        self.event_store.append(
            evt.EVENT_STAGE_TRANSITION,
            {"stage": stage.value},
            session_id=self.session_id,
        )
        self._log.info("stage_transition", extra={"stage": stage.value})

    async def _flush_events(self) -> None:
        """若有持久化回调（落库），在 phase 断点刷写事件。"""
        if self._on_flush is not None:
            await self._on_flush()


def _total_beats(script: Script) -> int:
    return sum(len(scene.beats) for scene in script.scenes)
