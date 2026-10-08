"""剧本包契约：ScriptPackage 及其组成部分。

- Stage 2 关键 beat 必须带原文 EvidenceRef 并保持顺序（spec 决策）。
- 角色设定表、可扮演角色列表供选角与角色 Agent 初始化使用。
- 场景/角色可携带稳定资产引用 `AssetRef`（ADR-0005 §3：URL-free，不存字节）。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.contracts.base import VersionedContract
from app.contracts.material import EvidenceRef  # noqa: F401


class AssetRef(VersionedContract):
    """稳定资产引用（ADR-0005 §3）。

    只放稳定 id/kind/status；字节与 URL（含 `object_key`）不进契约——访问经鉴权
    端点签发短时效预签名 URL（#42）。
    """

    asset_id: uuid.UUID
    kind: Literal["background", "avatar", "fullbody"]
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


class CharacterProfile(VersionedContract):
    """单个角色的设定（身份/背景/性格/语言风格），角色 Agent identity 的来源。"""

    name: str
    public_background: str
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


class Scene(VersionedContract):
    """剧本中的一个场景：参与者 + 有序 beats。"""

    scene_id: int
    title: str
    participants: list[str] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
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
