"""契约 payload → 引擎 payload 的翻译（`SessionApplication._engine_payload`）。

钉住四种带参命令与空参命令的映射：漏翻会让运行时收到空 payload（例如
`switch_scene` 的 `scene_key` 丢成空串，换景永远失败）。
"""

from __future__ import annotations

import uuid

from app.contracts.commands import CommandKind, PlayerCommand
from app.infrastructure.db.event_store import PersistentEventStore
from app.services.session_runtime import SessionApplication


def _cmd(kind: CommandKind, payload: dict) -> PlayerCommand:
    return PlayerCommand(
        command_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind=kind,
        payload=payload,
    )


def _payload(kind: CommandKind, payload: dict) -> dict:
    return SessionApplication._engine_payload(
        uuid.uuid4(), _cmd(kind, payload), PersistentEventStore()
    )


def test_select_role_and_option_and_text():
    assert _payload(CommandKind.SELECT_ROLE, {"role_name": "我"}) == {"role_name": "我"}
    assert _payload(CommandKind.CHOOSE_OPTION, {"option_id": "o1"}) == {"option_id": "o1"}
    assert _payload(CommandKind.FREE_INPUT, {"text": "你好"}) == {"text": "你好"}


def test_switch_scene_keeps_scene_key():
    assert _payload(CommandKind.SWITCH_SCENE, {"scene_key": "loc:home"}) == {
        "scene_key": "loc:home"
    }


def test_intervene_keeps_text():
    assert _payload(CommandKind.INTERVENE, {"text": "把灯点亮"}) == {"text": "把灯点亮"}


def test_empty_payload_kinds():
    for kind in (CommandKind.ENTER_STAGE3, CommandKind.CONFIRM_ENDING, CommandKind.EXIT_GAME):
        assert _payload(kind, {}) == {}
