"""剧本包契约：ScriptPackage 及其组成部分。

- Stage 2 关键 beat 必须带原文 EvidenceRef 并保持顺序（spec 决策）。
- 角色设定表、可扮演角色列表供选角与角色 Agent 初始化使用。
"""

from __future__ import annotations

from pydantic import Field

from app.contracts.base import VersionedContract
from app.contracts.material import EvidenceRef  # noqa: F401


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


class CharacterProfile(VersionedContract):
    """单个角色的设定（身份/背景/性格/语言风格），角色 Agent identity 的来源。"""

    name: str
    public_background: str
    personality_traits: list[CharacterTrait] = Field(default_factory=list)
    speech_style: SpeechStyle | None = None
    knowledge_boundary: KnowledgeBoundary = Field(default_factory=KnowledgeBoundary)
    is_player_playable: Playability = Field(default_factory=Playability)


class Beat(VersionedContract):
    """单场景内的情节点；关键 beat 带 evidence_refs（原文证据）。"""

    beat_id: int
    description: str
    is_key_event: bool = False
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class Scene(VersionedContract):
    """剧本中的一个场景：参与者 + 有序 beats。"""

    scene_id: int
    title: str
    participants: list[str] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)


class ScriptPackage(VersionedContract):
    """Stage1 生成的完整剧本包（冻结契约，版本化校验后进入游戏）。"""

    title: str
    characters: list[CharacterProfile] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    teaching_focus: list[str] = Field(default_factory=list)
    playable_roles: list[str] = Field(min_length=1)
    stage2_ending_beat_id: int
