"""导出契约模型的 JSON Schema 到 contracts/jsonschema/。

用法：cd backend && uv run python -m scripts.export_contracts
前端（#6）用这些 schema + fixtures 做运行时一致性校验；CI 断言两者不过期。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.auth import (
    AuthSessionInfo,
    LoginRequest,
    RegisterRequest,
    UserPublic,
)
from app.contracts.commands import PlayerCommand
from app.contracts.content import TextAnalysis
from app.contracts.dto import (
    CreateSessionRequest,
    ServerMessage,
    SessionListResponse,
    SessionSummary,
)
from app.contracts.errors import ErrorEnvelope
from app.contracts.events import DomainEvent
from app.contracts.material import Material, MaterialInput
from app.contracts.runtime import GameSnapshot, RuntimeState, RuntimeUpdate
from app.contracts.script_library import (
    MaterialPublic,
    ScriptCreateRequest,
    ScriptDetail,
    ScriptListResponse,
    ScriptPublishRequest,
    ScriptSummary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "contracts" / "jsonschema"

EXPORTS: dict[str, type] = {
    "auth_register": RegisterRequest,
    "auth_login": LoginRequest,
    "user_public": UserPublic,
    "auth_session_info": AuthSessionInfo,
    "material_input": MaterialInput,
    "material": Material,
    "material_public": MaterialPublic,
    "text_analysis": TextAnalysis,
    "player_command": PlayerCommand,
    "domain_event": DomainEvent,
    "create_session_request": CreateSessionRequest,
    "session_summary": SessionSummary,
    "session_list_response": SessionListResponse,
    "runtime_state": RuntimeState,
    "game_snapshot": GameSnapshot,
    "runtime_update": RuntimeUpdate,
    "error_envelope": ErrorEnvelope,
    "server_message": ServerMessage,
    "script_create_request": ScriptCreateRequest,
    "script_publish_request": ScriptPublishRequest,
    "script_summary": ScriptSummary,
    "script_detail": ScriptDetail,
    "script_list_response": ScriptListResponse,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in EXPORTS.items():
        schema = model.model_json_schema()
        path = OUT_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
