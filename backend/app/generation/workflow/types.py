"""workflow 内部产物类型（issue #28）。

中间产物（素材集/划分草稿）是 backend 内部类型，**不进 contracts/**：
教师端只读进度摘要（contracts/generation.py），完整草稿的契约化随
#34 教师闸门按需推进。最终产物仍是 contracts.script.ScriptPackage。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterNote(BaseModel):
    """素材集里对单个人物的结论。"""

    name: str = Field(min_length=1)
    note: str = Field(min_length=1)


class MaterialDossier(BaseModel):
    """素材收集节点产物：考证过的背景/时代/人物/情节/教学结论。"""

    background: str = Field(min_length=1)
    era_setting: str = Field(min_length=1)
    character_notes: list[CharacterNote] = Field(default_factory=list)
    plot_summary: str = Field(min_length=1)
    teaching_analysis: list[str] = Field(default_factory=list)


class BeatDraft(BaseModel):
    """划分草稿的单个节拍：key_event_order 指向原文关键事件序号。"""

    description: str = Field(min_length=1)
    is_key_event: bool = False
    key_event_order: int | None = Field(default=None, ge=1)


class SceneDraft(BaseModel):
    """划分草稿的单个场景。"""

    title: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    beats: list[BeatDraft] = Field(min_length=1)


class EventDivisionDraft(BaseModel):
    """事件/情景划分草稿：beats 结构先于剧本书写（#31 深化）。"""

    scenes: list[SceneDraft] = Field(min_length=1)
