"""共享契约一致性测试（issue #2 验收标准）。

- fixtures 与契约模型同步：每个 fixture 必须通过对应模型的严格校验。
- JSON Schema 导出不过期：重新生成的 schema 必须与磁盘一致。
- allowed_commands 是 CommandType 的子集；错误码前缀与 domain 匹配。
- 契约包零基础设施依赖：导入 contracts 不引入 fastapi/sqlalchemy/agents/llm。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.contracts import CONTRACTS_SCHEMA_VERSION
from app.contracts.auth import (
    AuthSessionInfo,
    LoginRequest,
    RegisterRequest,
    UserPublic,
)
from app.contracts.commands import PlayerCommand
from app.contracts.content import TextAnalysis
from app.contracts.dto import (
    ResyncRequestMessage,
    ServerMessage,
    SubmitCommandMessage,
    client_message_adapter,
)
from app.contracts.enums import ALLOWED_COMMANDS, CommandKind, StageValue
from app.contracts.errors import ErrorEnvelope
from app.contracts.events import DomainEvent
from app.contracts.material import Material, MaterialInput
from app.contracts.runtime import GameSnapshot, RuntimeState
from app.contracts.script_library import (
    MaterialPublic,
    ScriptCreateRequest,
    ScriptDetail,
    ScriptListResponse,
    ScriptPublishRequest,
    ScriptSummary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "contracts" / "fixtures"
SCHEMAS = REPO_ROOT / "contracts" / "jsonschema"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ===== 1. fixtures ↔ 契约类型严格同步 =====


@pytest.mark.parametrize(
    ("fixture", "model"),
    [
        ("auth_register", RegisterRequest),
        ("auth_login", LoginRequest),
        ("user_public", UserPublic),
        ("auth_session_info", AuthSessionInfo),
        ("material_input", MaterialInput),
        ("material", Material),
        ("material_public", MaterialPublic),
        ("script_create_request", ScriptCreateRequest),
        ("script_publish_request", ScriptPublishRequest),
        ("script_summary", ScriptSummary),
        ("script_detail", ScriptDetail),
        ("script_list_response", ScriptListResponse),
        ("text_analysis", TextAnalysis),
        ("player_command", PlayerCommand),
        ("domain_event", DomainEvent),
        ("runtime_state", RuntimeState),
        ("error_envelope", ErrorEnvelope),
    ],
)
def test_fixture_validates_against_contract(fixture: str, model: type) -> None:
    data = _load(fixture)

    class Strict(model):  # type: ignore[misc,valid-type]
        pass

    # forbid extra：fixture 中的未知字段视为契约漂移
    parsed = Strict.model_validate(data)
    assert parsed.schema_version == CONTRACTS_SCHEMA_VERSION


def test_script_package_fixture_roundtrip() -> None:
    from app.contracts.script import ScriptPackage

    data = json.loads((FIXTURES / "script_package.json").read_text())
    pkg = ScriptPackage.model_validate(data)

    assert [b.beat_id for b in pkg.scenes[0].beats] == [1, 2, 3]
    key_beats = [b for b in pkg.scenes[0].beats if b.is_key_event]
    assert key_beats and all(b.evidence_refs for b in key_beats), "关键 beat 必须带原文证据"

    out = json.loads(pkg.model_dump_json())
    assert ScriptPackage.model_validate(out) == pkg


def test_domain_event_fresh_build_defaults() -> None:
    from uuid import uuid4

    ev = DomainEvent(
        session_id=uuid4(),
        branch_id=uuid4(),
        sequence=0,
        event_type="narrative_advanced",
    )
    assert ev.event_id is not None


# ===== 2. allowed_commands 约束 =====


def test_allowed_commands_cover_all_stages() -> None:
    stages = {s.value for s in StageValue}
    assert set(ALLOWED_COMMANDS.keys()) == stages
    all_kinds = set(CommandKind)
    for stage, kinds in ALLOWED_COMMANDS.items():
        assert kinds <= all_kinds, f"{stage} 含未定义命令"


def test_allowed_commands_semantics() -> None:
    assert CommandKind.SELECT_ROLE in ALLOWED_COMMANDS[StageValue.STAGE1_COMPLETE]
    assert ALLOWED_COMMANDS[StageValue.INIT] == frozenset()
    assert ALLOWED_COMMANDS[StageValue.ENDED] == frozenset()
    game_cmds = ALLOWED_COMMANDS[StageValue.STAGE2_REENACTING]
    assert {CommandKind.CHOOSE_OPTION, CommandKind.FREE_INPUT} & game_cmds
    assert CommandKind.ROLLBACK_TO_EVENT in game_cmds


# ===== 3. PlayerCommand payload 判别校验 =====


def test_player_command_payload_kind_mismatch_rejected() -> None:
    data = _load("player_command")
    data["kind"] = "free_input"
    data["payload"] = {"option_id": "x"}  # kind=payload 不匹配
    with pytest.raises(Exception):
        PlayerCommand.model_validate(data)


def test_player_command_payload_model_resolution() -> None:
    data = _load("player_command")
    cmd = PlayerCommand.model_validate(data)
    payload = cmd.payload_model
    assert type(payload).__name__ == "ChooseOptionPayload"
    assert payload.option_id == "opt_buy_oranges_reply"


# ===== 4. ErrorEnvelope 规则 =====


def test_error_code_prefix_must_match_domain() -> None:
    with pytest.raises(Exception):
        ErrorEnvelope(code="GAME_NOT_ALLOWED", domain="session", message="x")


def test_register_contract_requires_email_or_phone() -> None:
    """#17 契约：RegisterRequest 的「email 或 phone 二选一」必须进入导出 schema。"""
    schema = RegisterRequest.model_json_schema()
    branches = schema["allOf"][0]["anyOf"]
    assert {tuple(b["required"]) for b in branches} == {("email",), ("phone",)}


def test_unknown_stable_code_falls_back_internal() -> None:
    from app.contracts.errors import stable_code

    assert stable_code("TOTALLY_UNKNOWN") == ("internal", True)


# ===== 5. 运行时状态：无基础设施依赖 + 快照可序列化 =====


def test_contracts_import_does_not_pull_infra() -> None:
    code = (
        "import sys; import app.contracts as c;"
        "assert not any(m in sys.modules for m in "
        "('fastapi','sqlalchemy','langchain','langgraph','agents','asyncpg')), "
        "'contracts must not import infra';"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stderr


def test_runtime_state_snapshot_roundtrip() -> None:
    state = RuntimeState.model_validate(_load("runtime_state"))
    snap = GameSnapshot(session_id=state.session_id, branch_id=state.branch_id,
                        last_sequence=state.last_sequence, state=state)
    restored = GameSnapshot.model_validate(json.loads(snap.model_dump_json()))
    assert restored.state.character_memories == state.character_memories
    assert restored.state.active_interaction == state.active_interaction
    assert restored.state.allowed_commands()  # stage2 允许输入命令


def test_active_interaction_mode_command_mapping() -> None:
    state = RuntimeState.model_validate(_load("runtime_state"))
    ix = state.active_interaction
    assert ix is not None
    kinds = ix.allowed_command_kinds()
    assert "choose_option" in kinds and "free_input" in kinds  # fallback 模式


# ===== 6. WS 协议 DTO mapper =====


def test_client_messages_discriminated_parse() -> None:
    data = _load("player_command")
    submit = client_message_adapter.validate_python(
        {"type": "submit_command", "command": data}
    )
    assert isinstance(submit, SubmitCommandMessage)
    confirm = client_message_adapter.validate_python(
        {"type": "confirm_messages", "last_confirmed_seq": 3}
    )
    assert confirm.type == "confirm_messages"
    resync = client_message_adapter.validate_python(
        {"type": "resync_request", "last_confirmed_seq": 2}
    )
    assert isinstance(resync, ResyncRequestMessage)


def test_server_message_seq_and_payload() -> None:
    msg = ServerMessage(
        session_id="0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910",
        seq=5,
        type="interaction",
        payload={"interaction_id": "ix-1"},
    )
    parsed = ServerMessage.model_validate(json.loads(msg.model_dump_json()))
    assert parsed.seq == 5 and parsed.type == "interaction"


def test_interaction_mapper_from_contract() -> None:
    from app.contracts.dto import interaction_to_payload

    state = RuntimeState.model_validate(_load("runtime_state"))
    payload = interaction_to_payload(state.active_interaction)  # type: ignore[arg-type]
    assert payload.mode == "options_with_fallback"
    assert len(payload.options) == 2


# ===== 7. JSON Schema 导出不过期（前端一致性锚点）=====


def test_exported_json_schemas_are_current(tmp_path: Path) -> None:
    from scripts.export_contracts import EXPORTS

    stale = []
    for name, model in EXPORTS.items():
        fresh = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
        path = SCHEMAS / f"{name}.schema.json"
        if not path.exists() or path.read_text() != fresh:
            stale.append(name)
    assert not stale, f"JSON Schema 过期，运行 backend/scripts/export_contracts.py 更新: {stale}"


def test_all_fixtures_have_schema_versions() -> None:
    for path in FIXTURES.glob("*.json"):
        data = json.loads(path.read_text())
        assert data.get("schema_version") == CONTRACTS_SCHEMA_VERSION, path.name
