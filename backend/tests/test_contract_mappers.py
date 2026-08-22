"""Shared Contracts mapper 契约测试：领域模型 → REST/WS DTO 的显式映射。

对应 ticket #2 验收：REST/WebSocket DTO 与领域模型分离，显式 mapper 契约已成型。
DTO 是设备边界；mapper 是唯一转换路径，禁止在路由中手工捏造 DTO。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.contracts import ErrorCode, ErrorEnvelope, GameStage, GenreKind, InteractionMode
from app.contracts.mappers import (
    make_error,
    material_to_view,
    script_to_view,
    update_to_runtime_view,
)
from app.contracts.material import Material
from app.contracts.protocol import MaterialView, RuntimeView, ScriptView
from app.contracts.runtime import InteractionPoint, RuntimeState, RuntimeUpdate
from app.contracts.script import CharacterSetting, Scene, ScriptPackage, Stage2Beat


def _ts() -> datetime:
    return datetime.now(UTC)


def _material() -> Material:
    return Material(
        material_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        raw_text="样例课文",
        content_hash="c" * 64,
        genre=GenreKind.NARRATIVE_PROSE,
        created_at=_ts(),
    )


def _script() -> ScriptPackage:
    beat = Stage2Beat(
        beat_id=1,
        title="t",
        description="d",
        evidence=[{"source_type": "original", "excerpt": "e", "paragraph_id": 1}],
    )
    return ScriptPackage(
        script_id=uuid.uuid4(),
        title="样例剧本",
        genre=GenreKind.NARRATIVE_PROSE,
        characters=[CharacterSetting(name="小芸", role="主角")],
        scenes=[Scene(scene_id=1, title="s", setting="st")],
        stage2_beats=[beat],
        teaching_focus=["f"],
        player_playable_roles=["小芸"],
        stage2_ending_beat_id=1,
    )


def test_material_to_view_maps_fields():
    m = _material()
    view = material_to_view(m)
    assert isinstance(view, MaterialView)
    assert view.material_id == m.material_id
    assert view.session_id == m.session_id
    assert view.content_hash == m.content_hash
    assert view.genre is GenreKind.NARRATIVE_PROSE
    assert view.char_count == len("样例课文")


def test_script_to_view_wraps_package():
    pkg = _script()
    assert isinstance(script_to_view(pkg), ScriptView)
    assert script_to_view(pkg).script is pkg


def test_update_to_runtime_view_maps_state_and_interaction():
    session_id = uuid.uuid4()
    state = RuntimeState(
        session_id=session_id,
        active_branch_id=uuid.uuid4(),
        stage=GameStage.STAGE2_REENACTING,
        head_event_id=3,
        event_count=4,
    )
    upd = RuntimeUpdate(
        state=state,
        interaction=InteractionPoint(
            mode=InteractionMode.OPTIONS, prompt="请选择", options=["a", "b"]
        ),
    )
    view = update_to_runtime_view(session_id, upd)
    assert isinstance(view, RuntimeView)
    assert view.stage is GameStage.STAGE2_REENACTING
    assert view.interaction is not None
    assert view.allowed_commands == []
    assert view.event_count == 4
    assert view.head_event_id == 3


def test_make_error_builds_envelope():
    env = make_error(ErrorCode.INPUT_EMPTY, "文本为空", details={"field": "raw_text"})
    assert isinstance(env, ErrorEnvelope)
    assert env.code is ErrorCode.INPUT_EMPTY
    assert env.details == {"field": "raw_text"}
    assert env.retryable is False


def test_make_error_honors_retryable_and_error_id():
    env = make_error(ErrorCode.LLM_TIMEOUT, "超时", retryable=True, error_id="fixed-id")
    assert env.retryable is True
    assert env.error_id == "fixed-id"
