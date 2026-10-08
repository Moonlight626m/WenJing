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
from app.contracts.script import AssetRef
from app.domain.game.game_runtime import StepResult
from app.domain.game.media import AssetKind, AssetStatus
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
    "asset_ready": EventType.ASSET_READY,
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
    session_id: uuid.UUID,
    store: PersistentEventStore,
    export: dict[str, Any],
    *,
    path: list[Any] | None = None,
) -> RuntimeState:
    """export_state → 契约 RuntimeState。

    `path` 允许调用方传入已算好的活动分支事件（`project_update` 复用同一次遍历），
    否则每次调用都要重走一遍 `branch_path`（血缘分支数 × 事件数）。
    """
    if path is None:
        path = store.active_events()
    current_asset = export.get("current_asset")
    return RuntimeState(
        session_id=session_id,
        branch_id=branch_uuid(session_id, store.active_branch_id),
        last_sequence=max(0, len(path) - 1),
        stage=StageValue(export["stage"]),
        phase=export.get("phase"),
        scene_id=_scene_id_from_key(export.get("scene_key")),
        scene_key=export.get("scene_key"),
        scene_title=export.get("scene_title"),
        beat_cursor=export.get("beat_cursor"),
        plot_context={
            "plot_log": list(export.get("plot_log", [])),
            "player_role": export.get("player_role"),
        },
        # 引擎已解析的背景稳定引用（#53）：投影只透传，URL 由鉴权端点签发
        current_asset=(
            AssetRef.model_validate(current_asset) if current_asset else None
        ),
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


def _scene_id_from_key(scene_key: str | None) -> int | None:
    """`scene:{id}` → id；运行期单调键（非脚本场景）返回 None。"""
    if scene_key and scene_key.startswith("scene:"):
        rest = scene_key.split(":", 1)[1]
        if rest.isdigit():
            return int(rest)
    return None


def project_update(
    session_id: uuid.UUID,
    store: PersistentEventStore,
    result: StepResult,
) -> RuntimeUpdate:
    """StepResult → 契约 RuntimeUpdate（new_events 映射为确定性 UUID 引用）。"""
    # 活动分支事件只遍历一次：投影消息与状态都复用同一 path（此前每次命令走三遍）
    path = store.active_events()
    order = {e.event_id: i for i, e in enumerate(path)}
    refs: list[DomainEventRef] = []
    for entry in result.new_events:
        local_id = int(entry["event_id"])
        pos = order.get(local_id)
        ev = path[pos] if pos is not None else None
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
        state=project_state(session_id, store, result.state, path=path),
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
    # 运行期配图就绪（#56）：命令外事件路径的唯一对外出口——不列这里，
    # asset_ready 事件会被静默丢弃，前端永远等不到背景替换。
    "asset_ready": "asset_ready",
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
        if category == "asset_ready":
            # 配图就绪（#56）：与 narrative 消息同形携带 current_asset，
            # 前端复用同一套「按 AssetRef 换背景」逻辑，不另立字段语义。
            # 缺省 kind/status 取自 media 的枚举（不另立第三份字面量副本），
            # 与 `domain/game/assets.py::derive_scene_assets` 同一约定。
            payload["scene_key"] = p.get("scene_key")
            payload["current_asset"] = {
                "asset_id": p.get("asset_id"),
                "kind": p.get("kind") or AssetKind.BACKGROUND.value,
                "status": p.get("status") or AssetStatus.READY.value,
            }
        elif category == "character_speech":
            payload["speaker"] = p.get("speaker")
            payload["text"] = str(p.get("text", ""))
        elif category == "narrative":
            payload["text"] = str(p.get("summary", ""))
            # 场景切换信息（#53）：前端据此更新背景/场景标题。
            # current_asset 也随事件下发——实时跨场景时不必等重连的 session_init
            if p.get("scene_key"):
                payload["scene_key"] = p["scene_key"]
            if p.get("scene_title"):
                payload["scene_title"] = p["scene_title"]
            if p.get("current_asset") is not None:
                payload["current_asset"] = p["current_asset"]
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
