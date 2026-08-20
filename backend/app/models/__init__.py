"""ORM 模型统一入口。

导入本包即把 `session.py` / `material.py` / `script.py` / `event.py` / `snapshot.py`
的全部模型注册到 `app.db.session.Base.metadata`（供 `alembic autogenerate` 与建表使用）。
"""

from __future__ import annotations

from app.models.event import GameEventRecord
from app.models.material import Material
from app.models.script import Script
from app.models.session import Session
from app.models.snapshot import Snapshot

__all__ = [
    "Session",
    "Material",
    "Script",
    "GameEventRecord",
    "Snapshot",
]

# 确保做元数据收集时模型已全部导入（Base.metadata 上注册）
_ = (Session, Material, Script, GameEventRecord, Snapshot)
