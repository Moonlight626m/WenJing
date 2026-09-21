"""会话层契约投影（#5 竖切接缝③）。

引擎内部形状（StepResult / export_state / 内存 int 分支与事件 id）到对外冻结契约
（RuntimeState / RuntimeUpdate / SessionStatusResponse）的显式映射。
禁止把引擎内部对象直接发给前端（contracts-first 决策）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.contracts.dto import SessionStatusResponse
from app.contracts.enums import EventType, InteractionMode, StageValue
from app.contracts.runtime import (
    ActiveInteraction,
    DomainEventRef,
    OptionItem,
    RuntimeState,
    RuntimeUpdate,
)
from app.domain.game.game_runtime import StepResult
from app.infrastructure.db.event_store import PersistentEventStore, branch_uuid, event_uuid

# 内存事件类型 → 契约 EventType
_EVENT_TYPE_MAP: dict[str, EventType] = {
    "stage_transition": EventType.STAGE_TRANSITIONED,
    "plot_advancement": EventType.NARRATIVE_ADVANCED,
    "direction": EventType.NARRATIVE_ADVANCED,
    "proposal": EventType.PROPOSALS_GENERATED,
    "verification": EventType.PROPOSALS_VERIFIED,
    "player_action": EventType.PLAYER_ACTION_RECORDED,
    "character_speech": EventType.AGENT_REACTIONS_DONE,
    "rollback": EventType.ROLLBACK_EXECUTED,
}


def _contract_event_type(event_type: str, payload: dict[str, Any]) -> EventType:
    if event_type == "system":
        return EventType.ROLE_SELECTED if "selected_role" in payload else EventType.SESSION_STARTED
    return _EVENT_TYPE_MAP.get(event_type, EventType.NARRATIVE_ADVANCED)


def _flatten_memory(snapshot: dict[str, Any]) -> list[str]:
    """CharacterMemory.snapshot(dict) → 契约 dict[str, list[str]] 投影。"""
    out = [str(x) for x in snapshot.get("personal_log", [])]
    for entry in snapshot.get("working_memory", []):
        if isinstance(entry, dict):
            out.append(f"{entry.get('role', '')}：{entry.get('content', '')}")
        else:
            out.append(str(entry))
    return out


def project_interaction(
    ix: dict[str, Any] | None, *, latest_event_id: int
) -> ActiveInteraction | None:
    """引擎交互点 payload → 契约 ActiveInteraction。"""
    if not ix:
        return None
    return ActiveInteraction(
        interaction_id=f"ix-{latest_event_id}",
        mode=InteractionMode(ix["mode"]),
        prompt=str(ix.get("context", "")),
        options=[
            OptionItem(option_id=str(o.get("id")), label=str(o.get("text", "")))
            for o in ix.get("options", [])
        ],
        hint=str(ix.get("hint", "") or ""),
    )


def project_state(
    session_id: uuid.UUID, store: PersistentEventStore, export: dict[str, Any]
) -> RuntimeState:
    """export_state → 契约 RuntimeState。"""
    path = store.active_events()
    return RuntimeState(
        session_id=session_id,
        branch_id=branch_uuid(session_id, store.active_branch_id),
        last_sequence=max(0, len(path) - 1),
        stage=StageValue(export["stage"]),
        phase=export.get("phase"),
        scene_id=None,
        beat_cursor=export.get("beat_cursor"),
        plot_context={
            "plot_log": list(export.get("plot_log", [])),
            "player_role": export.get("player_role"),
        },
        character_memories={
            name: _flatten_memory(mem)
            for name, mem in (export.get("character_memories") or {}).items()
        },
        active_interaction=project_interaction(
            export.get("active_interaction"),
            latest_event_id=int(export.get("latest_event_id", 0)),
        ),
        stage3_goals=[],
    )


def project_update(
    session_id: uuid.UUID,
    store: PersistentEventStore,
    result: StepResult,
) -> RuntimeUpdate:
    """StepResult → 契约 RuntimeUpdate（new_events 映射为确定性 UUID 引用）。"""
    path_ids = {e.event_id: e for e in store.active_events()}
    order = {e.event_id: i for i, e in enumerate(store.active_events())}
    refs: list[DomainEventRef] = []
    for entry in result.new_events:
        local_id = int(entry["event_id"])
        ev = path_ids.get(local_id)
        payload = ev.payload if ev else (entry.get("payload") or {})
        refs.append(
            DomainEventRef(
                event_id=event_uuid(session_id, store.active_branch_id, local_id),
                sequence=order.get(local_id, 0),
                event_type=_contract_event_type(entry["event_type"], payload),
            )
        )
    return RuntimeUpdate(
        session_id=session_id,
        branch_id=branch_uuid(session_id, store.active_branch_id),
        state=project_state(session_id, store, result.state),
        new_events=refs,
        terminal=result.terminal,
        emitted_event_types=sorted({r.event_type for r in refs}, key=lambda t: t.value),
    )


# ===== WS 消息投影（issue #5：事件流 → 前端消息）=====

# 事件类型 → 消息类别；未列入的事件（verification/player_action）不对用户展示
_MESSAGE_CATEGORY_MAP: dict[str, str] = {
    "plot_advancement": "narrative",
    "character_speech": "character_speech",
    "stage_transition": "system",
    "system": "system",
    "rollback": "system",
    "proposal": "system",
    "direction": "system",
}
_SILENT_EVENTS = frozenset({"verification", "player_action"})


def _system_text(event_type: str, p: dict[str, Any]) -> str:
    if event_type == "stage_transition":
        return f"进入阶段：{p.get('stage', '')}"
    if event_type == "system" and "selected_role" in p:
        return f"你将扮演：{p['selected_role']}"
    if event_type == "rollback":
        return f"已回溯到事件 #{p.get('target')}"
    if event_type == "proposal":
        return f"{p.get('proposed_by')} 提议：{p.get('description', '')}"
    if event_type == "direction":
        return str(p.get("conflict", ""))
    return event_type


def project_messages(
    session_id: uuid.UUID,
    store: Any,
    *,
    after_seq: int = -1,
    interaction: ActiveInteraction | None = None,
    allowed_commands: list[str] | None = None,
) -> list[dict[str, Any]]:
    """活动分支事件流 → 按序 WS 消息（seq = 分支路径序号）。

    `after_seq` 之后的消息用于断线重连补发；`interaction` 追加为最后一条。
    """
    msgs: list[dict[str, Any]] = []
    for seq, ev in enumerate(store.active_events()):
        if seq <= after_seq or ev.event_type in _SILENT_EVENTS:
            continue
        category = _MESSAGE_CATEGORY_MAP.get(ev.event_type)
        if category is None:
            continue
        p = ev.payload or {}
        payload: dict[str, Any] = {"category": category}
        if category == "character_speech":
            payload["speaker"] = p.get("speaker")
            payload["text"] = str(p.get("text", ""))
        elif category == "narrative":
            payload["text"] = str(p.get("summary", ""))
        else:
            payload["text"] = _system_text(ev.event_type, p)
        msgs.append({"type": category, "seq": seq, "payload": payload})
    if interaction is not None:
        msgs.append(
            {
                "type": "interaction",
                "seq": len(store.active_events()),
                "payload": {
                    "category": "interaction",
                    "interaction": interaction.model_dump(mode="json"),
                    "allowed_commands": allowed_commands or [],
                },
            }
        )
    return msgs


def messages_from_update(
    session_id: uuid.UUID, store: Any, update: RuntimeUpdate
) -> list[dict[str, Any]]:
    """一次命令推进 → 本批应发布的消息（仅新事件 + 交互点/终态）。"""
    new_seqs = {ref.sequence for ref in update.new_events}
    msgs = [m for m in project_messages(session_id, store) if m["seq"] in new_seqs]
    ix = update.state.active_interaction
    if ix is not None:
        msgs.append(
            {
                "type": "interaction",
                "seq": update.state.last_sequence,
                "payload": {
                    "category": "interaction",
                    "interaction": ix.model_dump(mode="json"),
                    "allowed_commands": [k.value for k in update.state.allowed_commands()],
                },
            }
        )
    elif update.terminal:
        msgs.append(
            {
                "type": "system",
                "seq": update.state.last_sequence,
                "payload": {"category": "system", "text": "本局演绎已结束"},
            }
        )
    return msgs


def project_status(
    *,
    session_id: uuid.UUID,
    stage: str,
    active_branch_id: uuid.UUID,
    head_event_id: int | None,
    playable_roles: list[str],
    selected_role: str | None,
) -> SessionStatusResponse:
    """会话行 + 运行时摘要 → SessionStatusResponse。"""
    return SessionStatusResponse(
        session_id=session_id,
        stage=stage,
        active_branch_id=active_branch_id,
        head_sequence=head_event_id or 0,
        playable_roles=playable_roles,
        selected_role=selected_role,
    )
