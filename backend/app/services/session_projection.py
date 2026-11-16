"""会话层契约投影（#5 竖切接缝③）。

引擎内部形状（StepResult / export_state / 内存 int 分支与事件 id）到对外冻结契约
（RuntimeState / RuntimeUpdate / SessionStatusResponse）的显式映射。
禁止把引擎内部对象直接发给前端（contracts-first 决策）。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from app.contracts.dto import (
    BranchSummary,
    SavePoint,
    SessionStatusResponse,
    SessionTimelineResponse,
    TimelineEntry,
)
from app.contracts.enums import (
    CommandKind,
    EventType,
    InteractionMode,
    MessageCategory,
    StageValue,
)
from app.contracts.runtime import (
    ActiveInteraction,
    DomainEventRef,
    OptionItem,
    RuntimeState,
    RuntimeUpdate,
    SceneOptionItem,
    Stage3Goal,
)
from app.contracts.script import AssetRef
from app.domain.game.assets import RuntimeAssets, derive_scene_assets
from app.domain.game.beat_text import split_goal_note
from app.domain.game.event import (
    EVENT_CHARACTER_CREATED,
    EVENT_EXPLORATION_SETTLE,
    EVENT_INTERVENTION_REJECTED,
    EVENT_INTERVENTION_REQUESTED,
    EVENT_OFFLINE_HINT,
    EVENT_PLAYER_ACTION,
    EVENT_PROPOSAL,
    EVENT_PULL_IN_CHARACTER,
    EVENT_REPLAY_CHOICE,
    EVENT_REPLAY_ENDING_REACHED,
    EVENT_REPLAY_NARRATION,
    EVENT_REPLAY_NODE_ENTERED,
    EVENT_ROLLBACK,
    EVENT_SCENE_CREATED,
    EVENT_SCENE_SWITCH,
    EVENT_STAGE3_GOAL_ACHIEVED,
    EVENT_STAGE3_GOALS_SET,
    EVENT_WORLD_CHRONICLE,
    EVENT_WORLD_FACT,
    GameEvent,
)
from app.domain.game.game_runtime import StepResult
from app.domain.game.goals import GoalState, apply_goal_event
from app.domain.game.media import AssetKind, AssetStatus
from app.infrastructure.db.event_store import PersistentEventStore, branch_uuid, event_uuid
from app.infrastructure.models.snapshot import Snapshot as SnapshotRecord
from app.services.command_labels import ACTION_COMMAND_LABELS
from app.services.session_store import snapshot_sequence_on_path

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
    "stage3_goals_set": EventType.STAGE3_GOALS_SET,
    "stage3_goal_achieved": EventType.STAGE3_GOAL_ACHIEVED,
}


def _contract_event_type(event_type: str, payload: dict[str, Any]) -> EventType:
    if event_type == "system":
        return EventType.ROLE_SELECTED if "selected_role" in payload else EventType.SESSION_STARTED
    mapped = _EVENT_TYPE_MAP.get(event_type)
    if mapped is not None:
        return mapped
    # 新事件（replay_* / scene_* / intervention_* 等）与契约 EventType 值 1:1：
    # 直接按值构造，避免每加一个事件就要在这张表里补一行、漏了会静默降级成叙事。
    try:
        return EventType(event_type)
    except ValueError:
        return EventType.NARRATIVE_ADVANCED


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
    ix: dict[str, Any] | None,
    *,
    latest_event_id: int,
    scene_options: list[dict[str, Any]] | None = None,
) -> ActiveInteraction | None:
    """引擎交互点 payload → 契约 ActiveInteraction。"""
    if not ix:
        return None
    return ActiveInteraction(
        interaction_id=f"ix-{latest_event_id}",
        mode=InteractionMode(ix["mode"]),
        prompt=str(ix.get("context", "")),
        options=[
            OptionItem(
                option_id=str(o.get("id")),
                label=str(o.get("text", "")),
                proposed_by=_proposer(o.get("proposed_by")),
            )
            for o in ix.get("options", [])
        ],
        hint=str(ix.get("hint", "") or ""),
        scene_options=[SceneOptionItem(**item) for item in (scene_options or [])],
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
            scene_options=export.get("scene_options"),
        ),
        stage3_goals=project_goals(export.get("stage3_goals") or []),
    )


def _scene_id_from_key(scene_key: str | None) -> int | None:
    """`scene:{id}` → id；运行期单调键（非脚本场景）返回 None。"""
    if scene_key and scene_key.startswith("scene:"):
        rest = scene_key.split(":", 1)[1]
        if rest.isdigit():
            return int(rest)
    return None


def _proposer(raw: Any) -> str | None:
    """引擎选项的 proposed_by → 契约字段：系统选项（"system"）与缺省都投成 None。"""
    if not isinstance(raw, str) or not raw or raw == "system":
        return None
    return raw


def project_goals(goals: list[dict[str, Any]] | list[GoalState]) -> list[Stage3Goal]:
    """引擎导出的续写目标（dict 或 GoalState）→ 契约 Stage3Goal。"""
    out: list[Stage3Goal] = []
    for g in goals:
        data = g.to_dict() if isinstance(g, GoalState) else g
        out.append(
            Stage3Goal(
                goal_id=int(data["goal_id"]),
                description=str(data.get("description", "")),
                achieved=bool(data.get("achieved", False)),
            )
        )
    return out


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
    # 珊瑚图纯 IO 播放（M4）：节点进入与旁白是叙事，选择与结局是系统提示
    EVENT_REPLAY_NODE_ENTERED: "narrative",
    EVENT_REPLAY_NARRATION: "narrative",
    EVENT_REPLAY_CHOICE: "system",
    EVENT_REPLAY_ENDING_REACHED: "system",
    # Stage3 确定性探索（M5）：结算摘要与换景都进叙事流——换景必须带 scene 字段，
    # 前端只在 narrative 消息上应用 scene_key/title/背景（system 消息不换景）
    EVENT_EXPLORATION_SETTLE: "narrative",
    EVENT_SCENE_SWITCH: "narrative",
    # 续写目标：定下与达成都以系统消息出现在消息流里，payload 另带一份目标快照
    "stage3_goals_set": "system",
    "stage3_goal_achieved": "system",
    # 玩家干涉世界（M6 §B5）：请求/拒绝/生效全部是系统消息，玩家能看到后果；
    # 动态场景与角色由事件派生，消息文本只做摘要（结构以事件为准）
    EVENT_INTERVENTION_REQUESTED: "system",
    EVENT_INTERVENTION_REJECTED: "system",
    EVENT_SCENE_CREATED: "system",
    EVENT_CHARACTER_CREATED: "system",
    EVENT_PULL_IN_CHARACTER: "system",
    # 世界事实（M6 §B6）：public 进公屏；private 只进 audience 角色视图，
    # 投影层在下方显式过滤（本层无 viewer，不能当普通 system 广播）
    EVENT_WORLD_FACT: "system",
    # 离线 tick 提示（M7 §B6）：一条系统消息指路时间线，不写详细摘要
    EVENT_OFFLINE_HINT: "system",
    # 运行期配图就绪（#56）：命令外事件路径的唯一对外出口——不列这里，
    # asset_ready 事件会被静默丢弃，前端永远等不到背景替换。
    "asset_ready": "asset_ready",
}
_SILENT_EVENTS = frozenset(
    {"verification", "player_action", EVENT_WORLD_CHRONICLE}
)


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
    if event_type == EVENT_REPLAY_CHOICE:
        return f"你选择了：{p.get('label', '')}"
    if event_type == EVENT_REPLAY_ENDING_REACHED:
        return f"到达结局：{p.get('title', '')}"
    if event_type == EVENT_STAGE3_GOALS_SET:
        descs = [str(g.get("description", "")) for g in p.get("goals", []) if isinstance(g, dict)]
        return "续写目标：" + "；".join(descs)
    if event_type == EVENT_STAGE3_GOAL_ACHIEVED:
        return f"达成续写目标：{p.get('description', '')}"
    if event_type == EVENT_INTERVENTION_REQUESTED:
        return f"你的干涉：{p.get('text', '')}"
    if event_type == EVENT_INTERVENTION_REJECTED:
        return f"世界构建没有应允：{p.get('reason', '')}"
    if event_type == EVENT_SCENE_CREATED:
        return f"新地点「{p.get('title', '')}」出现了，可在「前往」里选它。"
    if event_type == EVENT_CHARACTER_CREATED:
        return f"新角色「{p.get('name', '')}」登场：{p.get('public_background', '')}"
    if event_type == EVENT_PULL_IN_CHARACTER:
        reason = str(p.get("reason", "") or "")
        if reason:
            return f"「{p.get('name', '')}」来到了现场：{reason}"
        return f"「{p.get('name', '')}」来到了现场。"
    if event_type == EVENT_WORLD_FACT:
        return str(p.get("text", ""))
    if event_type == EVENT_OFFLINE_HINT:
        return str(p.get("text", ""))
    return event_type


def _is_private_fact(event_type: str, p: dict[str, Any]) -> bool:
    """私密世界事实不得进公屏/时间线（§B6 机制层知识边界）。"""
    return event_type == EVENT_WORLD_FACT and p.get("visibility") == "private"


def _event_text(event_type: str, p: dict[str, Any], category: str) -> str:
    """事件 → 用户可见文本（WS 消息与回溯页共用这套拼写，过滤/去重各自处理）。"""
    if event_type == "replay_node_entered":
        prefix = "分支" if p.get("node_kind") == "branch" else "场景"
        return f"{prefix}：{p.get('scene_title', '')}"
    if event_type == EVENT_SCENE_SWITCH:
        present = "、".join(str(n) for n in p.get("participants", []) if n)
        suffix = f"（在场：{present}）" if present else ""
        return f"你来到了「{p.get('scene_title', '')}」{suffix}"
    if category == "narrative":
        text = str(p.get("summary") or p.get("text") or "")
        if event_type == EVENT_REPLAY_NARRATION:
            # 历史事件里存的是 v3 时代的旁白（把「目标：…」注记也带上了），
            # 读取侧兜底：断线重连/回溯看到的历史消息同样是干净的
            text = split_goal_note(text)[0]
        return text
    if category == "character_speech":
        return str(p.get("text", ""))
    return _system_text(event_type, p)


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
    # 续写目标随事件顺序折叠：补发从中间开始时，快照也是那一刻的真实状态
    goals: list[GoalState] = []
    for seq, ev in enumerate(store.active_events()):
        goals = apply_goal_event(goals, ev.event_type, ev.payload or {})
        if seq <= after_seq or ev.event_type in _SILENT_EVENTS:
            continue
        if _is_private_fact(ev.event_type, ev.payload or {}):
            continue
        category = _MESSAGE_CATEGORY_MAP.get(ev.event_type)
        if category is None:
            continue
        p = ev.payload or {}
        # 消息类型随 payload 下发：前端据此区分离线提示、世界事实、干涉结果等
        # 系统消息；WS 的 payload 是自由 dict，不动契约版本。
        payload: dict[str, Any] = {"category": category, "event_type": ev.event_type}
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
            payload["text"] = _event_text(ev.event_type, p, category)
            if p.get("stage_direction"):
                payload["stage_direction"] = str(p["stage_direction"])
        elif category == "narrative":
            text = _event_text(ev.event_type, p, category)
            if not text:
                # 存量包里有整条都是作者注记的旁白：没有可播的内容
                continue
            payload["text"] = text
            # 场景切换信息（#53）：前端据此更新背景/场景标题。
            # current_asset 也随事件下发——实时跨场景时不必等重连的 session_init
            if p.get("scene_key"):
                payload["scene_key"] = p["scene_key"]
            if p.get("scene_title"):
                payload["scene_title"] = p["scene_title"]
            if p.get("current_asset") is not None:
                payload["current_asset"] = p["current_asset"]
        else:
            payload["text"] = _event_text(ev.event_type, p, category)
        if ev.event_type == "stage_transition" and p.get("stage"):
            # 结构化阶段标记：前端据此判断「是否进入过续写」，不靠解析中文文案
            payload["stage"] = p["stage"]
        # 目标变化与回溯都带一份完整目标快照：前端直接替换，回溯到续写之前也会清空
        if ev.event_type in (EVENT_STAGE3_GOALS_SET, EVENT_STAGE3_GOAL_ACHIEVED, EVENT_ROLLBACK):
            payload["stage3_goals"] = [g.model_dump(mode="json") for g in project_goals(goals)]
        # 结构化字段（M6/M8 前端增补）：运行期角色、干涉结果、重演结局。
        # 都是 payload 加法，不改变消息类别与 seq。
        if ev.event_type == EVENT_CHARACTER_CREATED:
            payload["character"] = {
                "name": p.get("name"),
                "public_background": p.get("public_background", ""),
                "personality_traits": [str(t) for t in p.get("personality_traits", [])],
                "location_key": p.get("location_key"),
                "origin": p.get("origin"),
                "avatar_brief": p.get("avatar_brief", ""),
            }
        elif ev.event_type == EVENT_PULL_IN_CHARACTER:
            payload["character"] = {"name": p.get("name")}
        elif ev.event_type == EVENT_INTERVENTION_REQUESTED:
            payload["intervention"] = {"status": "requested", "text": p.get("text", "")}
        elif ev.event_type == EVENT_INTERVENTION_REJECTED:
            payload["intervention"] = {"status": "rejected", "reason": p.get("reason", "")}
        elif ev.event_type == EVENT_REPLAY_ENDING_REACHED:
            payload["ending"] = {
                "ending_id": p.get("ending_id"),
                "title": p.get("title", ""),
                "description": p.get("description", ""),
                "kind": p.get("kind", "canonical"),
            }
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


def _stage_from_path(path: Sequence[GameEvent], fallback: str) -> str:
    """分支时间线 → 该分支尾部的阶段（旧分支只读视图用，别拿活动分支的阶段充数）。"""
    stage = fallback
    for ev in path:
        if ev.event_type == "stage_transition":
            value = (ev.payload or {}).get("stage")
            if value:
                stage = str(value)
    return stage


#: 回溯页叙事去重窗口：同一场景最近 N 条叙事内比较，避免跨幕误杀。
_NARRATION_WINDOW = 5
#: 字符二元组 Jaccard 阈值；实测重复旁白 ≥0.41，正常相邻旁白 <0.35。
_NARRATION_SIMILARITY = 0.4
_NARRATION_NOISE = frozenset("，。；：、“”‘’！？!?.,;:「」『』（）()—- \t\n\r")


def _normalize_narration(text: str) -> str:
    return "".join(ch for ch in text if ch not in _NARRATION_NOISE)


def _narration_grams(text: str) -> set[str]:
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _is_repeated_narration(text: str, recent_normalized: Sequence[str]) -> bool:
    """与同场景前几条回放旁白重复（包含关系或高二元组重合）。

    Stage2 回放会为 beat 描述和 `speaker=null` 的旁白台词各发一条
    `replay_narration`，模型又把后者写成前者的近似复述；这里保留先到的
    beat 描述，丢掉后到的复述。`recent_normalized` 须是归一化后的文本。
    """
    normalized = _normalize_narration(text)
    if not normalized:
        return False
    grams = _narration_grams(normalized)
    for other in recent_normalized:
        if normalized in other or other in normalized:
            # 短句被长句包含时要求长度接近，避免「夜深了」吞掉一整段叙事
            shortest, longest = sorted((len(normalized), len(other)))
            if shortest / longest >= 0.5:
                return True
            continue
        other_grams = _narration_grams(other)
        if not grams or not other_grams:
            continue
        overlap = len(grams & other_grams) / len(grams | other_grams)
        if overlap >= _NARRATION_SIMILARITY:
            return True
    return False


def _snapshot_action_label(path: Sequence[GameEvent], sequence: int) -> str | None:
    """快照附近最近一次玩家动作文本，供存档点标签使用。

    存档点的入参只有命令与场景，`choose_option` 每回合都落一个，标签会全变成
    「选择 · 同一场景」；动作文本才区分得开。历史快照也走这里，不必回填。
    干涉不写 `player_action`，取 `intervention_requested.text`。
    """
    for index in range(min(sequence, len(path) - 1), -1, -1):
        event = path[index]
        if event.event_type not in (EVENT_PLAYER_ACTION, EVENT_INTERVENTION_REQUESTED):
            continue
        text = str((event.payload or {}).get("text") or "").strip()
        return text[:40] or None
    return None


def project_timeline(
    session_id: uuid.UUID,
    store: Any,
    *,
    stage: StageValue | str,
    allowed_commands: list[str],
    max_rollback_steps: int,
    snapshots: Sequence[SnapshotRecord] = (),
    branch_int: int | None = None,
) -> SessionTimelineResponse:
    """分支事件流 → 回溯页进度（与 WS 消息同源，回溯页额外降噪）。

    `branch_int` 为空时取活动分支；给了别的分支就是**只读**视图（回溯/放弃后
    的旧进度仍可审计，但不能从旧分支继续玩）。只遍历分支时间线：剧本包里
    **尚未发生**的场景永远不会出现。场景图与标题按事件流累积——`plot_advancement`
    携带当时的场景上下文，`asset_ready` 到达后替换为该场景的图。

    只有叙事节拍可作回溯目标：回溯按 beat 游标恢复，目标落在台词或系统提示上
    会让「回到哪一幕」不可预期。

    降噪（2026-11-14）：`proposal` 是内部意图、`offline_hint` 由游戏内横幅承担，
    都不进时间线；同一离线 tick 的 `world_fact` 合成一条；Stage2 回放里近似复述
    beat 描述的旁白按相似度丢弃（保留先到的 beat 描述）。
    """
    path = (
        store.active_events()
        if branch_int is None
        else store.branch_path(branch_int)
    )
    read_only = branch_int is not None and branch_int != store.active_branch_id
    latest = path[-1].event_id if path else 0
    # 旧分支的「当前阶段」得从它自己的事件流取：活动运行时说的是活动分支的阶段
    branch_stage = str(stage.value if isinstance(stage, StageValue) else stage)
    if read_only:
        branch_stage = _stage_from_path(path, branch_stage)
    # 事件索引优先、剧本槽位兜底（AGENTS.md：RuntimeAssets.rebuild 是资产索引的
    # 指定入口）——`plot_advancement` 的 current_asset 是生成期离线预生成的槽位，
    # 运行期 asset_ready 才算在事件索引里。旧分支只读视图要按**它自己**的路径
    # 重建：活动分支的配图不能出现在被放弃的时间线上。
    runtime_assets = (
        RuntimeAssets(by_scene=derive_scene_assets(path))
        if read_only
        else RuntimeAssets.rebuild(store)
    )
    entries: list[TimelineEntry] = []
    scene_key: str | None = None
    scene_title: str | None = None
    plot_asset: AssetRef | None = None
    recent_narratives: list[str] = []
    recent_scene: str | None = None
    fact_entries: dict[str, TimelineEntry] = {}
    for seq, ev in enumerate(path):
        p = ev.payload or {}
        # 私密世界事实不进时间线：回溯页与公屏同一条过滤口径
        if _is_private_fact(ev.event_type, p):
            continue
        # 提议是内部意图，真正发生的是 world_fact；离线提示交给游戏内横幅，
        # 时间线不再重复（每次重连都会追加一条，文案还一样）。
        if ev.event_type in (EVENT_PROPOSAL, EVENT_OFFLINE_HINT):
            continue
        if ev.event_type in (
            "plot_advancement",
            EVENT_REPLAY_NODE_ENTERED,
            EVENT_EXPLORATION_SETTLE,
            EVENT_SCENE_SWITCH,
        ):
            next_key = p.get("scene_key")
            if next_key and next_key != scene_key:
                # 换场必须清掉上一场的图：新场还没有图时（current_asset 为空），
                # 沿用它会把上一幕的画面配到这一幕上。
                plot_asset = None
            scene_key = next_key or scene_key
            scene_title = p.get("scene_title") or scene_title
            if p.get("current_asset") is not None:
                plot_asset = AssetRef.model_validate(p["current_asset"])
        if ev.event_type in _SILENT_EVENTS:
            continue
        category = _MESSAGE_CATEGORY_MAP.get(ev.event_type)
        if category not in ("narrative", "character_speech", "system"):
            continue
        scened = category != "system"
        speaker = p.get("speaker") if category == "character_speech" else None
        steps = latest - ev.event_id
        entry = TimelineEntry(
            sequence=seq,
            event_id=event_uuid(session_id, ev.branch_id, ev.event_id),
            branch_id=branch_uuid(session_id, ev.branch_id),
            kind=MessageCategory(category),
            text=_event_text(ev.event_type, p, category),
            speaker=str(speaker) if speaker else None,
            scene_key=scene_key if scened else None,
            scene_title=scene_title if scened else None,
            current_asset=(
                (runtime_assets.current(scene_key) or plot_asset)
                if scened
                else None
            ),
            rollbackable=(
                not read_only
                and category == "narrative"
                and 0 < steps <= max_rollback_steps
            ),
        )
        if category == "narrative":
            if not entry.text.strip():
                # 整条都是作者注记、剥完为空：既不该展示，也不能进去重窗口
                # （空串是任何字符串的子串，会把同场景后续叙事全吞掉）。
                continue
            if ev.event_type != EVENT_REPLAY_NARRATION:
                entries.append(entry)
                continue
            if scene_key != recent_scene:
                recent_narratives.clear()
                recent_scene = scene_key
            if _is_repeated_narration(entry.text, recent_narratives):
                continue
            recent_narratives.append(_normalize_narration(entry.text))
            if len(recent_narratives) > _NARRATION_WINDOW:
                del recent_narratives[0]
        elif ev.event_type == EVENT_WORLD_FACT and p.get("tick_id"):
            # 一个离线 tick 的多个 NPC 行动合成一条，避免同一段缺席时间刷屏。
            tick_id = str(p["tick_id"])
            existing = fact_entries.get(tick_id)
            if existing is not None:
                existing.text = f"{existing.text}；{entry.text}"
                continue
            fact_entries[tick_id] = entry
        entries.append(entry)
    branch_of = {
        branch_uuid(session_id, meta.branch_id): meta.branch_id
        for meta in store.branches
    }
    save_points: list[SavePoint] = []
    for row in snapshots:
        ev_branch = branch_of.get(row.branch_id)
        if ev_branch is None:
            continue
        # 坐标必须在这次展示的路径上：父分支被放弃的那截历史不算存档点
        sequence = snapshot_sequence_on_path(row, path)
        if sequence is None:
            continue
        event = path[sequence]
        label = row.label or "存档点"
        kind = row.kind or "command"
        # 选择/行动/换景/干涉的存档点用动作文本区分；历史快照也在这里现算。
        word = label.split(" · ", 1)[0]
        if kind == "command" and word in ACTION_COMMAND_LABELS:
            action = _snapshot_action_label(path, sequence)
            if action:
                label = f"{word}：{action}"
        save_points.append(
            SavePoint(
                branch_id=branch_uuid(session_id, ev_branch),
                sequence=sequence,
                event_id=event_uuid(session_id, event.branch_id, event.event_id),
                label=label,
                kind=kind,
                created_at=row.created_at,
            )
        )
    branch_summaries: list[BranchSummary] = []
    for meta in store.branches:
        branch_summaries.append(
            BranchSummary(
                branch_id=branch_uuid(session_id, meta.branch_id),
                is_active=meta.branch_id == store.active_branch_id,
                event_count=len(store.branch_path(meta.branch_id)),
            )
        )
    return SessionTimelineResponse(
        session_id=session_id,
        stage=branch_stage,
        head_sequence=max(0, len(path) - 1),
        can_rollback=(
            not read_only
            and CommandKind.ROLLBACK_TO_EVENT.value in allowed_commands
            and any(e.rollbackable for e in entries)
        ),
        branch_id=branch_uuid(
            session_id,
            store.active_branch_id if branch_int is None else branch_int,
        ),
        read_only=read_only,
        save_points=sorted(save_points, key=lambda p: p.sequence)[-20:],
        branches=branch_summaries,
        entries=entries,
    )


def _interaction_tail(update: RuntimeUpdate) -> list[dict[str, Any]]:
    """命令批次的尾部：新交互点或终态提示（都带 seq）。"""
    ix = update.state.active_interaction
    if ix is not None:
        return [
            {
                "type": "interaction",
                "seq": update.state.last_sequence,
                "payload": {
                    "category": "interaction",
                    "interaction": ix.model_dump(mode="json"),
                    "allowed_commands": [k.value for k in update.state.allowed_commands()],
                },
            }
        ]
    if update.terminal:
        return [
            {
                "type": "system",
                "seq": update.state.last_sequence,
                "payload": {"category": "system", "text": "本局演绎已结束"},
            }
        ]
    return []


def messages_from_update(
    session_id: uuid.UUID, store: Any, update: RuntimeUpdate
) -> list[dict[str, Any]]:
    """一次命令推进 → 本批应发布的消息（仅新事件 + 交互点/终态）。

    回溯是例外：它重写了活动分支，只发新事件会让客户端清空旧时间线后丢掉
    继承前缀（回溯目标之前的剧情）。此时先发一条 `timeline_reset` 控制消息，
    再整段重放新分支的活动事件——客户端清空本地时间线后按顺序重建。
    """
    tail = _interaction_tail(update)
    if any(ref.event_type is EventType.ROLLBACK_EXECUTED for ref in update.new_events):
        reset = {
            "type": "timeline_reset",
            "seq": update.state.last_sequence,
            "payload": {
                "branch_id": str(update.state.branch_id),
                "stage": update.state.stage,
            },
        }
        return [reset, *project_messages(session_id, store), *tail]
    new_seqs = {ref.sequence for ref in update.new_events}
    msgs = [m for m in project_messages(session_id, store) if m["seq"] in new_seqs]
    return [*msgs, *tail]


def project_status(
    *,
    session_id: uuid.UUID,
    stage: str,
    active_branch_id: uuid.UUID,
    head_sequence: int,
    playable_roles: list[str],
    selected_role: str | None,
) -> SessionStatusResponse:
    """会话行 + 运行时摘要 → SessionStatusResponse。

    `head_sequence` 是**分支内**进度序号（`sessions.head_sequence`），与 WS 消息的
    `seq`、回溯坐标同口径；不要拿全局事件行 id 充数。
    """
    return SessionStatusResponse(
        session_id=session_id,
        stage=stage,
        active_branch_id=active_branch_id,
        head_sequence=max(0, int(head_sequence)),
        playable_roles=playable_roles,
        selected_role=selected_role,
    )
