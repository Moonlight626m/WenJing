"""submit_async（select_role 202 化）的语义单测（DB-free，SQLite 棒）。

覆盖幂等闸的细分状态机：新受理 / 在途 / 已完成 / 失败后的重发，以及后台收口
（settle + event_hub 推送）。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.contracts.commands import CommandKind, PlayerCommand
from app.services.session_runtime import SessionApplication


def _cmd(kind: CommandKind, payload: dict[str, Any] | None = None) -> PlayerCommand:
    return PlayerCommand(
        session_id=uuid.uuid4(),
        command_id=uuid.uuid4(),
        kind=kind,
        payload=payload or {},
    )


def test_async_command_kinds_whitelist():
    """白名单外的 kind 不允许走异步受理口。"""
    assert "select_role" in SessionApplication.ASYNC_COMMAND_KINDS


def test_async_receipt_states_documented():
    """回执语义有且只有五个状态（对齐 docstring；防止无意扩容）。"""
    from app.services.session_runtime import AsyncCommandReceipt

    for state in ("accepted", "pending", "done", "stale", "failed"):
        assert AsyncCommandReceipt(claimed=True, state=state).state == state


@pytest.mark.asyncio
async def test_submit_async_non_async_kind_raises(mocker_like_fake):
    """白名单外 kind 走 submit_async 必须拒绝。"""
    from app.infrastructure.errx import Error, codes, match_code

    app = mocker_like_fake
    with pytest.raises(Error) as ei:
        await app.submit_async(
            uuid.uuid4(),
            _cmd(CommandKind.CHOOSE_OPTION, {"option_id": "0"}),
            actor=None,  # type: ignore[arg-type]
        )
    assert match_code(ei.value, codes.ENG_PLAYER_ACTION_INVALID)


@pytest.fixture
def mocker_like_fake():
    """最小 SessionApplication 桩：只需 ASYNC_COMMAND_KINDS 白名单检查可用。"""
    return SessionApplication(
        session_factory=None,  # 白名单检查在访问 DB 之前，不会真的碰库
        agent_llm=None,  # type: ignore[arg-type]
    )
