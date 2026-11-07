"""Stage2 珊瑚图纯 IO 播放（design play-through-redesign §A4，里程碑 M4）。

剧本的 `options / dialogue / endings` 派生出一张只读珊瑚图；播放器零 LLM、
零 agent：把节点内容摊成 `ReplayCue`（事件），在决策点给出选项。写事件、
包交互点由运行时 `GameRuntime` 负责（引擎不碰存储与契约投影）。

节点编号（与生成期配图槽位同一拼法）：
- 主干场景 `scene:{scene_id}`；
- 分支过场 `scene:{scene_id}::branch:{branch_id}`；
- 结局 `ending:{ending_id}`。

「回到决策点」（`return_mode=choice`）不是图上的边：分支播完停在父场景的
决策点，由 `options()` 重新给出同一组选项，UI 文案是「回到刚才的选择」。
玩家所选角色的台词在播放时跳过——不替玩家说话；该拍由叙述承担。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts.script import (
    AssetRef,
    DialogueLine,
    Scene,
    SceneOption,
    ScriptPackage,
)
from app.domain.game import event as evt
from app.domain.game.types import InteractionPoint

_BRANCH_SEP = "::branch:"
_RETURN_TO_CHOICE = "回到刚才的选择"
_DEFAULT_DECISION_CONTEXT = "请选择你的行动"


@dataclass(frozen=True)
class ReplayCue:
    """一条待写入事件存储的播放指令（`event_type` + payload）。"""

    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReplayBeat:
    beat_id: int
    description: str
    dialogue: tuple[DialogueLine, ...] = ()


@dataclass(frozen=True)
class ReplayBranch:
    node_id: str
    branch_id: str
    parent_scene_id: int
    title: str
    beats: tuple[ReplayBeat, ...]
    dialogue: tuple[DialogueLine, ...]
    ending_id: str | None
    return_mode: str
    return_scene_id: int | None
    background_asset: AssetRef | None = None


@dataclass(frozen=True)
class ReplayScene:
    node_id: str
    scene_id: int
    title: str
    participants: tuple[str, ...]
    beats: tuple[ReplayBeat, ...]
    options: tuple[SceneOption, ...]
    branches: dict[str, ReplayBranch]
    interaction_context: str = _DEFAULT_DECISION_CONTEXT
    background_asset: AssetRef | None = None


@dataclass(frozen=True)
class ReplayEnding:
    node_id: str
    ending_id: str
    title: str
    description: str
    kind: str


@dataclass(frozen=True)
class ReplayGraph:
    """派生自 `ScriptPackage` 的只读珊瑚图（无第二份持久化真相）。"""

    scenes: tuple[ReplayScene, ...]
    endings: dict[str, ReplayEnding]
    by_node: dict[str, ReplayScene | ReplayBranch | ReplayEnding]
    mainline: tuple[str, ...]
    # 主干播完（最后一场没有决策点）时使用的结局：第一个 canonical，兜底第一个
    mainline_ending: ReplayEnding | None


@dataclass(frozen=True)
class ReplayState:
    """播放位置：当前节点 + 是否已到达结局。"""

    node_id: str
    ending_id: str | None = None


def _beat_list(raw_beats: list) -> tuple[ReplayBeat, ...]:
    """契约 beats → 播放节拍（场景 beat 自带台词；分支 beat 的台词为空）。"""
    return tuple(
        ReplayBeat(b.beat_id, b.description, tuple(b.dialogue)) for b in raw_beats
    )


def _scene_node(scene: Scene) -> ReplayScene:
    branches = {
        branch.branch_id: ReplayBranch(
            node_id=f"scene:{scene.scene_id}{_BRANCH_SEP}{branch.branch_id}",
            branch_id=branch.branch_id,
            parent_scene_id=scene.scene_id,
            title=branch.title,
            beats=_beat_list(branch.beats),
            dialogue=tuple(branch.dialogue),
            ending_id=branch.ending_id,
            return_mode=branch.return_mode,
            return_scene_id=branch.return_scene_id,
            background_asset=branch.background_asset,
        )
        for branch in scene.branches
    }
    point = scene.interaction_point
    return ReplayScene(
        node_id=f"scene:{scene.scene_id}",
        scene_id=scene.scene_id,
        title=scene.title,
        participants=tuple(scene.participants),
        beats=_beat_list(scene.beats),
        options=tuple(scene.options),
        branches=branches,
        # 契约介入点只有「玩家可以做什么」，拿它当决策点的提示语
        interaction_context=(
            point.what_player_can_do
            if point is not None and point.what_player_can_do
            else _DEFAULT_DECISION_CONTEXT
        ),
        background_asset=scene.background_asset,
    )


def build_replay_graph(pkg: ScriptPackage) -> ReplayGraph | None:
    """旧剧本（无 options / endings）返回 None → 运行时走 agent 线性路径。"""
    if not any(scene.options for scene in pkg.scenes) and not pkg.endings:
        return None
    scenes = tuple(_scene_node(scene) for scene in pkg.scenes)
    endings: dict[str, ReplayEnding] = {}
    for ending in pkg.endings:
        node = ReplayEnding(
            node_id=f"ending:{ending.ending_id}",
            ending_id=ending.ending_id,
            title=ending.title,
            description=ending.description,
            kind=ending.kind,
        )
        endings[node.node_id] = node
    by_node: dict[str, ReplayScene | ReplayBranch | ReplayEnding] = {
        scene.node_id: scene for scene in scenes
    }
    for scene in scenes:
        for branch in scene.branches.values():
            by_node[branch.node_id] = branch
    by_node.update(endings)
    mainline_ending = next(
        (e for e in endings.values() if e.kind == "canonical"), None
    ) or next(iter(endings.values()), None)
    return ReplayGraph(
        scenes=scenes,
        endings=endings,
        by_node=by_node,
        mainline=tuple(scene.node_id for scene in scenes),
        mainline_ending=mainline_ending,
    )


class ReplayDirector:
    """确定性播放器：只读珊瑚图，产出 cue；不做 IO、不调 LLM。"""

    def __init__(self, graph: ReplayGraph) -> None:
        self.graph = graph

    # ===== 入口 =====

    def start(self, player_role: str | None) -> tuple[ReplayState, list[ReplayCue]]:
        if not self.graph.mainline:
            return self._mainline_ending()
        return self._enter(self.graph.mainline[0], player_role)

    def enter(
        self, node_id: str, player_role: str | None
    ) -> tuple[ReplayState, list[ReplayCue]]:
        """从指定节点整段重演（回溯到某拍后使用）。"""
        return self._enter(node_id, player_role)

    def choose(
        self, state: ReplayState, option_id: str, player_role: str | None
    ) -> tuple[ReplayState, list[ReplayCue]]:
        scene = self._decision_scene(state)
        option = self.find_option(state, option_id)
        if scene is None or option is None:
            return state, []
        target = self._option_target(scene, option)
        cues = [
            ReplayCue(
                evt.EVENT_REPLAY_CHOICE,
                {
                    "option_id": option.option_id,
                    "label": option.label,
                    "kind": option.kind,
                    "from": state.node_id,
                    "to": target or "",
                },
            )
        ]
        if target is None:
            return self._mainline_ending(cues)
        next_state, more = self._enter(target, player_role)
        return next_state, [*cues, *more]

    def resolve(self, events: Any) -> ReplayState | None:
        """从活动分支事件折叠播放位置（`GameEvent` 或 `to_dict()` 均可）。"""
        state: ReplayState | None = None
        for ev in events:
            if isinstance(ev, dict):
                etype = ev.get("event_type") or ev.get("type")
                payload = ev.get("payload") or {}
            else:
                etype = getattr(ev, "event_type", None)
                payload = getattr(ev, "payload", None) or {}
            if etype == evt.EVENT_REPLAY_NODE_ENTERED:
                node_id = payload.get("node_id")
                if node_id in self.graph.by_node:
                    state = ReplayState(node_id=str(node_id))
            elif etype == evt.EVENT_REPLAY_ENDING_REACHED:
                ending_id = payload.get("ending_id")
                node_id = payload.get("node_id") or f"ending:{ending_id}"
                state = ReplayState(node_id=str(node_id), ending_id=ending_id)
        return state

    # ===== 决策点 / 结局 =====

    def find_option(self, state: ReplayState, option_id: str) -> SceneOption | None:
        scene = self._decision_scene(state)
        if scene is None:
            return None
        return next((o for o in scene.options if o.option_id == option_id), None)

    def options(self, state: ReplayState) -> InteractionPoint | None:
        """当前决策点的契约交互点；结局/无决策点返回 None。"""
        scene = self._decision_scene(state)
        if scene is None or not scene.options:
            return None
        node = self.graph.by_node.get(state.node_id)
        context = (
            _RETURN_TO_CHOICE
            if isinstance(node, ReplayBranch)
            else scene.interaction_context
        )
        return InteractionPoint(
            mode="options",
            context=context,
            options=[
                {"id": option.option_id, "text": option.label, "proposed_by": "system"}
                for option in scene.options
            ],
        )

    def ending_interaction(self, state: ReplayState) -> InteractionPoint:
        """到达结局后的 0/1 出口（0=续写、1=结束），沿用旧交互约定。"""
        ending = self.graph.endings.get(state.node_id)
        context = "已到达课文结局，选择是否进入剧情续写。"
        if ending is not None:
            context = f"已到达结局「{ending.title}」"
            if ending.description:
                context += f"：{ending.description}"
            else:
                context += "。"
        return InteractionPoint(
            mode="options",
            context=context,
            options=[
                {"id": 0, "text": "进入剧情续写（Stage3）", "proposed_by": "system"},
                {"id": 1, "text": "到此结束", "proposed_by": "system"},
            ],
        )

    # ===== 投影辅助（export_state / 重连用）=====

    def scene_key_of(self, state: ReplayState | None) -> str | None:
        if state is None or isinstance(self.graph.by_node.get(state.node_id), ReplayEnding):
            return None
        return state.node_id

    def title_of(self, state: ReplayState | None) -> str | None:
        node = self.graph.by_node.get(state.node_id) if state is not None else None
        return node.title if node is not None else None

    def background_of(self, state: ReplayState | None) -> AssetRef | None:
        node = self.graph.by_node.get(state.node_id) if state is not None else None
        if isinstance(node, ReplayScene | ReplayBranch):
            return node.background_asset
        return None

    # ===== 内部：节点播放 =====

    def _enter(
        self, node_id: str, player_role: str | None
    ) -> tuple[ReplayState, list[ReplayCue]]:
        cues: list[ReplayCue] = []
        current: str | None = node_id
        while current is not None:
            node = self.graph.by_node.get(current)
            if node is None:
                # 引用损坏（生成期已校验；教师手改包兜底）——收敛到主线结局，不崩
                return self._mainline_ending(cues)
            if isinstance(node, ReplayEnding):
                cues.append(self._ending_cue(node))
                return ReplayState(node_id=node.node_id, ending_id=node.ending_id), cues
            if isinstance(node, ReplayScene):
                cues.extend(self._scene_cues(node, player_role))
                if node.options:
                    return ReplayState(node_id=node.node_id), cues
                current = self._next_mainline(node.node_id)
                continue
            cues.extend(self._branch_cues(node, player_role))
            if node.ending_id is not None:
                current = f"ending:{node.ending_id}"
                continue
            if node.return_mode == "choice":
                return ReplayState(node_id=node.node_id), cues
            current = self._branch_return(node)
        return self._mainline_ending(cues)

    def _scene_cues(self, scene: ReplayScene, player_role: str | None) -> list[ReplayCue]:
        cues = [self._enter_cue(scene)]
        for beat in scene.beats:
            cues.append(self._narration_cue(scene.node_id, beat.description))
            cues.extend(self._line_cues(scene.node_id, beat.dialogue, player_role))
        return cues

    def _branch_cues(self, branch: ReplayBranch, player_role: str | None) -> list[ReplayCue]:
        cues = [self._enter_cue(branch)]
        for beat in branch.beats:
            cues.append(self._narration_cue(branch.node_id, beat.description))
        cues.extend(self._line_cues(branch.node_id, branch.dialogue, player_role))
        return cues

    def _line_cues(
        self,
        node_id: str,
        dialogue: tuple[DialogueLine, ...],
        player_role: str | None,
    ) -> list[ReplayCue]:
        cues: list[ReplayCue] = []
        for line in dialogue:
            if line.speaker is not None and line.speaker == player_role:
                continue  # 不替玩家说话
            if line.speaker is None:
                cues.append(self._narration_cue(node_id, line.text))
                continue
            cues.append(
                ReplayCue(
                    evt.EVENT_CHARACTER_SPEECH,
                    {
                        "speaker": line.speaker,
                        "text": line.text,
                        "stage_direction": line.stage_direction,
                        "source": "replay",
                    },
                )
            )
        return cues

    def _enter_cue(self, node: ReplayScene | ReplayBranch) -> ReplayCue:
        asset = node.background_asset
        return ReplayCue(
            evt.EVENT_REPLAY_NODE_ENTERED,
            {
                "node_id": node.node_id,
                "node_kind": "scene" if isinstance(node, ReplayScene) else "branch",
                "scene_key": node.node_id,
                "scene_title": node.title,
                "current_asset": asset.model_dump(mode="json") if asset is not None else None,
            },
        )

    def _narration_cue(self, node_id: str, text: str) -> ReplayCue:
        return ReplayCue(
            evt.EVENT_REPLAY_NARRATION, {"node_id": node_id, "text": text}
        )

    def _ending_cue(self, ending: ReplayEnding) -> ReplayCue:
        return ReplayCue(
            evt.EVENT_REPLAY_ENDING_REACHED,
            {
                "node_id": ending.node_id,
                "ending_id": ending.ending_id,
                "title": ending.title,
                "kind": ending.kind,
            },
        )

    # ===== 内部：图导航 =====

    def _decision_scene(self, state: ReplayState) -> ReplayScene | None:
        node = self.graph.by_node.get(state.node_id)
        if isinstance(node, ReplayScene):
            return node
        if isinstance(node, ReplayBranch):
            parent = self.graph.by_node.get(f"scene:{node.parent_scene_id}")
            return parent if isinstance(parent, ReplayScene) else None
        return None

    def _option_target(self, scene: ReplayScene, option: SceneOption) -> str | None:
        if option.ending_id is not None:
            return f"ending:{option.ending_id}"
        if option.target_scene_id is not None:
            return f"scene:{option.target_scene_id}"
        if option.branch_id is not None:
            return f"{scene.node_id}{_BRANCH_SEP}{option.branch_id}"
        return self._next_mainline(scene.node_id)

    def _branch_return(self, branch: ReplayBranch) -> str | None:
        if branch.return_scene_id is not None:
            return f"scene:{branch.return_scene_id}"
        return self._next_mainline(f"scene:{branch.parent_scene_id}")

    def _next_mainline(self, node_id: str) -> str | None:
        try:
            idx = self.graph.mainline.index(node_id)
        except ValueError:
            return None
        return (
            self.graph.mainline[idx + 1]
            if idx + 1 < len(self.graph.mainline)
            else None
        )

    def _mainline_ending(
        self, cues: list[ReplayCue] | None = None
    ) -> tuple[ReplayState, list[ReplayCue]]:
        out = list(cues or [])
        ending = self.graph.mainline_ending
        if ending is None:
            return ReplayState(node_id=""), out
        out.append(self._ending_cue(ending))
        return ReplayState(node_id=ending.node_id, ending_id=ending.ending_id), out


__all__ = [
    "ReplayCue",
    "ReplayDirector",
    "ReplayEnding",
    "ReplayGraph",
    "ReplayScene",
    "ReplayState",
    "build_replay_graph",
]
