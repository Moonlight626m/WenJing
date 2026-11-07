"""GameRuntime：可恢复的 command/step 游戏运行时（issue #7 / 取代长驻 run）。

语义：
- `start()` 初始化会话（剧本在构造时注入），停在选角点。
- `submit(...)` 是唯一输入入口；每次提交从当前稳定交互点推进到下一个
  稳定交互点或终态，返回 StepResult（#5 Session 层映射为契约 RuntimeUpdate）。
- `rollback(...)` 回退保留旧历史事件（新分支继承前缀，目标拍重演）。
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
from app.contracts.script import AssetRef, ExplorationMap
from app.domain.agents.character import CharacterAgentManager
from app.domain.agents.director import DirectorAgent
from app.domain.agents.producer import (
    KIND_ADD_CHARACTER,
    KIND_CREATE_SCENE,
    KIND_PULL_IN_CHARACTER,
    InterventionIntent,
    ProducerAgent,
)
from app.domain.agents.screenwriter import ScreenwriterAgent, total_beats
from app.domain.agents.verifier import VerifierAgent
from app.domain.game import event as evt
from app.domain.game.assets import RuntimeAssets
from app.domain.game.engine_config import EngineConfig
from app.domain.game.event import EventStore
from app.domain.game.exploration import (
    SCENE_KEY_PREFIX,
    ExplorationDirector,
    ExplorationProgress,
    WorldState,
    build_location_registry,
    derive_world,
    location_scene_key,
)
from app.domain.game.goals import GoalState, derive_goals
from app.domain.game.media import scene_visual_description
from app.domain.game.offline_ticks import npc_action_fact
from app.domain.game.replay import ReplayCue, ReplayDirector, ReplayGraph, ReplayState
from app.domain.game.state_machine import GameStage, GameStateMachine, InteractionPhase
from app.domain.game.streaming import SpeechStreamSink
from app.domain.game.types import (
    CharacterSetting,
    InteractionPoint,
    PlayerAction,
    Proposal,
    Scene,
    SceneAssetIntent,
    Script,
)
from app.domain.game.world_view import RuntimeWorldView
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

# 干涉预算（design §B5）：每会话新场景 ≤3、新角色 ≤2；每轮 ≤1 次由事件判定。
MAX_DYNAMIC_SCENES = 3
MAX_NEW_CHARACTERS = 2


def _setting_from_payload(payload: dict) -> CharacterSetting:
    """`character_created` 事件载荷 → 角色 Agent 的设定（新角色无知识边界）。"""
    return CharacterSetting(
        name=str(payload.get("name", "")),
        public_background=str(payload.get("public_background", "")),
        personality_traits=[str(t) for t in payload.get("personality_traits", [])],
        speech_style=str(payload.get("speech_style", "")),
        knows=[str(k) for k in payload.get("knows", [])],
        not_knows=[str(k) for k in payload.get("not_knows", [])],
        is_player_playable=False,
    )


@dataclass
class _RState:
    """显式、可序列化的运行时状态（进度游标等全部在此，无隐藏字段）。"""

    stage: str = StageValue.INIT.value
    phase: str | None = None
    player_role: str | None = None
    beat_cursor: int = 0
    stage3_round_taken: int = 0
    plot_log: list[str] = field(default_factory=list)
    # 公开发言台账（机制层知识边界）：(speaker, scene_key, 摘要)。只知道
    # 「谁在哪个场景说了什么」——per-character 世界视图据此答题
    # 「我在场时听到了谁的话」，未公开/不在场的一切不进任何角色的输入。
    # 快照与重放的对账来源同 timeline：export_state 存元组列表，
    # character_speech 事件重放时重建。
    speech_log: list[tuple[str, str | None, str]] = field(default_factory=list)
    # 当前矛盾/关键处境（D5 方向确认产物；供角色 Agent 的 view_current_direction 工具）
    direction: dict[str, str] = field(default_factory=dict)
    # 当前场景稳定键（#53 / ADR-0005 §8）：脚本场景 `scene:{scene_id}`。
    # 进显式状态与 plot_advancement payload——否则重连/重放会丢背景。
    scene_key: str | None = None
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
    # 运行期配图请求（#56）：引擎只**发起意图**，不自己生成——Session 层在命令
    # 事务提交后把它绑上 session/branch 派给后台任务（ADR-0005 §5：后台任务
    # 不得持有 GameRuntime）。
    asset_requests: list[SceneAssetIntent] = field(default_factory=list)


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
        speech_sink: SpeechStreamSink | None = None,
        replay_graph: ReplayGraph | None = None,
        exploration_map: ExplorationMap | None = None,
    ) -> None:
        self.session_id = session_id
        self.script = script
        self.config = config or EngineConfig()
        # 注意：EventStore 定义了 __len__（空存储为 falsy），必须显式判 None，
        # 否则 `event_store or EventStore()` 会静默丢弃空 PersistentEventStore
        self.event_store: EventStore = event_store if event_store is not None else EventStore()
        self._on_flush = on_flush
        # 流式字幕出口（#60）：None = 不发流式（HTTP 命令路径、离线重放、测试）。
        # 运行时实例按命令重建，故把"发到哪条连接"挂在这里是安全的。
        self._speech_sink = speech_sink
        self._log = log or logging.getLogger("wenjing.core.runtime")

        self.state_machine = GameStateMachine()
        self.state = _RState()
        self.active_interaction: InteractionPoint | None = None

        # 角色 Agent 经只读 WorldView 按需查询世界进度（ADR-0004）；
        # 视图惰性读取 self.state，故可在状态初始化后、开始推进前构造。
        self.world_view = RuntimeWorldView(self)
        self.screenwriter = ScreenwriterAgent(llm)
        self.verifier = VerifierAgent(llm)
        # 工作人员（M6）：只设计选项/解析干涉，不出场、不写台词
        self.director = DirectorAgent(llm)
        self.producer = ProducerAgent(llm)
        self.characters = CharacterAgentManager(llm, self.world_view)
        self.characters.create_agents(script.characters)
        # 珊瑚图纯 IO 播放（M4）：有图就走确定性路径，不建 agent、不调 LLM
        self.replay = ReplayDirector(replay_graph) if replay_graph is not None else None
        self._replay_state: ReplayState | None = None
        # Stage3 确定性探索（M5）：无地图（旧剧本）时保持原 3 轮行为
        registry = build_location_registry(exploration_map)
        self.exploration = ExplorationDirector(registry) if registry is not None else None
        self._exploration_progress: ExplorationProgress | None = (
            self.exploration.start_progress() if self.exploration is not None else None
        )
        # 运行期世界（M6）：动态场景/新角色/拉人/世界事实，全部由事件派生
        self._world = WorldState()
        # 本轮导演设计的选项（M6）；空 = 回退到已验证提议/默认项
        self._director_options: list[str] = []
        self._processed_commands: dict[str, StepResult] = {}
        # 本次命令追加的全部事件（#5：WS 实时消息投影的完整来源）
        self._command_events: list[dict] = []
        # 本次命令产生的运行期配图请求（#56，见 StepResult.asset_requests）
        self._asset_requests: list[SceneAssetIntent] = []
        self._valid_proposals: list[Proposal] = []

    # ===== 显式状态导出 / 恢复 =====

    def _asset_at(self, scene_key: str | None) -> AssetRef | None:
        """事件索引里的场景资产（`RuntimeAssets.rebuild` 的唯一调用点）。"""
        if not scene_key:
            return None
        return RuntimeAssets.rebuild(self.event_store).current(scene_key)

    def _asset_json(self, scene_key: str | None) -> dict | None:
        asset = self._asset_at(scene_key)
        return asset.model_dump(mode="json") if asset is not None else None

    def _current_background(
        self, scene: Scene | None, node_asset: AssetRef | None = None
    ) -> AssetRef | None:
        """当前场景的背景稳定引用：**事件索引优先，脚本槽位兜底**。

        ADR-0005 §9：事件是资产继承的唯一权威——运行期 `asset_ready` 写下的资产
        必须压过剧本槽位，否则续写阶段的实时配图永远显示不出来；槽位兜底覆盖
        Stage2 的离线预生成资产（那时还没有 asset_ready 事件）。`node_asset` 是
        珊瑚图播放节点的槽位（分支过场用 `scene:{id}::branch:{bid}`，游标解析
        不到）。在引擎内解析（ADR-0005 §8）：这里同时有 events 与 script，
        投影层保持纯函数。未开播（游标 0）或该场景无图 → None。
        """
        ref = self._asset_at(self.state.scene_key)
        if ref is not None:
            return ref
        if node_asset is not None:
            return node_asset
        return scene.background_asset if scene is not None else None

    def _beat_ctx(self, cursor: int) -> Scene | None:
        """beat 游标 → 当前场景；尚未开播（cursor<=0）/空剧本返回 None。

        **游标是「下一个待播 beat」，不是「当前 beat」**（`ScreenwriterAgent.advance_plot`
        先读 `beat_index` 播报、再 `beat_index += 1`），所以刚播完的那拍是
        `cursor - 1`——场景切换/背景解析必须用它，否则会提前跳到下一场景。
        游标 0 表示一拍未播，此时没有「当前场景」（`scene_key` 也尚未写入），
        返回 None 以免出现「有背景但无场景键」的字段互斥。
        """
        total = total_beats(self.script)
        if total == 0 or cursor <= 0:
            return None
        idx = min(cursor - 1, total - 1)
        count = 0
        for scene in self.script.scenes:
            for _beat in scene.beats:
                if count == idx:
                    return scene
                count += 1
        return None

    def _scene_by_key(self, scene_key: str) -> Scene | None:
        """场景稳定键（`scene:{scene_id}`）→ 场景设定；解析不到返回 None。"""
        if not scene_key.startswith("scene:"):
            return None
        try:
            scene_id = int(scene_key[len("scene:") :])
        except ValueError:
            return None
        return next((s for s in self.script.scenes if s.scene_id == scene_id), None)

    def export_state(self) -> dict:
        s = self.state
        # 当前场景只解析一次（#53）：背景与标题同源，且都在热路径上
        scene = self._beat_ctx(s.beat_cursor)
        node_asset = (
            self.replay.background_of(self._replay_state)
            if self.replay is not None and self._replay_state is not None
            else None
        )
        current_asset = self._current_background(scene, node_asset)
        scene_title = scene.title if scene is not None else None
        if self.replay is not None and self._replay_state is not None:
            # 珊瑚图播放不推 beat 游标（§A4）：标题从播放位置解析
            scene_title = self.replay.title_of(self._replay_state) or scene_title
        if self.exploration is not None and self._exploration_progress is not None:
            location = self.exploration.location(
                self._exploration_progress.current_location_key, self._world
            )
            if location is not None:
                scene_title = location.title
        return {
            "stage": s.stage,
            "phase": s.phase,
            "player_role": s.player_role,
            "beat_cursor": s.beat_cursor,
            "stage3_round_taken": s.stage3_round_taken,
            "plot_log": list(s.plot_log),
            "speech_log": [list(t) for t in s.speech_log],
            "direction": dict(s.direction),
            "scene_key": s.scene_key,
            "scene_title": scene_title,
            "ended": s.ended,
            "character_memories": self.characters.snapshot_memories(),
            "latest_event_id": self.event_store.latest_event_id,
            "active_branch_id": self.event_store.active_branch_id,
            "active_interaction": _interaction_payload(self.active_interaction),
            # Stage3 换景列表（M5）：只在探索地图存在且已进入续写时给出
            "scene_options": self._scene_options(),
            # 当前背景稳定引用在导出时解析（#53）：快照/投影都从这里拿
            "current_asset": (
                current_asset.model_dump(mode="json") if current_asset is not None else None
            ),
            # 续写目标从活动分支事件派生（见 goals.py），restore 不读它
            "stage3_goals": [g.to_dict() for g in self._stage3_goals()],
        }

    def _stage3_goals(self) -> list[GoalState]:
        return derive_goals(self.event_store.active_events())

    def restore(self, state_dump: dict) -> None:
        """从显式状态快照重建运行时（快照 + 重放前缀；记忆由事件折叠）。"""
        s = self.state
        s.stage = state_dump.get("stage", StageValue.INIT.value)
        s.phase = state_dump.get("phase")
        s.player_role = state_dump.get("player_role")
        s.beat_cursor = int(state_dump.get("beat_cursor", 0))
        s.stage3_round_taken = int(state_dump.get("stage3_round_taken", 0))
        s.plot_log = list(state_dump.get("plot_log", []))
        s.speech_log = [tuple(entry) for entry in state_dump.get("speech_log", [])]
        s.direction = dict(state_dump.get("direction") or {})
        s.scene_key = state_dump.get("scene_key")
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

    def replay_from(self, snapshot_state: dict | None, events: list[dict]) -> None:
        """快照 + 事件重放重建运行时（issue #8 验收标准 1）。

        快照提供记忆基线（character_memories/beat_cursor/plot_log/stage），
        随后按事件顺序重放确定性的状态迁移：
        - stage_transition → stage / ended
        - plot_advancement → beat_cursor+1、plot_log 追加、剧情上下文广播
        - direction → 角色处境上下文广播
        - system(selected_role) → player_role
        - player_action（Stage3）→ stage3_round_taken+1
        - proposal / character_speech → 角色记忆折叠（见 `derive_memories`）

        事件形如 `GameEvent.to_dict()`（含 event_type + payload）。快照里的
        `character_memories` 只是兼容缓存：每次重放**额外**折叠进个人记忆。
        快照损坏/缺失时用 `replay_from(None, store.active_events())` 完整重建——
        必须传**活动分支**事件；全量历史里的被放弃分支会被一并折回。
        """
        # 运行期世界先于快照/记忆恢复：快照的 `character_memories` 可能含
        # 动态角色的条目，agent 必须已经在 manager 里（否则恢复 KeyError）
        if self.exploration is not None:
            self._world = derive_world(self.event_store.active_events())
            self._sync_world_characters()
        if snapshot_state is not None:
            self.restore(snapshot_state)
            # 记忆折叠只作用于基线之后的事件：快照缓存已含此前的个人记忆，
            # 对全量事件再折叠会双计（快照位于 head 时折叠为空，天然兼容）
            memory_base_event_id = int(
                snapshot_state.get("latest_event_id", 0) or 0
            )
        else:
            self.state = _RState()
            self.screenwriter.beat_index = 0
            self.active_interaction = None
            # 原地清空（保持对象身份）：工具闭包持有 memory 引用，换对象会让
            # view_my_memory 读到旧记忆
            self.characters.clear_memories()
            memory_base_event_id = 0
            # 被回溯到创建之前的动态角色：「从未存在」——事件是唯一权威
            if self.exploration is not None:
                self._sync_world_characters()

        for ev in events:
            self._replay_event(ev)
        # 角色记忆由事件重建（M0：快照记忆只是兼容缓存）——与实时写入同构
        # （proposal→personal_log/rejected、character_speech→working_memory）
        self.characters.derive_memories(
            ev
            for ev in events
            if int(ev.get("event_id", 0) or 0) > memory_base_event_id
        )

        # 使 state_machine / screenwriter 与重放结果一致
        self.state_machine.restore({"stage": self.state.stage, "phase": self.state.phase})
        self.screenwriter.beat_index = self.state.beat_cursor
        if self.state.player_role:
            self.characters.player_role = self.state.player_role
        if self.replay is not None:
            # 播放位置从**活动分支**事件折叠（快照不含它；只折重放切片会漏前缀）
            self._replay_state = self.replay.resolve(self.event_store.active_events())
        if self.exploration is not None:
            self._exploration_progress = self.exploration.progress(
                self.event_store.active_events()
            )
            if self.state.stage == StageValue.STAGE3_EXTENDING.value:
                # 回溯到第一次 settle 之前时，前缀里没有 settle/switch，
                # scene_key 还停在 Stage2 的场景上；按地点进度纠正。
                self._sync_exploration_scene_key()

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
            # 场景键重建（#53）：plot_advancement payload 携带 scene_key，
            # 重连/重放据此恢复当前场景（背景随 export_state 按游标解析）
            scene_key = payload.get("scene_key")
            if isinstance(scene_key, str):
                self.state.scene_key = scene_key
        elif etype == evt.EVENT_DIRECTION:
            direction = {
                "conflict": payload.get("conflict", ""),
                "context": payload.get("context", ""),
            }
            self.state.direction = direction
            self.characters.broadcast_direction(direction)
        elif etype == evt.EVENT_SYSTEM:
            role = payload.get("selected_role")
            if role:
                self.state.player_role = role
                self.characters.player_role = role
        elif etype == evt.EVENT_PLAYER_ACTION:
            # 换景不消耗续写回合预算（与实时 `_on_switch_scene` 同口径，
            # 否则回溯重放后轮次会凭空多一拍、提前收束）
            if (
                self.state.stage == StageValue.STAGE3_EXTENDING.value
                and payload.get("type") != "switch_scene"
            ):
                self.state.stage3_round_taken += 1
        elif etype == evt.EVENT_CHARACTER_SPEECH:
            # 公开发言台账重放（机制层知识边界）：重连/回溯后「谁在哪个场景说了
            # 什么」据此重建；speaker 与当前 scene_key 是事件自带/状态现有的。
            speaker = payload.get("speaker")
            if speaker:
                self.state.speech_log.append(
                    (str(speaker), self.state.scene_key, str(payload.get("text", "")))
                )
        elif etype == evt.EVENT_REPLAY_NODE_ENTERED:
            scene_key = payload.get("scene_key")
            if isinstance(scene_key, str):
                self.state.scene_key = scene_key
        elif etype == evt.EVENT_REPLAY_NARRATION:
            # 旁白进入剧情上下文：续写目标/角色视图靠它了解演到哪了
            text = str(payload.get("text", ""))
            if text:
                self.state.plot_log.append(text)
                self.characters.broadcast_plot_context(text)
        elif etype == evt.EVENT_REPLAY_ENDING_REACHED:
            summary = f"结局：{payload.get('title', '')}".rstrip("：")
            self.state.plot_log.append(summary)
            self.characters.broadcast_plot_context(summary)
            # 游标对齐末尾：无快照恢复时 Stage3 也从结局之后续写，而非从头复读
            self.state.beat_cursor = total_beats(self.script)
        elif etype == evt.EVENT_EXPLORATION_SETTLE:
            self._apply_settle_event(payload)
        elif etype == evt.EVENT_SCENE_SWITCH:
            self._apply_switch_event(payload)
        elif etype in (
            evt.EVENT_SCENE_CREATED,
            evt.EVENT_CHARACTER_CREATED,
            evt.EVENT_PULL_IN_CHARACTER,
            evt.EVENT_WORLD_FACT,
        ):
            # 运行期世界（M6）增量折叠：事件是唯一权威，实时/重放同一入口
            self._refresh_world()

    def _apply_settle_event(self, payload: dict) -> None:
        """`exploration_settle` 折叠：地点进度 + 场景键 + 剧情/处境（幂等）。"""
        key = payload.get("location_key")
        if isinstance(key, str):
            self._move_exploration(key)
        scene_key = payload.get("scene_key")
        if isinstance(scene_key, str):
            self.state.scene_key = scene_key
        summary = str(payload.get("summary", ""))
        if summary:
            self.state.plot_log.append(summary)
            self.characters.broadcast_plot_context(summary)
        conflict = str(payload.get("conflict", "") or "")
        context = str(payload.get("context", "") or "")
        if conflict or context:
            direction = {"conflict": conflict, "context": context}
            self.state.direction = direction
            self.characters.broadcast_direction(direction)

    def _apply_switch_event(self, payload: dict) -> None:
        """`scene_switch` 折叠：换景是前进式，不回溯事件分支。"""
        key = payload.get("to")
        if not isinstance(key, str):
            return
        self._move_exploration(key)
        scene_key = payload.get("scene_key")
        if isinstance(scene_key, str):
            self.state.scene_key = scene_key
        title = str(payload.get("scene_title") or key)
        summary = f"来到「{title}」"
        self.state.plot_log.append(summary)
        self.characters.broadcast_plot_context(summary)

    def _move_exploration(self, location_key: str) -> None:
        if self.exploration is None or self._exploration_progress is None:
            return
        if self.exploration.location(location_key, self._world) is None:
            return
        visited = self._exploration_progress.visited
        if location_key not in visited:
            visited = (*visited, location_key)
        self._exploration_progress = ExplorationProgress(
            current_location_key=location_key, visited=visited
        )

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
                # 不转发 asset_requests：幂等重放不重跑调度（同进程内 `_attempted`
                # 也拦得住），第二次以后由后续命令重新从事件派生意图。
            )
        result = await self._dispatch(key, kind, payload or {})
        self._processed_commands[key] = result
        return result

    async def _dispatch(self, cid: str, kind: str, payload: dict[str, Any]) -> StepResult:
        self._command_events = []
        self._asset_requests = []
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
                if self._at_replay_decision():
                    return await self._on_replay_choice(cid, payload)
                return await self._on_input(cid, action_type="choose_option", payload=payload)
            case "free_input":
                return await self._on_input(cid, action_type="speak", payload=payload)
            case "rollback_to_event":
                target = int(payload.get("target_event_id", 0))
                return await self.rollback(command_id=cid, target_event_id=target)
            case "switch_scene":
                return await self._on_switch_scene(cid, payload)
            case "intervene":
                return await self._on_intervene(cid, payload)
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
        await self._set_stage3_goals()
        return await self._drive_until_interaction()

    async def _set_stage3_goals(self) -> None:
        """进入续写时定下小目标并写成事件。本分支已有目标（不应发生）就不重定。"""
        if self._stage3_goals():
            return
        descriptions = await self.screenwriter.design_stage3_goals(
            self.script,
            player_role=self.state.player_role,
            plot_log=self.state.plot_log,
        )
        self._append(
            evt.EVENT_STAGE3_GOALS_SET,
            {
                "goals": [
                    {"goal_id": i, "description": d}
                    for i, d in enumerate(descriptions, start=1)
                ]
            },
        )

    async def _judge_stage3_goals(
        self, action_text: str, reactions: list[tuple[str, str]]
    ) -> list[GoalState]:
        """这一轮之后判定目标达成，每个新达成的目标写一条事件；返回判定后的目标。"""
        goals = self._stage3_goals()
        if not goals or all(g.achieved for g in goals):
            return goals
        achieved, reason = await self.verifier.judge_stage3_goals(
            goals,
            player_role=self.state.player_role,
            action=action_text,
            reactions=reactions,
        )
        by_id = {g.goal_id: g for g in goals}
        for gid in achieved:
            self._append(
                evt.EVENT_STAGE3_GOAL_ACHIEVED,
                {"goal_id": gid, "description": by_id[gid].description, "reason": reason},
            )
        if achieved:
            self._log.info("stage3_goal_achieved", extra={"goal_ids": achieved})
        return self._stage3_goals()

    async def _on_input(self, cid: str, *, action_type: str, payload: dict) -> StepResult:
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
        # 续写目标判定要知道学生做了什么：选项只带编号，先趁交互点还在把文字取出来
        action_text = action.text or next(
            (
                str(o.get("text", ""))
                for o in self.active_interaction.options
                if o.get("id") == option_val
            ),
            "",
        )
        self._append(
            evt.EVENT_PLAYER_ACTION,
            {"type": action.type, "text": action.text, "option_id": action.option_id},
        )
        self.active_interaction = None

        current_stage = self._runtime_stage_alias()

        # Stage2 结局确认出口（design_interaction 到结局时提供 0=续写 / 1=结束）
        reached_ending = current_stage == "stage2" and self._reached_ending()
        if reached_ending and action_type == "choose_option":
            self._log.info("ending_choice", extra={"choice": action.option_id})
            if action.option_id == 1:
                self._transition_to(GameStage.ENDED.value)
                self.state.ended = True
                return await self._result_at_point(new_events=[], terminal=True)
            self._transition_to(StageValue.STAGE2_COMPLETE.value)
            return await self._result_at_point(new_events=[])

        # Stage3 探索：先确定性结算（地点化摘要/处境），再只让**在场** NPC 回应
        present_names: list[str] | None = None
        if current_stage == "stage3" and self.exploration is not None:
            present_names = list(self._exploration_present())
            self._settle_stage3(action_text)
        reactions = await self._collect_reactions(action, current_stage, names=present_names)
        await self._flush_events()

        if self.state.stage == StageValue.STAGE3_EXTENDING.value:
            goals = await self._judge_stage3_goals(action_text, reactions)
            self.state.stage3_round_taken += 1
            # 目标导向收敛：目标全部达成即收束；轮次上限兜底（目标判不出来时也能结束）
            converged = bool(goals) and all(g.achieved for g in goals)
            if converged or self.state.stage3_round_taken >= self.config.stage3_rounds:
                self._log.info(
                    "stage3_end",
                    extra={"converged": converged, "rounds": self.state.stage3_round_taken},
                )
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

    # ===== 珊瑚图纯 IO 播放（M4；design play-through-redesign §A4）=====

    def _at_replay_decision(self) -> bool:
        """当前交互点是不是珊瑚图决策点（结局后的 0/1 出口不算）。"""
        return (
            self.replay is not None
            and self.state.stage == StageValue.STAGE2_REENACTING.value
            and self._replay_state is not None
            and self._replay_state.ending_id is None
        )

    def _reached_ending(self) -> bool:
        if self.replay is not None:
            return (
                self._replay_state is not None
                and self._replay_state.ending_id is not None
            )
        return self.state.beat_cursor >= total_beats(self.script)

    async def _on_replay_choice(self, cid: str, payload: dict) -> StepResult:
        """珊瑚图决策点：校验选项 → 写事件 → 播到下一个决策点/结局。"""
        assert self.replay is not None and self._replay_state is not None  # noqa: S101
        option_id = str(payload.get("option_id") or "")
        option = self.replay.find_option(self._replay_state, option_id)
        if option is None:
            raise new(
                codes.ENG_PLAYER_ACTION_INVALID,
                extra={"option_id": option_id, "node": self._replay_state.node_id},
            )
        # 珊瑚图选项 id 是字符串（o1…），与旧路径的数字选项不同；事件只作审计
        self._append(
            evt.EVENT_PLAYER_ACTION,
            {"type": "choose_option", "option_id": option_id, "text": option.label},
        )
        self.active_interaction = None
        state, cues = self.replay.choose(
            self._replay_state, option_id, self.state.player_role
        )
        self._log.info(
            "replay_choice",
            extra={"option_id": option_id, "node": self._replay_state.node_id},
        )
        return await self._apply_replay_advance(state, cues)

    async def _drive_replay(
        self, new_events: list[dict] | None = None, *, force_node_id: str | None = None
    ) -> StepResult:
        """珊瑚图推进：从开局/指定节点播到下一个稳定决策点或结局。"""
        assert self.replay is not None  # noqa: S101
        sink: list[dict] = new_events if new_events is not None else []
        self.state.phase = InteractionPhase.NARRATIVE.value
        if force_node_id is not None:
            state, cues = self.replay.enter(force_node_id, self.state.player_role)
        elif self._replay_state is None:
            state, cues = self.replay.start(self.state.player_role)
        else:
            state, cues = self._replay_state, []
        return await self._apply_replay_advance(state, cues, sink=sink)

    async def _apply_replay_advance(
        self, state: ReplayState, cues: list[ReplayCue], *, sink: list[dict] | None = None
    ) -> StepResult:
        assert self.replay is not None  # noqa: S101
        for cue in cues:
            self._append(cue.event_type, cue.payload, sink=sink)
            # 与 `replay_from` 同构：实时推进也走同一折叠，避免 `_RState`
            # （导出/快照的来源）要等下一次重建才对齐。
            self._replay_event({"event_type": cue.event_type, "payload": cue.payload})
        # 预写台词也进 NPC 工作记忆（与实时写入同一函数，防漂移）
        self.characters.derive_memories(
            {"event_type": cue.event_type, "payload": cue.payload} for cue in cues
        )
        self._replay_state = state
        self.state.scene_key = self.replay.scene_key_of(state) or self.state.scene_key
        if state.ending_id is not None:
            # 到达结局：游标对齐到末尾（旧投影/前端按它判断「已演完」）
            self.state.beat_cursor = total_beats(self.script)
            self.active_interaction = self.replay.ending_interaction(state)
        else:
            self.active_interaction = self.replay.options(state)
        self.state.phase = InteractionPhase.PLAYER_TURN.value
        self.state_machine.enter_phase(InteractionPhase.PLAYER_TURN)
        return await self._result_at_point(new_events=sink or [])

    # ===== Stage3 确定性探索（M5；design play-through-redesign §B3）=====

    def _exploration_present(self) -> tuple[str, ...]:
        """在场角色 = 当前地点 participants（+ 拉入/新增）∩ 已创建角色。"""
        active = tuple(self.characters.active_names())
        if self.exploration is None or self._exploration_progress is None:
            return active
        return self.exploration.present_names(
            self._exploration_progress, active, self._world
        )

    def _scene_participants(self, scene_key: str | None) -> set[str]:
        """某场景/地点的在场角色集合（世界视图的知识边界用）。"""
        if not scene_key:
            return set()
        if scene_key.startswith("scene:"):
            scene = self._scene_by_key(scene_key)
            return set(scene.participants) if scene is not None else set()
        if scene_key.startswith(SCENE_KEY_PREFIX) and self.exploration is not None:
            location = self.exploration.resolve_scene(scene_key, self._world)
            if location is None:
                return set()
            return set(self.exploration.participants_at(location, self._world))
        return set()

    def _scene_options(self) -> list[dict]:
        """交互点的换景列表（只在探索地图 + 续写阶段给出）。"""
        if (
            self.exploration is None
            or self._exploration_progress is None
            or self.state.stage != StageValue.STAGE3_EXTENDING.value
        ):
            return []
        return self.exploration.scene_options(
            self._exploration_progress, self._world
        )

    def _request_location_asset(self, location) -> None:
        """探索地点缺图时记一次 scene_montage 意图（M6 画师接线，§B3 注记）。

        静态地点没有 Stage2 的离线槽位（`design_assets` 只覆盖剧本场景），
        所以续写里第一次到访/结算时补一次运行期配图；去重由调度器负责
        （同一 scene_key 在途/已失败会被拦下）。
        """
        if self._asset_at(location.scene_key) is not None:
            return
        self._asset_requests.append(
            SceneAssetIntent(
                scene_key=location.scene_key,
                description=location.visual_summary or f"场景：{location.title}",
                kind="scene_montage",
            )
        )

    def _settle_stage3(self, action_text: str) -> None:
        """把本轮动作结算成地点化摘要（`exploration_settle`），并同步 `_RState`。"""
        if self.exploration is None or self._exploration_progress is None:
            return
        settlement = self.exploration.settle(
            self._exploration_progress,
            action_text,
            self._exploration_present(),
            self._world,
        )
        if settlement is None:
            return
        location = self.exploration.location(
            self._exploration_progress.current_location_key, self._world
        )
        if location is not None:
            self._request_location_asset(location)
        payload = {
            "location_key": settlement.location_key,
            "scene_key": settlement.scene_key,
            "scene_title": settlement.title,
            "summary": settlement.summary,
            "conflict": settlement.conflict,
            "context": settlement.context,
            "present": list(settlement.present),
            # 地点若已有事件索引资产（早期访问/教师上传），随叙事一起下发
            "current_asset": self._asset_json(settlement.scene_key),
        }
        self._append(evt.EVENT_EXPLORATION_SETTLE, payload)
        self._apply_settle_event(payload)

    def _sync_exploration_scene_key(self) -> None:
        """让 `scene_key` 与探索进度一致（重放后/回合头兜底）。"""
        if self.exploration is None or self._exploration_progress is None:
            return
        location = self.exploration.location(
            self._exploration_progress.current_location_key, self._world
        )
        if location is not None:
            self.state.scene_key = location.scene_key

    async def _stage3_exploration_head(self, stage: str, sink: list[dict]) -> None:
        """探索回合头部：不再 advance_plot/confirm_direction。

        剧情摘要与处境由 `exploration_settle` 产出（`_on_input` 已写入）；
        NPC 提议送审后交给导演设计玩家选项（M6），失败则由交互层回退。
        """
        self._sync_exploration_scene_key()
        self.state.phase = InteractionPhase.NARRATIVE.value
        proposals = await self._collect_proposals(
            stage, sink, names=list(self._exploration_present())
        )
        self._valid_proposals = await self._verify_proposals(proposals, stage, sink)
        self._director_options = await self._design_director_options()

    async def _design_director_options(self) -> list[str]:
        """导演设计 2–4 条玩家行动；上下文由运行时装配（导演不挂工具）。"""
        if self.exploration is None or self._exploration_progress is None:
            return []
        location = self.exploration.location(
            self._exploration_progress.current_location_key, self._world
        )
        if location is None:
            return []
        present = [
            (
                name,
                self.characters.agents[name].identity.public_background
                if name in self.characters.agents
                else "",
            )
            for name in self._exploration_present()
        ]
        return await self.director.design_options(
            location_title=location.title,
            visual_summary=location.visual_summary,
            player_role=self.state.player_role,
            present=present,
            plot_log=self.state.plot_log,
            direction=self.state.direction,
            goals=[(g.description, g.achieved) for g in self._stage3_goals()],
            teaching_focus=list(self.script.teaching_focus),
        )

    def _stage3_interaction(self) -> InteractionPoint:
        """续写交互点：导演选项优先，其次已验证提议，最后给兜底行动。"""
        labels = [text for text in self._director_options if text]
        if not labels:
            labels = [p.description for p in self._valid_proposals if p.description]
        if not labels:
            labels = ["环顾四周，看看这里有什么", "离开这里，去别处看看"]
        context = self.state.direction.get("conflict") or "请选择你的行动，或自由发言"
        return InteractionPoint(
            mode="options_with_fallback",
            context=context,
            options=[
                {"id": index, "text": label} for index, label in enumerate(labels)
            ],
            hint="可自定义输入，也可以用「干涉」改变世界",
        )

    async def _on_switch_scene(self, cid: str, payload: dict) -> StepResult:
        """换景（前进式）：校验目标 → 写 `scene_switch` → 目标在场 NPC 反应。"""
        if self.exploration is None or self._exploration_progress is None:
            raise new(
                codes.ENG_PLAYER_ACTION_INVALID, extra={"reason": "no_exploration"}
            )
        if self.active_interaction is None:
            raise new(codes.ENG_NOT_RUNNING, extra={"reason": "no_active_interaction"})
        target_key = str(payload.get("scene_key") or "")
        location = self.exploration.resolve_scene(target_key, self._world)
        if location is None:
            raise new(codes.ENG_PLAYER_ACTION_INVALID, extra={"scene_key": target_key})
        previous = self._exploration_progress.current_location_key
        if location.location_key == previous:
            raise new(codes.ENG_PLAYER_ACTION_INVALID, extra={"reason": "already_there"})

        self._append(
            evt.EVENT_PLAYER_ACTION, {"type": "switch_scene", "text": location.title}
        )
        self.active_interaction = None
        # 在场 = 地点静态名单（保持原顺序）+ 运行期拉入/新增（排序保证可重放）
        extra = sorted(self._scene_participants(location.scene_key) - set(location.participants))
        switch_payload = {
            "from": previous,
            "to": location.location_key,
            "scene_key": location.scene_key,
            "scene_title": location.title,
            "participants": [*location.participants, *extra],
            # 目标地点若已有事件索引资产（此前到过/教师上传），换景即换图
            "current_asset": self._asset_json(location.scene_key),
        }
        self._append(evt.EVENT_SCENE_SWITCH, switch_payload)
        self._apply_switch_event(switch_payload)
        self._request_location_asset(location)
        # 到场反应：只有新地点的在场 NPC 说话（不广播给全场）
        action = PlayerAction(
            type="switch_scene", text=f"你走进了「{location.title}」"
        )
        await self._collect_reactions(
            action, "stage3", names=list(self._exploration_present())
        )
        await self._flush_events()
        self._log.info(
            "scene_switch", extra={"from": previous, "to": location.location_key}
        )
        return await self._drive_until_interaction()

    # ===== 玩家干涉世界（M6；design play-through-redesign §B5）=====

    async def _on_intervene(self, cid: str, payload: dict) -> StepResult:
        """玩家自然语言干涉：Producer 解析 → 确定性校验 → 事件化应用。

        与换景同构：不消耗续写回合预算、全部走事件（回溯到创建之前 =
        该场景/角色从未存在）、解析/校验失败 fail-closed 成 `intervention_rejected`。
        不写 `player_action`——那不是「推进一轮」的动作，写进去会让重放把
        一次干涉多算一拍续写回合、提前触发收束。
        """
        if self.exploration is None or self._exploration_progress is None:
            raise new(
                codes.ENG_PLAYER_ACTION_INVALID, extra={"reason": "no_exploration"}
            )
        if self.active_interaction is None:
            raise new(codes.ENG_NOT_RUNNING, extra={"reason": "no_active_interaction"})
        text = str(payload.get("text") or "").strip()
        if not text:
            raise new(codes.ENG_PLAYER_ACTION_INVALID, extra={"reason": "empty_text"})

        self._append(evt.EVENT_INTERVENTION_REQUESTED, {"text": text})
        if self._was_intervened_this_round():
            # 每轮 ≤1 次（§B5）：确定性拒绝，不调 Producer（本次请求也是审计）
            self._reject_intervention("本轮已经干涉过一次了，推进一轮后再试。")
            await self._flush_events()
            return await self._result_at_point(new_events=[])

        intent = await self.producer.parse_intervention(
            text, context=self._intervention_context()
        )
        applied = self._apply_intervention(intent)
        await self._flush_events()
        self._log.info(
            "intervention_applied",
            extra={"kind": intent.kind, "applied": applied},
        )
        if not applied:
            # 被拒绝：世界没变，保持当前交互点（不白跑一轮提议）
            return await self._result_at_point(new_events=[])
        # 干涉不推进剧情：回到交互点（选项按新世界重新设计）
        return await self._drive_until_interaction()

    def _was_intervened_this_round(self) -> bool:
        """本轮（最近一次结算/换景之后）是否已发起过干涉——每轮 ≤1 次。

        调用方在读之前刚 append 了本次 `intervention_requested`，故排除最后一条。
        """
        boundary = 0
        events = self.event_store.active_events()
        for ev in events:
            if ev.event_type in (evt.EVENT_EXPLORATION_SETTLE, evt.EVENT_SCENE_SWITCH):
                boundary = ev.event_id
        prior = [
            ev
            for ev in events
            if ev.event_type == evt.EVENT_INTERVENTION_REQUESTED and ev.event_id > boundary
        ]
        return len(prior) > 1

    def _intervention_context(self) -> dict:
        """制作人的输入装配（staff 不挂工具，design §B1）：全量世界单次打包。"""
        current = self.exploration.location(
            self._exploration_progress.current_location_key, self._world
        )
        known_locations = [
            *self.exploration.registry.ordered(),
            *self._world.dynamic_scenes.values(),
        ]
        visited_titles: list[str] = []
        for key in self._exploration_progress.visited:
            loc = self.exploration.location(key, self._world)
            visited_titles.append(loc.title if loc is not None else key)
        return {
            "location_title": current.title if current is not None else "",
            "visited_titles": visited_titles,
            # 地点 key 与标题分开给：Producer 的 location_key 字段要填 key，
            # 但 LLM 只见过标题——运行时两种都认（见 `_resolve_location_key`）
            "locations": [
                {"key": loc.location_key, "title": loc.title}
                for loc in known_locations
            ],
            "roster": self._known_names(),
            "player_role": self.state.player_role,
            "budgets": {
                "scenes_left": MAX_DYNAMIC_SCENES - len(self._world.dynamic_scenes),
                "characters_left": MAX_NEW_CHARACTERS - len(self._world.characters),
            },
        }

    def _resolve_location_key(self, raw: str | None) -> str | None:
        """Producer 的地点参数可能是 key 也可能是标题（LLM 输出）——两种都认。"""
        if not raw:
            return None
        if self.exploration.location(raw, self._world) is not None:
            return raw
        candidates = [
            *self.exploration.registry.ordered(),
            *self._world.dynamic_scenes.values(),
        ]
        return next((loc.location_key for loc in candidates if loc.title == raw), None)

    def _known_names(self) -> list[str]:
        """可拉入名单：剧本角色 + 运行期新增，排除玩家自己。"""
        names = [c.name for c in self.script.characters if not c.is_player_playable]
        names.extend(n for n in self._world.characters if n not in names)
        if self.state.player_role in names:
            names.remove(self.state.player_role)
        return names

    def _apply_intervention(self, intent: InterventionIntent) -> bool:
        """按意图类型应用（全部事件化）；返回是否改动了世界。"""
        if intent.kind == KIND_CREATE_SCENE:
            return self._intervene_create_scene(intent)
        if intent.kind == KIND_ADD_CHARACTER:
            return self._intervene_add_character(intent)
        if intent.kind == KIND_PULL_IN_CHARACTER:
            return self._intervene_pull_in(intent)
        return self._reject_intervention(intent.reason)

    def _reject_intervention(self, reason: str) -> bool:
        self._append(
            evt.EVENT_INTERVENTION_REJECTED,
            {"reason": reason or "这个请求无法实现。"},
        )
        return False

    def _intervene_create_scene(self, intent: InterventionIntent) -> bool:
        if len(self._world.dynamic_scenes) >= MAX_DYNAMIC_SCENES:
            return self._reject_intervention(
                f"新场景最多 {MAX_DYNAMIC_SCENES} 个，本局已经用完了。"
            )
        taken = {loc.title for loc in self.exploration.registry.ordered()}
        taken.update(loc.title for loc in self._world.dynamic_scenes.values())
        if intent.title in taken:
            return self._reject_intervention("这个地点已经存在，不用再建。")
        participants = tuple(
            n for n in intent.participants if n in self._known_names()
        )
        scene_key = location_scene_key(intent.title)
        payload = {
            "scene_key": scene_key,
            "location_key": intent.title,
            "title": intent.title,
            "participants": list(participants),
            "visual_summary": intent.visual_summary,
            # 锚定的已访问地点（§B4）：解析得到就记下（连通性过滤后置），
            # 解析不到按当前地点处理——锚点是建议性输入，不因此拒绝
            "parent_location_key": self._resolve_location_key(
                intent.parent_location_key
            )
            or self._exploration_progress.current_location_key,
            "current_asset": None,
        }
        self._append(evt.EVENT_SCENE_CREATED, payload)
        self._refresh_world()
        # 新场景无图（#56）：记一次 scene_montage 配图意图，Session 层后台生成
        created = self._world.dynamic_scenes.get(scene_key)
        if created is not None:
            self._request_location_asset(created)
        return True

    def _intervene_add_character(self, intent: InterventionIntent) -> bool:
        if len(self._world.characters) >= MAX_NEW_CHARACTERS:
            return self._reject_intervention(
                f"新角色最多 {MAX_NEW_CHARACTERS} 个，本局已经用完了。"
            )
        if intent.name == self.state.player_role or any(
            c.name == intent.name for c in self.script.characters
        ) or intent.name in self._world.characters:
            return self._reject_intervention("这个名字已经在戏里了，不能新建同名角色。")
        if intent.location_key:
            location_key = self._resolve_location_key(intent.location_key)
            if location_key is None:
                return self._reject_intervention("没有这个地点。")
        else:
            location_key = self._exploration_progress.current_location_key
        payload = {
            "name": intent.name,
            "public_background": intent.brief,
            "personality_traits": [intent.personality] if intent.personality else [],
            # 头像简述（§B5；头像生成本身随资产管线后置，字段先按事件形状留好）
            "avatar_brief": intent.brief,
            "location_key": location_key,
            "origin": "player_intervention",
        }
        self._append(evt.EVENT_CHARACTER_CREATED, payload)
        self._refresh_world()
        # provenance 记忆与重放同一写者（derive_memories），实时也折这一次
        self.characters.derive_memories(
            [{"event_type": evt.EVENT_CHARACTER_CREATED, "payload": payload}]
        )
        return True

    def _intervene_pull_in(self, intent: InterventionIntent) -> bool:
        if intent.name not in self._known_names():
            return self._reject_intervention(f"「{intent.name}」不在可拉入的角色名单里。")
        if intent.name in self._exploration_present():
            return self._reject_intervention(f"「{intent.name}」已经在这里了。")
        here = self.exploration.location(
            self._exploration_progress.current_location_key, self._world
        )
        if here is None:
            return self._reject_intervention("当前地点无效。")
        payload = {
            "name": intent.name,
            # 来源场景可推断就记（审计/迁移动画用），推断不到留空
            "from_scene": self._character_current_scene(intent.name),
            "to_scene": here.scene_key,
            # Producer 生成的到场理由（§B5）：写进事件，重放/投影同源
            "reason": intent.reason or "他闻讯赶来了。",
        }
        self._append(evt.EVENT_PULL_IN_CHARACTER, payload)
        self._refresh_world()
        return True

    def _character_current_scene(self, name: str) -> str | None:
        """角色此刻所在的地点场景键（按地点表现场名单推断；推断不到返回 None）。"""
        for location in (
            *self.exploration.registry.ordered(),
            *self._world.dynamic_scenes.values(),
        ):
            if name in self.exploration.participants_at(location, self._world):
                return location.scene_key
        return None

    def _refresh_world(self) -> None:
        """从事件重建运行期世界 + 同步角色 Agent（实时路径与重放同构）。"""
        self._world = derive_world(self.event_store.active_events())
        self._sync_world_characters()

    def _sync_world_characters(self) -> None:
        """让 manager 的角色集与 `_world.characters` 一致（幂等，重放复用）。

        回溯到 `character_created` 之前时该角色「从未存在」：事件派生集合里没有它，
        这里把它从 manager 移除（生产路径按命令重建运行时，同一不变量）。
        """
        script_names = {c.name for c in self.script.characters}
        for name in [n for n in self.characters.agents if n not in script_names]:
            if name not in self._world.characters:
                self.characters.remove_character(name)
        for name, profile in self._world.characters.items():
            self.characters.add_character(_setting_from_payload(profile))

    # ===== 推进引擎：跑到下一个稳定交互点 =====

    async def _drive_until_interaction(
        self,
        *,
        new_events: list[dict] | None = None,
        force_node_id: str | None = None,
    ) -> StepResult:
        if self.replay is not None and self.state.stage == StageValue.STAGE2_REENACTING.value:
            return await self._drive_replay(new_events, force_node_id=force_node_id)
        sink: list[dict] = new_events if new_events is not None else []

        while True:
            stage_name = self._runtime_stage_alias()
            await self._run_cycle_head(stage_name, sink)

            reached_ending = stage_name == "stage2" and self.state.beat_cursor >= total_beats(
                self.script
            )
            if stage_name == "stage3" and self.exploration is not None:
                interaction = self._stage3_interaction()
            else:
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
        if stage == "stage3" and self.exploration is not None:
            await self._stage3_exploration_head(stage, sink)
            return
        self.state.phase = InteractionPhase.NARRATIVE.value
        adv = self.screenwriter.advance_plot(self.script, stage)
        # 进度游标显式同步：state 是权威，screenwriter 游标是派生
        self.state.beat_cursor = self.screenwriter.beat_index
        ctx = self._beat_ctx(self.state.beat_cursor)
        self.state.scene_key = f"scene:{ctx.scene_id}" if ctx is not None else None
        # 事件索引优先（§9）：重连/回溯重放后，已就绪的运行期配图必须随叙事一同下发，
        # 否则前端会被 payload 里的 current_asset=null 清掉刚换上的背景。
        current_asset = self._current_background(ctx)
        self._request_scene_asset(stage, ctx, current_asset)
        self._append(
            evt.EVENT_PLOT_ADVANCEMENT,
            {
                "summary": adv.summary,
                "scene": adv.scene_description,
                # #53：场景键/标题/背景进 payload——重放重建 scene_key，
                # 前端在**实时**切换场景时即可换图（不必等重连的 session_init）
                "scene_key": self.state.scene_key,
                "scene_title": ctx.title if ctx is not None else None,
                "current_asset": (
                    current_asset.model_dump(mode="json") if current_asset is not None else None
                ),
            },
            sink=sink,
        )
        self.state.plot_log.append(adv.summary)
        self.characters.broadcast_plot_context(adv.summary)

        self.state.phase = InteractionPhase.DIRECTION.value
        direction = self.screenwriter.confirm_direction(self.script, stage)
        direction_payload = {"conflict": direction.conflict, "context": direction.context}
        self.state.direction = dict(direction_payload)
        self._append(
            evt.EVENT_DIRECTION,
            direction_payload,
            sink=sink,
        )
        self.characters.broadcast_direction(direction_payload)

        proposals = await self._collect_proposals(stage, sink)
        self._valid_proposals = await self._verify_proposals(proposals, stage, sink)

    # ===== Agent 调度 =====

    def _request_scene_asset(
        self, stage: str, ctx: Scene | None, current_asset: AssetRef | None
    ) -> None:
        """新场景缺图时记下一次运行期配图意图（#56，ADR-0005 §5）。

        只在 Stage3（续写）触发：Stage2 的配图由剧本生成 workflow 离线预生成
        （#48），游走中再生成等于对已审批的剧本私自改图、且付两次费。这里**只记
        意图**，不调用任何 provider——真正的生成由 Session 层在命令事务提交后
        派给后台任务（后台任务不得持有 GameRuntime）。

        去重交给两处：已在事件索引/剧本槽位里的场景不重复请求；同一进程内
        在途或已失败的 scene_key 由调度器拦下（见 `services/scene_assets.py`）。
        """
        if stage != "stage3" or ctx is None or self.state.scene_key is None:
            return
        if current_asset is not None:
            return
        self._asset_requests.append(
            SceneAssetIntent(
                scene_key=self.state.scene_key,
                description=scene_visual_description(ctx),
            )
        )

    # ===== 离线 tick（M7；design play-through-redesign §B6）=====

    async def offline_tick(self, *, tick_id: str) -> int:
        """一次离线 tick：在场 NPC 自主提议 → 验证 → 确定性结算成 world_fact。

        不设计玩家选项、不跑导演、不判续写目标、不动回合计数（§B6）；返回写入的
        事实条数。事件都落在运行时的事件存储里，由调用方（服务层）与
        `session_ticks` 认领行同一事务提交——重放时与实时路径同一折叠。
        """
        if (
            self.exploration is None
            or self.state.stage != StageValue.STAGE3_EXTENDING.value
        ):
            return 0
        names = list(self.characters.active_names())
        if not names:
            return 0
        proposals = await self._collect_proposals("stage3", [], names=names)
        valid = await self._verify_proposals(proposals, "stage3", [])
        for index, proposal in enumerate(valid, start=1):
            self._append(
                evt.EVENT_WORLD_FACT,
                npc_action_fact(
                    tick_id=tick_id,
                    index=index,
                    actor=proposal.proposed_by,
                    description=proposal.description,
                    location_key=self._actor_location_key(proposal.proposed_by),
                ),
            )
        return len(valid)

    def _actor_location_key(self, name: str) -> str | None:
        """角色此刻所在地点的 location_key（事实的地点锚）。"""
        for location in (
            *self.exploration.registry.ordered(),
            *self._world.dynamic_scenes.values(),
        ):
            if name in self.exploration.participants_at(location, self._world):
                return location.location_key
        if self._exploration_progress is None:
            return None
        current = self.exploration.location(
            self._exploration_progress.current_location_key, self._world
        )
        return current.location_key if current is not None else None

    async def _collect_proposals(
        self, stage: str, sink: list[dict], *, names: list[str] | None = None
    ) -> list[Proposal]:
        active = names if names is not None else self.characters.active_names()

        async def _one(name: str) -> Proposal:
            return await self.characters.get(name).propose_action(stage)

        results = await asyncio.gather(*[_one(n) for n in active], return_exceptions=True)
        proposals: list[Proposal] = []
        for name, res in zip(active, results):
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
                    self._log.error("verify_failed", extra={"proposal": prop.proposal_id})
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
                    revised = await self.characters.get(prop.proposed_by).revise_proposal(
                        stage,
                        res.rejections[0].suggestion if res.rejections else None,
                    )
                    # 重提也是提议：不落事件的话，重放/回溯后这份记忆会消失，
                    # `rejected` 去重语义也随之弱于回溯前。
                    self._append(
                        evt.EVENT_PROPOSAL,
                        {
                            "proposed_by": revised.proposed_by,
                            "description": revised.description,
                            "revised": True,
                        },
                        sink=sink,
                    )
                    still_pending.append(revised)
                elif res.verdict != "reject":
                    valid.append(prop)
            pending = still_pending
            attempts_left -= 1
        return valid

    async def _collect_reactions(
        self, action: PlayerAction, stage: str, *, names: list[str] | None = None
    ) -> list[tuple[str, str]]:
        """各角色并发回应；返回成功的 (角色名, 回应) 供续写目标判定。

        `names` 缺省 = 全部参演角色；Stage3 探索模式传**在场**角色（地点
        participants ∩ 已创建角色），不在场的人不会凭空回应。
        """
        active = names if names is not None else self.characters.active_names()
        results = await asyncio.gather(
            *[self._react(name, action, stage) for name in active],
            return_exceptions=True,
        )
        reactions: list[tuple[str, str]] = []
        for name, res in zip(active, results):
            if isinstance(res, BaseException):
                self._log.error(
                    "react_failed",
                    extra={"wj_extra": {"name": name, "err": str(res)}},
                )
                continue
            # 落库的永远是**最终答复**；前端屏幕上已经滚过的那份是临时文本，
            # 由这条带 seq 的持久发言覆盖（ADR-0005 §10 终态规则）。
            self._append(evt.EVENT_CHARACTER_SPEECH, {"speaker": name, "text": res})
            self.state.speech_log.append((name, self.state.scene_key, res))
            reactions.append((name, res))
        return reactions

    async def _react(self, name: str, action: PlayerAction, stage: str) -> str:
        """单角色反应；配了流出口就开一条流，逐段推给客户端。

        多角色是并发生成的（`asyncio.gather`），每条流各有 `stream_id`，前端按
        `stream_id` 分轨渲染（ADR-0005 §11 的多音轨同源）。`end` 走 `finally`：
        生成中途抛错也必须收流，否则客户端会留着一条不结束的字幕。
        """
        sink = self._speech_sink
        if sink is None:
            return await self.characters.get(name).react_to(action, stage)
        stream_id = sink.start(name)
        try:
            return await self.characters.get(name).react_to(
                action,
                stage,
                on_delta=lambda text: sink.delta(stream_id, text),
            )
        finally:
            sink.end(stream_id)

    # ===== 回溯（保留旧历史；新分支继承前缀、目标拍重演）=====

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

        # 目标所属拍 = 路径上 id ≤ target 的最后一个叙事事件；重放它之前的全部前缀
        # （含此前各回合的 direction/proposal/发言），该拍由随后的
        # `_drive_until_interaction` 整拍重演。目标落在同回合后续事件上时同一规则
        # 仍回到该回合起点（防御：UI 只提供 narrative 目标）。
        # 珊瑚图播放的「拍」是 `replay_node_entered`（M4），Stage3 探索是
        # `exploration_settle`（M5），旧路径是 plot_advancement。
        # 目标之前没有任何叙事事件（如开局阶段事件）→ 不是合法回溯点，切分支前拒绝。
        if (
            self.state.stage == StageValue.STAGE3_EXTENDING.value
            and self.exploration is not None
        ):
            beat_type = evt.EVENT_EXPLORATION_SETTLE
        elif self.replay is not None:
            beat_type = evt.EVENT_REPLAY_NODE_ENTERED
        else:
            beat_type = evt.EVENT_PLOT_ADVANCEMENT
        beat_events = [
            e
            for e in self.event_store.active_events()
            if e.event_id <= target_event_id and e.event_type == beat_type
        ]
        target_beat_id = max((e.event_id for e in beat_events), default=0)
        if target_beat_id == 0:
            raise new(
                codes.ENG_ROLLBACK_TARGET_MISSING,
                extra={"event_id": target_event_id},
            )
        target_node_id = next(
            (
                str(e.payload["node_id"])
                for e in beat_events
                if e.event_id == target_beat_id and e.payload.get("node_id")
            ),
            None,
        )
        prefix = [
            e for e in self.event_store.active_events() if e.event_id < target_beat_id
        ]

        # 分支继承终点 = 前缀最后一个事件（含）：新分支路径恰好等于「重放前缀 +
        # 重演事件」，不与重放双计。若 root 含目标拍，下一次从 DB 恢复时目标拍与
        # 重演拍会各计一次、beat 游标漂移一拍（旧 `_memory_marks` 时代的隐性 bug）。
        superseded = self.event_store.rollback_to(
            prefix[-1].event_id, session_id=self.session_id, command_id=command_id
        )
        # 切分支后重放前缀整段，全部运行时状态（游标/剧情/方向/角色记忆）随事件
        # 回退（M0：事件是唯一权威；记忆由 `replay_from` → `derive_memories` 重建）
        self.replay_from(None, [e.to_dict() for e in prefix])

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
        # 回溯后从恢复点重新推进到下一个稳定交互点（新分支继续追加）；
        # 珊瑚图播放要整拍重演被回退的节点，故显式指定节点。
        driven = await self._drive_until_interaction(
            new_events=[roll_ev], force_node_id=target_node_id
        )
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

    def _append(self, event_type: str, payload: dict, *, sink: list[dict] | None = None) -> dict:
        ev = self.event_store.append(event_type, payload, session_id=self.session_id)
        entry = {"event_id": ev.event_id, "event_type": event_type}
        self._command_events.append(entry)
        if sink is not None:
            sink.append(entry)
        return entry

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
            allowed_commands=sorted(_ALLOWED_BY_STAGE[self.state.stage]),
            terminal=terminal,
            asset_requests=list(self._asset_requests),
        )

    async def _flush_events(self) -> None:
        if self._on_flush is not None:
            await self._on_flush()
