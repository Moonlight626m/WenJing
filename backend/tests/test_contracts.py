"""Shared Contracts 契约层测试：版本化类型、命令集合、每阶段 allowed_commands、
错误 envelope 与领域不变量。

对应 ticket #2：
- 定义 MaterialInput/Material、EvidenceRef、ScriptPackage、PlayerCommand、
  DomainEvent、RuntimeState、GameSnapshot、RuntimeUpdate、ErrorEnvelope 的版本化类型
- 命令类型集合与每阶段 allowed_commands 已定义
- 错误 envelope 含 error_id/code/message/retryable/details；
  错误码域覆盖 INPUT/CONTENT/SEARCH/LLM/GAME/SESSION/PERSISTENCE/PROTOCOL/INTERNAL
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from app.contracts import (
    ALLOWED_COMMANDS,
    CharacterSetting,
    CommandType,
    DomainEvent,
    ErrorCode,
    ErrorDomains,
    ErrorEnvelope,
    EvidenceRef,
    GameSnapshot,
    GameStage,
    GenreKind,
    InteractionMode,
    InteractionPoint,
    Material,
    MaterialInput,
    OriginalEvidenceRef,
    PlayerCommand,
    RuntimeState,
    RuntimeStatus,
    RuntimeUpdate,
    Scene,
    ScriptPackage,
    Stage2Beat,
    WebEvidenceRef,
)


def _ts() -> datetime:
    return datetime.now(UTC)


def _sample_material_input() -> MaterialInput:
    return MaterialInput(raw_text="  巷口的修鞋摊\n\n陈师傅修了三十年鞋。  ", source_type="paste")


def _sample_original_evidence() -> OriginalEvidenceRef:
    return OriginalEvidenceRef(
        excerpt="陈师傅修了三十年鞋",
        paragraph_id=1,
        char_start=4,
        char_end=14,
    )


def _sample_material() -> Material:
    return Material(
        material_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        raw_text="巷口的修鞋摊\n\n陈师傅修了三十年鞋。",
        content_hash="a" * 64,
        genre=GenreKind.NARRATIVE_PROSE,
        created_at=_ts(),
    )


def _sample_script() -> ScriptPackage:
    beat = Stage2Beat(
        beat_id=1,
        title="雨夜捡到戒指",
        description="雨夜，陈师傅在巷口捡到一枚银戒指。",
        evidence=[_sample_original_evidence()],
    )
    return ScriptPackage(
        script_id=uuid.uuid4(),
        title="巷口的修鞋摊",
        genre=GenreKind.NARRATIVE_PROSE,
        characters=[CharacterSetting(name="陈师傅", role="修鞋匠", is_player_playable=True)],
        scenes=[Scene(scene_id=1, title="巷口", setting="雨天", beats=[beat])],
        stage2_beats=[beat],
        teaching_focus=["关键事件还原", "细节描写"],
        player_playable_roles=["陈师傅"],
        stage2_ending_beat_id=1,
        stage3_resume="小芸认出戒指后，与陈师傅继续对话……",
    )


def _sample_update() -> RuntimeUpdate:
    state = RuntimeState(session_id=uuid.uuid4(), active_branch_id=uuid.uuid4())
    return RuntimeUpdate(
        state=state,
        interaction=InteractionPoint(
            mode=InteractionMode.OPTIONS, prompt="请选择"
        ),
    )


# ===== 版本化类型 =====


def test_material_input_trims_and_rejects_empty():
    m = _sample_material_input()
    assert m.raw_text.startswith("巷口")
    assert m.raw_text.endswith("。")
    m2 = MaterialInput(raw_text="  ", source_type="paste")
    assert m2.raw_text == ""


def test_material_input_too_large_rejected():
    with pytest.raises(ValidationError):
        MaterialInput(raw_text="x" * (1_000_001), source_type="paste")


def test_material_input_file_requires_filename():
    with pytest.raises(ValidationError):
        MaterialInput(raw_text="text", source_type="file")


def test_material_input_unknown_source_rejected():
    with pytest.raises(ValidationError):
        MaterialInput(raw_text="text", source_type="audio")


def test_material_schema_version_defaults_to_1():
    m = _sample_material()
    assert m.schema_version == 1
    assert len(m.content_hash) == 64


def test_evidence_ref_discriminates_on_source_type():
    _adapter = TypeAdapter(EvidenceRef)
    original = _adapter.validate_python(_sample_original_evidence().model_dump())
    assert original.source_type == "original"
    web = _adapter.validate_python(
        {
            "source_type": "web",
            "url": "https://example.com/lesson",
            "title": "课文背景",
            "retrieved_at": _ts().isoformat(),
            "content_hash": "b" * 64,
            "excerpt": "作者生平",
        }
    )
    assert isinstance(web, WebEvidenceRef)
    assert str(web.url) == "https://example.com/lesson"


def test_web_evidence_rejects_non_http_url():
    with pytest.raises(ValidationError):
        WebEvidenceRef(
            source_type="web",
            url="file:///etc/passwd",
            title="t",
            retrieved_at=_ts(),
            content_hash="b" * 64,
            excerpt="e",
        )


def test_original_evidence_requires_excerpt():
    with pytest.raises(ValidationError):
        OriginalEvidenceRef(source_type="original", excerpt="")


# ===== ScriptPackage 不变量 =====


def test_script_package_playable_roles_must_be_characters():
    with pytest.raises(ValidationError):
        broken = _sample_script().model_copy(
            update={"player_playable_roles": ["不存在的人"]}
        )
        ScriptPackage.model_validate(broken.model_dump())


def test_script_package_stage2_ending_beat_must_exist():
    with pytest.raises(ValidationError):
        ScriptPackage.model_validate(
            _sample_script().model_copy(update={"stage2_ending_beat_id": 99}).model_dump()
        )


def test_script_package_stage2_beats_require_original_evidence():
    with pytest.raises(ValidationError):
        ScriptPackage.model_validate(
            _sample_script().model_copy(
                update={
                    "stage2_beats": [
                        Stage2Beat(beat_id=9, title="t", description="d", evidence=[])
                    ]
                }
            ).model_dump()
        )


# ===== 命令集合与 allowed_commands =====


def test_command_type_set_is_frozen():
    assert set(CommandType) == {
        CommandType.CHOOSE_OPTION,
        CommandType.FREE_INPUT,
        CommandType.ROLLBACK,
        CommandType.CONFIRM_STAGE2_ENDING,
        CommandType.DECLINE_STAGE3,
        CommandType.END_GAME,
    }


def test_allowed_commands_covers_every_stage():
    assert set(ALLOWED_COMMANDS) == set(GameStage)


def test_allowed_commands_stage2_reenacting():
    allowed = ALLOWED_COMMANDS[GameStage.STAGE2_REENACTING]
    assert CommandType.CHOOSE_OPTION in allowed
    assert CommandType.FREE_INPUT in allowed
    assert CommandType.ROLLBACK in allowed
    assert CommandType.CONFIRM_STAGE2_ENDING not in allowed


def test_allowed_commands_ended_is_empty():
    assert ALLOWED_COMMANDS[GameStage.ENDED] == frozenset()


def test_allowed_commands_initial_stages_have_no_game_commands():
    for stage in (GameStage.INIT, GameStage.STAGE1_CREATING, GameStage.STAGE1_COMPLETE):
        assert ALLOWED_COMMANDS[stage] == frozenset()


def test_player_command_payload_validated_per_type():
    base = dict(command_id=uuid.uuid4(), session_id=uuid.uuid4(), issued_at=_ts())
    ok = PlayerCommand(type=CommandType.CHOOSE_OPTION, payload={"option_index": 1}, **base)
    assert ok.type is CommandType.CHOOSE_OPTION
    with pytest.raises(ValidationError):
        PlayerCommand(type=CommandType.CHOOSE_OPTION, payload={"option_index": -1}, **base)
    with pytest.raises(ValidationError):
        PlayerCommand(type=CommandType.FREE_INPUT, payload={"text": ""}, **base)
    with pytest.raises(ValidationError):
        PlayerCommand(type=CommandType.ROLLBACK, payload={}, **base)
    ok_rb = PlayerCommand(type=CommandType.ROLLBACK, payload={"steps": 2}, **base)
    assert ok_rb.payload["steps"] == 2


# ===== DomainEvent =====


def test_domain_event_required_fields_and_schema_version():
    ev = DomainEvent(
        event_id=1,
        session_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        sequence=1,
        type="stage_transitioned",
        causation_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        timestamp=_ts(),
    )
    assert ev.schema_version == 1
    assert ev.type == "stage_transitioned"
    with pytest.raises(ValidationError):
        DomainEvent(
            event_id=1,
            session_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            type="stage_transitioned",
            causation_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            timestamp=_ts(),
        )  # 缺 sequence


# ===== RuntimeState / GameSnapshot / RuntimeUpdate =====


def test_runtime_state_serializable_defaults():
    state = RuntimeState(session_id=uuid.uuid4(), active_branch_id=uuid.uuid4())
    assert state.stage is GameStage.INIT
    assert state.head_event_id == 0
    assert state.event_count == 0
    assert state.beat_index == 0
    assert state.stage2_ending_confirmed is False
    assert state.stage3_round_taken == 0
    assert state.schema_version == 1
    # 可序列化：json roundtrip 不丢字段
    assert RuntimeState.model_validate_json(state.model_dump_json()) == state


def test_runtime_state_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RuntimeState(session_id=uuid.uuid4(), active_branch_id=uuid.uuid4(), websocket=None)


def test_game_snapshot_wraps_runtime_state():
    state = RuntimeState(session_id=uuid.uuid4(), active_branch_id=uuid.uuid4())
    snap = GameSnapshot(
        snapshot_id=uuid.uuid4(),
        session_id=state.session_id,
        branch_id=state.active_branch_id,
        event_id=5,
        state=state,
    )
    assert snap.state is state
    assert snap.event_id == 5


def test_runtime_update_defaults():
    upd = _sample_update()
    assert upd.status is RuntimeStatus.RUNNING
    assert upd.allowed_commands == frozenset()
    assert upd.interaction is not None


# ===== 错误 envelope =====


def test_error_domains_covered():
    domains = {d for d in ErrorDomains}
    assert domains == {
        "INPUT",
        "CONTENT",
        "SEARCH",
        "LLM",
        "GAME",
        "SESSION",
        "PERSISTENCE",
        "PROTOCOL",
        "INTERNAL",
    }


def test_every_error_code_belongs_to_a_domain():
    domains = {d.value for d in ErrorDomains}
    for code in ErrorCode:
        prefix = code.value.split("_", 1)[0]
        assert prefix in domains


def test_error_envelope_fields():
    env = ErrorEnvelope(code=ErrorCode.CONTENT_UNSUPPORTED_GENRE, message="当前仅支持叙事类课文")
    assert len(env.error_id) == 36  # uuid
    assert env.retryable is False
    assert env.details == {}
    assert env.schema_version == 1
    with pytest.raises(ValidationError):
        ErrorEnvelope(code=ErrorCode.INTERNAL_ERROR, message="x", unexpected=True)


def test_error_envelope_retryable_flag():
    env = ErrorEnvelope(
        code=ErrorCode.INTERNAL_ERROR, message="llm down", retryable=True
    )
    assert env.retryable is True
