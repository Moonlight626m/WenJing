"""剧本库（issue #19 / ADR-0002 §3）：可复用剧本实体的应用服务与 API。"""

from app.scripts.service import ScriptLibrary, legacy_progress

__all__ = ["ScriptLibrary", "legacy_progress"]
