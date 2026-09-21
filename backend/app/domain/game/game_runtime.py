"""GameRuntime：可恢复的 command/step 游戏运行时（issue #7 / 取代长驻 run）。

语义：
- `start()` 初始化会话（剧本在构造时注入），停在选角点。
- `submit(...)` 是唯一输入入口；每次提交从当前稳定交互点推进到下一个
  稳定交互点或终态，返回 StepResult（#5 Session 层映射为契约 RuntimeUpdate）。
- `rollback(...)` 回退保留旧历史事件（分支语义由 #8 扩展）。
- 进度游标、阶段、玩家角色、剧情上下文与角色记忆全部位于显式 `_RState`
  及其序列化投影 `export_state()` / `restore()` —— 不依赖隐藏对象字段即可重建。
- 引擎不 import FastAPI/WebSocket/SQLAlchemy/DB；LLM 仅经构造注入的 gateway。

`command_id` 幂等：重复提交返回首次结果并标 `duplicate=True`，不产生重复领域事件。
allowed_commands 从共享契约 `app.contracts.enums` 单源派生。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.contracts.enums import ALLOWED_COMMANDS, StageValue
from app.domain.agents.character import CharacterAgentManager
from app.domain.agents.screenwriter import ScreenwriterAgent, total_beats
from app.domain.agents.verifier import VerifierAgent
from app.domain.game import event as evt
from app.domain.game.engine_config import EngineConfig
from app.domain.game.event import EventStore
from app.domain.game.state_machine import GameStage, GameStateMachine, InteractionPhase
from app.domain.game.types import (
    InteractionPoint,
    PlayerAction,
    Proposal,
    Script,
)
from app.domain.llm import LLMService
from app.infrastructure.errx import codes, new

_ALLOWED_BY_STAGE: dict[str, frozenset[str]] = {
    stage.value: frozenset(kind.value for kind in kinds)
    for stage, kinds in ALLOWED_COMMANDS.items()
}
_STAGE_ALIASES: dict[str, str] = {
    "stage2": StageValue.STAGE2_REENACTING.value,
    "stage3": StageValue.STAGE3_EXTENDING.value,
}


@dataclass
class _RState:
    """显式、可序列化的运行时状态（进度游标等全部在此，无隐藏字段）。"""

    stage: str = StageValue.INIT.value
    phase: str | None = None
    player_role: str | None = None
    beat_cursor: int = 0
    stage3_round_taken: int = 0
    plot_log: list[str] = field(default_factory=list)
    ended: bool = False


@dataclass
class StepResult:
    """一次命令推进的结果（内部形状；Session 层映射 contracts.RuntimeUpdate）。"""

    state: dict
    new_events: list[dict]
    active_interaction: dict | None
    allowed_commands: list[str]
    terminal: bool = False
    duplicate: bool = False


def _interaction_payload(ix: InteractionPoint | None) -> dict | None:
    if ix is None:
        return None
    return {
        "mode": ix.mode,
        "context": ix.context,
        "options": [dict(o) for o in ix.options],
        "hint": ix.hint,
    }


class GameRuntime:
    """文境游戏运行时主类：start / submit / restore / rollback。"""

    def __init__(
        self,
        *,
        session_id: str,
        script: Script,
        llm: LLMService,
        config: EngineConfig | None = None,
        log: logging.Logger | None = None,
        event_store: EventStore | None = None,
        on_flush: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.session_id = session_id
        self.script = script
        self.config = config or EngineConfig()
        # 注意：EventStore 定义了 __len__（空存储为 falsy），必须显式判 None，
        # 否则 `event_store or EventStore()` 会静默丢弃空 PersistentEventStore
        self.event_store: EventStore = (
            event_store if event_store is not None else EventStore()
        )
        self._on_flush = on_flush
        self._log = log or logging.getLogger("wenjing.core.runtime")

        self.state_machine = GameStateMachine()
        self.screenwriter = ScreenwriterAgent(llm)
        self.verifier = VerifierAgent(llm)
        self.characters = CharacterAgentManager(llm)
        self.characters.create_agents(script.characters)

        self.state = _RState()
        self.active_interaction: InteractionPoint | None = None
        self._processed_commands: dict[str, StepResult] = {}
        # 本次命令追加的全部事件（#5：WS 实时消息投影的完整来源）
        self._command_events: list[dict] = []
        # 记忆快照标记：(事件id, 记忆快照, 该时刻的 beat 游标)
        self._memory_marks: list[tuple[int, dict[str, Any], int]] = []
        self._valid_proposals: list[Proposal] = []

    # ===== 显式状态导出 / 恢复 =====

    def export_state(self) -> dict:
        s = self.state
        return {
            "stage": s.stage,
            "phase": s.phase,
            "player_role": s.player_role,
            "beat_cursor": s.beat_cursor,
            "stage3_round_taken": s.stage3_round_taken,
            "plot_log": list(s.plot_log),
            "ended": s.ended,
            "character_memories": self.characters.snapshot_memories(),
            "latest_event_id": self.event_store.latest_event_id,
            "active_branch_id": self.event_store.active_branch_id,
            "active_interaction": _interaction_payload(self.active_interaction),
        }

    def restore(self, state_dump: dict) -> None:
        """从显式状态快照重建运行时（快照 + 重放基线；分支重放语义在 #8 完善）。"""
        s = self.state
        s.stage = state_dump.get("stage", StageValue.INIT.value)
        s.phase = state_dump.get("phase")
        s.player_role = state_dump.get("player_role")
        s.beat_cursor = int(state_dump.get("beat_cursor", 0))
        s.stage3_round_taken = int(state_dump.get("stage3_round_taken", 0))
        s.plot_log = list(state_dump.get("plot_log", []))
        s.ended = bool(state_dump.get("ended", False))

        self.screenwriter.beat_index = s.beat_cursor
        self.characters.restore_memories(state_dump.get("character_memories") or {})
        if s.player_role:
            self.characters.player_role = s.player_role

        self.state_machine.restore({"stage": s.stage, "phase": s.phase})

        ix = state_dump.get("active_interaction")
        self.active_interaction = (
            InteractionPoint(
                mode=ix["mode"],
                context=ix.get("context", ""),
                options=[dict(o) for o in ix.get("options", [])],
                hint=ix.get("hint", ""),
            )
            if ix
            else None
        )

    def replay_from(
        self, snapshot_state: dict | None, events: list[dict]
    ) -> None:
        """快照 + 事件重放重建运行时（issue #8 验收标准 1）。

        快照提供记忆基线（character_memories/beat_cursor/plot_log/stage），
        随后按事件顺序重放确定性的状态迁移：
        - stage_transition → stage / ended
        - plot_advancement → beat_cursor+1、plot_log 追加、剧情上下文广播
        - direction → 角色处境上下文广播
        - system(selected_role) → player_role
        - player_action（Stage3）→ stage3_round_taken+1

        事件形如 `GameEvent.to_dict()`（含 event_type + payload）。纯 LLM 文本
        （角色发言/提议原文）不入状态，由快照记忆承担。
        """
        if snapshot_state is not None:
            self.restore(snapshot_state)
        else:
            self.state = _RState()
            self.screenwriter.beat_index = 0
            self.characters.restore_memories({})

        for ev in events:
            self._replay_event(ev)

        # 使 state_machine / screenwriter 与重放结果一致
        self.state_machine.restore({"stage": self.state.stage, "phase": self.state.phase})
        self.screenwriter.beat_index = self.state.beat_cursor
        if self.state.player_role:
            self.characters.player_role = self.state.player_role

    def _replay_event(self, ev: dict) -> None:
        etype = ev.get("event_type") or ev.get("type")
        payload = ev.get("payload") or {}
        if etype == evt.EVENT_STAGE_TRANSITION:
            stage = payload.get("stage")
            if stage:
                self.state.stage = stage
                if stage == GameStage.ENDED.value:
                    self.state.ended = True
        elif etype == evt.EVENT_PLOT_ADVANCEMENT:
            summary = payload.get("summary", "")
            self.state.beat_cursor += 1
            if summary:
                self.state.plot_log.append(summary)
                self.characters.broadcast_plot_context(summary)
        elif etype == evt.EVENT_DIRECTION:
            self.characters.broadcast_direction(
                {
                    "conflict": payload.get("conflict", ""),
                    "context": payload.get("context", ""),
                }
            )
        elif etype == evt.EVENT_SYSTEM:
            role = payload.get("selected_role")
            if role:
                self.state.player_role = role
                self.characters.player_role = role
        elif etype == evt.EVENT_PLAYER_ACTION:
            if self.state.stage == StageValue.STAGE3_EXTENDING.value:
                self.state.stage3_round_taken += 1

    # ===== 生命周期 =====

    async def start(self) -> StepResult:
        """初始化到 STAGE1_COMPLETE 停靠点：等待 select_role。"""
        self._command_events = []
        self.state.stage = StageValue.STAGE1_CREATING.value
        self._transition_to(StageValue.STAGE1_COMPLETE.value)
        return await self._result_at_point(new_events=[])

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "stage": self.state.stage,
            "player_role": self.state.player_role,
            "beat_cursor": self.state.beat_cursor,
            "event_count": len(self.event_store),
            "latest_event_id": self.event_store.latest_event_id,
            "ended": self.state.ended,
        }

    # ===== 命令入口（幂等）=====

    async def submit(
        self, *, command_id: str, kind: str, payload: dict | None = None
    ) -> StepResult:
        key = str(command_id)
        cached = self._processed_commands.get(key)
        if cached is not None:
            return StepResult(
                state=cached.state,
                new_events=list(cached.new_events),
                active_interaction=cached.active_interaction,
                allowed_commands=list(cached.allowed_commands),
                terminal=cached.terminal,
                duplicate=True,
            )
        result = await self._dispatch(key, kind, payload or {})
        self._processed_commands[key] = result
        return result

    async def _dispatch(
        self, cid: str, kind: str, payload: dict[str, Any]
    ) -> StepResult:
        self._command_events = []
        stage = self.state.stage
        if kind not in _ALLOWED_BY_STAGE.get(stage, frozenset()):
            raise new(
                codes.ENG_PLAYER_ACTION_INVALID,
                extra={"kind": kind, "stage": stage},
            )

        match kind:
            case "select_role":
                return await self._on_select_role(payload)
            case "choose_option":
                return await self._on_input(cid, action_type="choose_option", payload=payload)
            case "free_input":
                return await self._on_input(cid, action_type="speak", payload=payload)
            case "rollback_to_event":
                target = int(payload.get("target_event_id", 0))
                return await self.rollback(command_id=cid, target_event_id=target)
            case "enter_stage3":
                return await self._on_enter_stage3()
            case "confirm_ending":
                self._transition_to(GameStage.ENDED.value)
                self.state.ended = True
                return await self._result_at_point(new_events=[], terminal=True)
            case "exit_game":
                self._transition_to(GameStage.ENDED.value)
                self.state.ended = True
                return await self._result_at_point(new_events=[], terminal=True)
        raise new(codes.ENG_PLAYER_ACTION_INVALID, extra={"kind": kind})  # pragma: no cover

    # ===== 命令实现 =====

    async def _on_select_role(self, payload: dict) -> StepResult:
        role = str(payload.get("role_name") or "")
        playable = {c.name for c in self.script.characters if c.is_player_playable}
        if role not in playable:
            raise new(
                codes.ENG_PLAYER_ACTION_INVALID,
                extra={"role": role, "playable": sorted(playable)},
            )
        self.characters.player_role = role
        self.state.player_role = role
        self._append(evt.EVENT_SYSTEM, {"selected_role": role})
        self._transition_to(StageValue.STAGE2_REENACTING.value)
        self._log.info("stage2_start", extra={"player": role})
        return await self._drive_until_interaction()

    async def _on_enter_stage3(self) -> StepResult:
        self._transition_to(StageValue.STAGE3_EXTENDING.value)
        self._log.info("stage3_start")
        return await self._drive_until_interaction()

    async def _on_input(
        self, cid: str, *, action_type: str, payload: dict
    ) -> StepResult:
        if self.active_interaction is None:
            raise new(codes.ENG_NOT_RUNNING, extra={"reason": "no_active_interaction"})

        option_raw = payload.get("option_id")
        option_val: int | None = None
        if isinstance(option_raw, str) and option_raw.isdigit():
            option_val = int(option_raw)
        elif isinstance(option_raw, int):
            option_val = option_raw

        action = PlayerAction(
            type=action_type,
            option_id=option_val,
            text=payload.get("text"),
        )
        self._append(
            evt.EVENT_PLAYER_ACTION,
            {"type": action.type, "text": action.text, "option_id": action.option_id},
        )
        self.active_interaction = None

        current_stage = self._runtime_stage_alias()

        # Stage2 结局确认出口（design_interaction 到结局时提供 0=续写 / 1=结束）
        reached_ending = (
            current_stage == "stage2"
            and self.state.beat_cursor >= total_beats(self.script)
        )
        if reached_ending and action_type == "choose_option":
            self._log.info("ending_choice", extra={"choice": action.option_id})
            if action.option_id == 1:
                self._transition_to(GameStage.ENDED.value)
                self.state.ended = True
                return await self._result_at_point(new_events=[], terminal=True)
            self._transition_to(StageValue.STAGE2_COMPLETE.value)
            return await self._result_at_point(new_events=[])

        await self._collect_reactions(action, current_stage)
        await self._flush_events()

        if self.state.stage == StageValue.STAGE3_EXTENDING.value:
            self.state.stage3_round_taken += 1
            if self.state.stage3_round_taken >= self.config.stage3_rounds:
                self._transition_to(GameStage.ENDED.value)
                self.state.ended = True
                return await self._result_at_point(new_events=[], terminal=True)
        elif self.state.stage == StageValue.STAGE2_REENACTING.value:
            pass

        return await self._drive_until_interaction()

    def _runtime_stage_alias(self) -> str:
        if self.state.stage == StageValue.STAGE2_REENACTING.value:
            return "stage2"
        if self.state.stage == StageValue.STAGE3_EXTENDING.value:
            return "stage3"
        raise new(codes.ENG_INVALID_TRANSITION, extra={"stage": self.state.stage})

    # ===== 推进引擎：跑到下一个稳定交互点 =====

    async def _drive_until_interaction(
        self, *, new_events: list[dict] | None = None
    ) -> StepResult:
        sink: list[dict] = new_events if new_events is not None else []

        while True:
            self._mark_memories()
            stage_name = self._runtime_stage_alias()
            await self._run_cycle_head(stage_name, sink)

            reached_ending = (
                stage_name == "stage2"
                and self.state.beat_cursor >= total_beats(self.script)
            )
            interaction = self.screenwriter.design_interaction(
                stage=stage_name,
                proposals=self._valid_proposals,
                reached_ending=reached_ending,
            )
            self.state.phase = InteractionPhase.PLAYER_TURN.value
            self.state_machine.enter_phase(InteractionPhase.PLAYER_TURN)
            self.active_interaction = interaction
            return await self._result_at_point(new_events=sink)

    async def _run_cycle_head(self, stage: str, sink: list[dict]) -> None:
        self.state.phase = InteractionPhase.NARRATIVE.value
        adv = self.screenwriter.advance_plot(self.script, stage)
        # 进度游标显式同步：state 是权威，screenwriter 游标是派生
        self.state.beat_cursor = self.screenwriter.beat_index
        self._append(
            evt.EVENT_PLOT_ADVANCEMENT,
            {"summary": adv.summary, "scene": adv.scene_description},
            sink=sink,
        )
        self.state.plot_log.append(adv.summary)
        self.characters.broadcast_plot_context(adv.summary)

        self.state.phase = InteractionPhase.DIRECTION.value
        direction = self.screenwriter.confirm_direction(self.script, stage)
        self._append(
            evt.EVENT_DIRECTION,
            {"conflict": direction.conflict, "context": direction.context},
            sink=sink,
        )
        self.characters.broadcast_direction(
            {"conflict": direction.conflict, "context": direction.context}
        )

        proposals = await self._collect_proposals(stage, sink)
        self._valid_proposals = await self._verify_proposals(proposals, stage, sink)

    # ===== Agent 调度 =====

    async def _collect_proposals(
        self, stage: str, sink: list[dict]
    ) -> list[Proposal]:
        names = self.characters.active_names()

        async def _one(name: str) -> Proposal:
            return await self.characters.get(name).propose_action(stage)

        results = await asyncio.gather(
            *[_one(n) for n in names], return_exceptions=True
        )
        proposals: list[Proposal] = []
        for name, res in zip(names, results):
            if isinstance(res, BaseException):
                self._log.error(
                    "propose_failed",
                    extra={"wj_extra": {"name": name, "err": str(res)}},
                )
                continue
            self._append(
                evt.EVENT_PROPOSAL,
                {"proposed_by": name, "description": res.description},
                sink=sink,
            )
            proposals.append(res)
        return proposals

    async def _verify_proposals(
        self, proposals: list[Proposal], stage: str, sink: list[dict]
    ) -> list[Proposal]:
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
                    self._log.error(
                        "verify_failed", extra={"proposal": prop.proposal_id}
                    )
                    valid.append(prop)  # 降级收录
                    continue
                self._append(
                    evt.EVENT_VERIFICATION,
                    {
                        "proposal_id": prop.proposal_id,
                        "verdict": res.verdict,
                        "score": res.score,
                    },
                    sink=sink,
                )
                if res.verdict == "reject" and attempts_left > 0:
                    revised = self.characters.get(prop.proposed_by).revise_proposal(
                        res.rejections[0].suggestion if res.rejections else None
                    )
                    still_pending.append(revised)
                elif res.verdict != "reject":
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
                self._log.error(
                    "react_failed",
                    extra={"wj_extra": {"name": name, "err": str(res)}},
                )
                continue
            self._append(evt.EVENT_CHARACTER_SPEECH, {"speaker": name, "text": res})

    # ===== 回溯（保留旧历史；分支语义由 #8 扩展）=====

    async def rollback(self, *, command_id: str, target_event_id: int) -> StepResult:
        key = str(command_id)
        cached = self._processed_commands.get(key)
        if cached is not None:
            return StepResult(
                state=cached.state,
                new_events=[],
                active_interaction=cached.active_interaction,
                allowed_commands=list(cached.allowed_commands),
                terminal=cached.terminal,
                duplicate=True,
            )

        steps_limit = self.config.max_rollback_steps
        latest = self.event_store.latest_event_id
        steps = latest - int(target_event_id)
        if steps <= 0 or steps > steps_limit:
            raise new(
                codes.ENG_ROLLBACK_OVERFLOW,
                extra={"steps": steps, "max_steps": steps_limit},
            )
        if target_event_id < 1:
            raise new(
                codes.ENG_ROLLBACK_TARGET_MISSING,
                extra={"event_id": target_event_id},
            )
        active_ids = {e.event_id for e in self.event_store.active_events()}
        if target_event_id not in active_ids:
            raise new(
                codes.ENG_ROLLBACK_TARGET_MISSING,
                extra={"event_id": target_event_id},
            )

        _, snap, mark_beat = 0, {}, 0
        for mark_event_id, m_snap, m_beat in reversed(self._memory_marks):
            if mark_event_id <= target_event_id:
                snap, mark_beat = m_snap, m_beat
                break
        if snap:
            self.characters.restore_memories(snap)
            self.state.beat_cursor = min(mark_beat, self.state.beat_cursor)
        self.screenwriter.beat_index = self.state.beat_cursor

        # 回溯：旧事件保留，创建新活动分支并从目标节点继承历史
        superseded = self.event_store.rollback_to(
            target_event_id, session_id=self.session_id, command_id=command_id
        )
        roll_ev = self._append(
            evt.EVENT_ROLLBACK,
            {
                "steps": steps,
                "target": target_event_id,
                "superseded": len(superseded),
                "branch_id": self.event_store.active_branch_id,
            },
        )
        self.active_interaction = None
        # 回溯后从恢复点重新推进到下一个稳定交互点（新分支继续追加）
        driven = await self._drive_until_interaction(new_events=[roll_ev])
        self._processed_commands[key] = driven
        self._log.info(
            "rollback_done",
            extra={
                "steps": steps,
                "target": target_event_id,
                "new_branch_id": self.event_store.active_branch_id,
            },
        )
        return driven

    # ===== 内部工具 =====

    def _append(
        self, event_type: str, payload: dict, *, sink: list[dict] | None = None
    ) -> dict:
        ev = self.event_store.append(
            event_type, payload, session_id=self.session_id
        )
        entry = {"event_id": ev.event_id, "event_type": event_type}
        self._command_events.append(entry)
        if sink is not None:
            sink.append(entry)
        return entry

    def _mark_memories(self) -> None:
        self._memory_marks.append(
            (
                self.event_store.latest_event_id,
                self.characters.snapshot_memories(),
                self.state.beat_cursor,
            )
        )

    def _transition_to(self, stage_value: str) -> None:
        stage = GameStage(stage_value)
        self.state_machine.set_stage(stage)
        self.state.stage = stage_value
        self._append(evt.EVENT_STAGE_TRANSITION, {"stage": stage_value})
        self._log.info("stage_transition", extra={"stage": stage_value})

    async def _result_at_point(
        self, *, new_events: list[dict], terminal: bool = False
    ) -> StepResult:
        await self._flush_events()
        if terminal:
            # 终局后不得残留交互点（否则投影会把过期交互发给前端）
            self.active_interaction = None
        return StepResult(
            state=self.export_state(),
            new_events=list(self._command_events),
            active_interaction=_interaction_payload(self.active_interaction),
            allowed_commands=sorted(
                _ALLOWED_BY_STAGE[self.state.stage]
            ),
            terminal=terminal,
        )

    async def _flush_events(self) -> None:
        if self._on_flush is not None:
            await self._on_flush()
