"""剧本包契约：ScriptPackage 及其组成部分。

- Stage 2 关键 beat 必须带原文 EvidenceRef 并保持顺序（spec 决策）。
- 角色设定表、可扮演角色列表供选角与角色 Agent 初始化使用。
- 场景/角色可携带稳定资产引用 `AssetRef`（ADR-0005 §3：URL-free，不存字节）。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.contracts.base import ContractModel, VersionedContract
from app.contracts.material import EvidenceRef  # noqa: F401


class AssetRef(VersionedContract):
    """稳定资产引用（ADR-0005 §3）。

    只放稳定 id/kind/status；字节与 URL（含 `object_key`）不进契约——访问经鉴权
    端点签发短时效预签名 URL（#42）。

    `scene_montage`（方案 branch-montage-dm）是**完整场面图**：背景+在场人物+
    行为一图的插画（推翻 ADR-0005 §1「游玩内不显示人物」需随 ADR 修订走）；
    `background` 保留给旧脚本与纯空镜背景。
    """

    asset_id: uuid.UUID
    kind: Literal["background", "avatar", "fullbody", "scene_montage"]
    status: Literal["pending", "ready", "failed"]


class AssetCredit(VersionedContract):
    """素材署名/许可元数据（ADR-0005 §6）：供教师端展示与学生端折叠署名。

    默认仅采用免署名许可（CC0/PD）；采用需署名许可时向最终用户展示。
    """

    author: str = ""
    license: str = ""
    source_url: str = ""
    license_url: str = ""


class CharacterTrait(VersionedContract):
    """性格标签：标签 + 原文证据 + 行为化描述（show don't tell，spec 裁决）。"""

    label: str = Field(min_length=1)
    evidence: str = ""
    behavior: str = ""


class SpeechStyle(VersionedContract):
    """说话风格五要素 + 示例台词（驱动角色 Agent 的 persona，spec 裁决）。"""

    era_layer: str = ""
    sentence_rhythm: str = ""
    address_terms: str = ""
    catchphrases: str = ""
    emotion_expression: str = ""
    sample_lines: list[str] = Field(default_factory=list)


class KnowledgeBoundary(VersionedContract):
    """知识边界：角色知道/不知道的事（防 OOC，运行时 persona 引用）。"""

    knows: list[str] = Field(default_factory=list)
    not_knows: list[str] = Field(default_factory=list)


class Playability(VersionedContract):
    """是否适合玩家扮演：布尔 + 可选理由（不带安全考量，spec 裁决）。"""

    value: bool = False
    reason: str = ""


class Appearance(VersionedContract):
    """结构化外貌要素（文生图锚定）：只写原文可推断内容。

    未交代处如实填「原文未交代」，由媒体层渲染为时代中性词——
    严禁编造原文外的辨识性细节（具体五官、时代错位服饰）。
    """

    face: str = ""
    hair: str = ""
    clothing: str = ""
    accessories: str = ""
    build: str = ""


class CharacterProfile(VersionedContract):
    """单个角色的设定（身份/背景/性格/语言风格），角色 Agent identity 的来源。"""

    name: str
    public_background: str
    appearance: Appearance | None = None
    personality_traits: list[CharacterTrait] = Field(default_factory=list)
    speech_style: SpeechStyle | None = None
    knowledge_boundary: KnowledgeBoundary = Field(default_factory=KnowledgeBoundary)
    is_player_playable: Playability = Field(default_factory=Playability)
    # 详情页用（游玩内不显示头像，ADR-0005 §1）：M2 生成期预生成。
    avatar_asset: AssetRef | None = None
    fullbody_asset: AssetRef | None = None
    # 署名/许可（ADR-0005 §6）：需署名许可时详情页展示（#51/#54）。
    avatar_credit: AssetCredit | None = None
    fullbody_credit: AssetCredit | None = None


class Beat(VersionedContract):
    """单场景内的情节点；关键 beat 带 evidence_refs（原文证据）。"""

    beat_id: int
    description: str
    is_key_event: bool = False
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class InteractionPoint(ContractModel):
    """场景末尾的玩家介入点（drama manager 心智，spec 裁决）。

    为角色扮演运行时预留玩家介入空间：关键事件不可被介入改变，
    介入只发生在 must_not_change 之外的节拍间隙。

    定义在 script.py（Scene.interaction_point 引用它；review.py 的 SceneDraft
    也引用）——此前它只存在于 review.py，划分草稿产出后被写入剧本的环节
    丢弃；提升进剧本包是伪分支挂接介入点的前提。
    """

    player_role_hint: str = ""
    what_player_can_do: str = Field(min_length=1)
    must_not_change: list[int] = Field(default_factory=list)


class VisualNotes(VersionedContract):
    """场景视觉锚点（文生图槽位）：只写原文可推断的环境信息。

    未交代处写「原文未交代」或留空；动作留在 beats，此处不含人物行为。
    """

    era: str = ""
    location: str = ""
    time_of_day: str = ""
    weather: str = ""
    mood: str = ""


class BranchScene(VersionedContract):
    """伪分支场景（珊瑚形结构）：挂在主干场景介入点上的替代过场。

    分支播放完并回主干下一场，结局固定；分支 beat 一律非关键事件
    （不进 total_beats、不动主 beat_cursor），不得包含 must_not_change
    关键事件、不得改变课文结局。
    """

    branch_id: str = Field(pattern=r"^b[1-9][0-9]*$")
    # 选项文案：玩家在介入点看到的分支入口文字。
    label: str = Field(min_length=1)
    title: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    # 分支内局部节拍：beat_id 从 1 起在分支内递增，不参与主干全局序。
    beats: list[Beat] = Field(min_length=1)
    visual_notes: VisualNotes | None = None
    # 挂接点：None = 场景末尾（当前唯一实现）；未来支持同场多介入点时
    # 指向 Scene.beats 的 beat_id。
    anchor_beat_id: int | None = None
    # 分支场景图（完整场面 kind=scene_montage）；生成期预生成（#48 同通道）。
    background_asset: AssetRef | None = None
    background_credit: AssetCredit | None = None


class Scene(VersionedContract):
    """剧本中的一个场景：参与者 + 有序 beats。"""

    scene_id: int
    title: str
    participants: list[str] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    # 场景视觉锚点（文生图 prompt 的时代/地点/时段/氛围槽位）。
    visual_notes: VisualNotes | None = None
    # 场景末尾的玩家介入点（由划分草稿提升而来；此前生成后被丢弃）。
    interaction_point: InteractionPoint | None = None
    # 伪分支替代过场：玩家在介入点选择后播放，播完并回主干下一场。
    branches: list[BranchScene] = Field(default_factory=list)
    # 游玩内全屏背景（ADR-0005 §1）；无图时为 None（纯文本降级）。
    background_asset: AssetRef | None = None
    # 背景署名/许可（ADR-0005 §6）：需署名许可时详情页展示（#51/#54）。
    background_credit: AssetCredit | None = None


class ScriptPackage(VersionedContract):
    """Stage1 生成的完整剧本包（冻结契约，版本化校验后进入游戏）。"""

    title: str
    characters: list[CharacterProfile] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    teaching_focus: list[str] = Field(default_factory=list)
    playable_roles: list[str] = Field(min_length=1)
    stage2_ending_beat_id: int
