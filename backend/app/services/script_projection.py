"""剧本库 ORM → 契约投影（教师库 / 学生广场 / 运营后台共用）。

抽为独立模块，避免路由之间（`api/admin.py` ← `api/scripts.py`）互相依赖私有 mapper。
"""

from __future__ import annotations

from app.contracts.script_library import ScriptSummary
from app.infrastructure.models.script import Script as ScriptRecord


def script_summary(row: ScriptRecord) -> ScriptSummary:
    """剧本记录 → 轻量列表投影。"""
    return ScriptSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        visibility=row.visibility,
        material_id=row.material_id,
        owner_user_id=row.owner_user_id,
        org_id=row.org_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["script_summary"]
