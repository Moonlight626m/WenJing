"""内容管线契约（issue #9）：体裁判断 + 原文分析输出。

- GenreType：体裁全集；前四类为支持的叙事体裁，其余按 spec 拒绝。
- TextAnalysis：原文分析结果（人物/关系/场景/关键事件），每条结论均以
  OriginalEvidence 锚定原文字符区间与段落，供 #11 Stage1 生成作为权威输入。
- EvidenceRef 区分原文证据（OriginalEvidence）与网络补充（WebEvidence）：
  原文分析只产出 OriginalEvidence；WebEvidence 由 #10 RAG 侧产生。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.contracts.base import VersionedContract
from app.contracts.material import OriginalEvidence


class GenreType(StrEnum):
    """体裁全集：前四类为支持的叙事体裁，后四类按 spec 返回 CONTENT_UNSUPPORTED_GENRE。"""

    NOVEL = "novel"                      # 小说
    NARRATIVE = "narrative"              # 叙事文/记叙文
    DRAMA = "drama"                      # 戏剧
    CHARACTER_STORY = "character_story"  # 人物故事
    EXPOSITORY = "expository"            # 说明文（拒绝）
    ARGUMENTATIVE = "argumentative"      # 议论文（拒绝）
    SCENERY = "scenery"                  # 纯写景（拒绝）
    POETRY = "poetry"                    # 诗歌（拒绝）
    UNKNOWN = "unknown"                  # 无法判定（拒绝）


# 支持的叙事体裁（issue #9 验收标准 2 的通过集）
SUPPORTED_GENRES: frozenset[GenreType] = frozenset(
    {
        GenreType.NOVEL,
        GenreType.NARRATIVE,
        GenreType.DRAMA,
        GenreType.CHARACTER_STORY,
    }
)


class GenreClassification(VersionedContract):
    """体裁判定结果：signals 记录判定依据，便于解释与回归。"""

    genre: GenreType
    is_supported: bool
    signals: list[str] = Field(default_factory=list)


class CharacterMention(VersionedContract):
    """人物：姓名 + 角色/性格分析，附原文证据。"""

    name: str = Field(min_length=1)
    role: str | None = None
    personality: str | None = None
    evidence_refs: list[OriginalEvidence] = Field(default_factory=list)


class RelationshipEdge(VersionedContract):
    """人物关系边：两端为人物名（source/target 无向，去重按字典序）。"""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    nature: str = Field(min_length=1)
    evidence_refs: list[OriginalEvidence] = Field(default_factory=list)


class SceneSetting(VersionedContract):
    """场景：地点/参与者/核心事件/在全文中的作用。"""

    title: str = Field(min_length=1)
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    core_event: str = Field(min_length=1)
    significance: str | None = None
    evidence_refs: list[OriginalEvidence] = Field(default_factory=list)


class KeyEvent(VersionedContract):
    """关键事件：按原文出现顺序编号（order 1 起）。"""

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    order: int = Field(ge=1)
    evidence_refs: list[OriginalEvidence] = Field(default_factory=list)


class TextAnalysis(VersionedContract):
    """原文分析结果（issue #9 验收标准 3）。

    content_hash 锚定规范化后的原文（与 Material.content_hash 一致）。
    """

    content_hash: str = Field(min_length=1)
    title: str | None = None
    author: str | None = None
    genre: GenreClassification
    characters: list[CharacterMention] = Field(default_factory=list)
    relationships: list[RelationshipEdge] = Field(default_factory=list)
    scenes: list[SceneSetting] = Field(default_factory=list)
    key_events: list[KeyEvent] = Field(default_factory=list)
