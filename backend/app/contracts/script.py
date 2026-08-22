"""剧本包契约（Stage1 产物）。

- `CharacterSetting`：角色设定（Agent identity / Stage3 一致性来源）。
- `Beat` / `Scene`：场景与情节点。
- `Stage2Beat`：Stage 2 关键情节，**必须携带至少一条原文证据**（设计文档 §2.3）。
- `ScriptPackage`：完整可玩剧本；可扮演角色必须是 characters 子集，结局 beat 必须存在。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.evidence import OriginalEvidenceRef
from app.contracts.material import GenreKind

SCRIPT_SCHEMA_VERSION = 1


class CharacterSetting(BaseModel):
    """单个角色的设定。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    description: str = ""
    personality: str = ""
    background: str = ""
    is_player_playable: bool = False


class Beat(BaseModel):
    """单个情节点。"""

    model_config = ConfigDict(extra="forbid")

    beat_id: int = Field(ge=0)
    title: str
    description: str


class Scene(BaseModel):
    """剧本中的一个场景。"""

    model_config = ConfigDict(extra="forbid")

    scene_id: int = Field(ge=0)
    title: str
    setting: str = ""
    beats: list[Beat] = Field(default_factory=list)


class Stage2Beat(Beat):
    """Stage 2 关键情节 beat —— 必须有原文证据，顺序即事件顺序。"""

    character_ids: list[str] = Field(default_factory=list)
    evidence: list[OriginalEvidenceRef] = Field(min_length=1)


class ScriptPackage(BaseModel):
    """完整剧本包。"""

    model_config = ConfigDict(extra="forbid")

    script_id: UUID
    title: str
    genre: GenreKind
    characters: list[CharacterSetting] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    stage2_beats: list[Stage2Beat] = Field(default_factory=list)
    teaching_focus: list[str] = Field(default_factory=list)
    player_playable_roles: list[str] = Field(default_factory=list)
    stage2_ending_beat_id: int = Field(ge=0)
    stage3_resume: str = ""
    schema_version: int = SCRIPT_SCHEMA_VERSION

    @model_validator(mode="after")
    def _roles_must_be_characters(self) -> ScriptPackage:
        names = {c.name for c in self.characters}
        unknown = set(self.player_playable_roles) - names
        if unknown:
            raise ValueError(f"player_playable_roles 引用了不存在的角色: {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def _ending_beat_must_exist(self) -> ScriptPackage:
        ids = {b.beat_id for b in self.stage2_beats}
        if self.stage2_ending_beat_id not in ids:
            raise ValueError(
                f"stage2_ending_beat_id={self.stage2_ending_beat_id} "
                f"不在 stage2_beats 中: {sorted(ids)}"
            )
        return self
