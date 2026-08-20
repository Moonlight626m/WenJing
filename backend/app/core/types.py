"""引擎领域类型：剧本、提议、验证、玩家动作等结构化数据。

与 design_01（ScriptOutput / Proposal / VerificationResult / PlotAdvancement）对应。
MVP 阶段使用精简可序列化的 dataclass，便于事件溯源落库与测试断言。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.state_machine import GameStage, InteractionPhase

# ===== 剧本（Stage1 产物，MVP 由 mock 提供，不测生成链路）=====


@dataclass
class CharacterSetting:
    """单个角色的设定（角色 Agent 的 identity 来源）。"""

    name: str
    public_background: str
    personality_traits: list[str] = field(default_factory=list)
    is_player_playable: bool = False


@dataclass
class Beat:
    """单个场景内的情节点。"""

    beat_id: int
    description: str


@dataclass
class Scene:
    """剧本中的一个场景。"""

    scene_id: int
    title: str
    participants: list[str] = field(default_factory=list)
    beats: list[Beat] = field(default_factory=list)


@dataclass
class Script:
    """完整剧本（MVP 最小集：直接提供，不测试生成）。"""

    title: str
    characters: list[CharacterSetting]
    scenes: list[Scene]
    stage2_ending_beat_id: int


# ===== 提议与验证 =====


@dataclass
class Proposal:
    """角色 Agent 提出的行动提议。"""

    proposal_id: int
    proposed_by: str  # 角色名
    description: str
    expected_outcome: str | None = None


@dataclass
class Rejection:
    """单条验证驳回反馈。"""

    reason: str
    suggestion: str | None = None


@dataclass
class VerificationResult:
    """验证 Agent 对提议/推进的审核结果。"""

    verdict: str  # "pass" | "reject" | "conditional_pass"
    score: float
    rejections: list[Rejection] = field(default_factory=list)


# ===== 剧情推进（Stage2/3 单次）=====


@dataclass
class PlotAdvancement:
    """编剧 Agent 的单次剧情推进。"""

    summary: str
    scene_description: str


@dataclass
class Direction:
    """D5 两段式的第一步：确认当前矛盾/关键处境。"""

    conflict: str
    context: str


# ===== 交互与玩家 =====


@dataclass
class InteractionPoint:
    """交互设计器的产出（模式 A/B/C）。"""

    mode: str  # "options" | "free_input" | "options_with_fallback"
    context: str = ""
    options: list[dict] = field(default_factory=list)
    hint: str = ""


@dataclass
class PlayerAction:
    """玩家的写死动作（测试驱动）。"""

    type: str  # "choose_option" | "speak" | "act" | "rollback" | "confirm" | "exit"
    option_id: int | None = None
    text: str | None = None
    steps: int = 0


# ===== GameStage 别名（供类型提示简洁引用）=====

Stage = GameStage
Phase = InteractionPhase
