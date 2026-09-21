"""workflow 产物类型（issue #28 → #34 契约化）。

MaterialDossier / EventDivisionDraft 已随 #34 教师闸门契约化
（app/contracts/review.py：教师编辑请求引用同一形状）；此处 re-export
保持 workflow 内部引用点不变。最终产物仍是 contracts.script.ScriptPackage。
"""

from __future__ import annotations

from app.contracts.review import (
    BeatDraft,
    CharacterNote,
    EventDivisionDraft,
    MaterialDossier,
    SceneDraft,
)

__all__ = ["CharacterNote", "MaterialDossier", "BeatDraft", "SceneDraft", "EventDivisionDraft"]
