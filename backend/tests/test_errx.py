"""errx 错误体系单测。"""

from __future__ import annotations

import pytest

from app.errx import codes, lookup, match_code, new, register, wrap


def test_new_uses_predefined_message_and_extra():
    e = new(codes.ENG_INVALID_TRANSITION, extra={"src": "a", "dst": "b"})
    assert e.code == codes.ENG_INVALID_TRANSITION
    assert e.msg == "invalid stage transition from a to b"


def test_new_unknown_code_falls_back():
    e = new(99999)
    assert e.msg == "Service Internal Error"


def test_register_overrides():
    register(77777, "custom {who}")
    assert lookup(77777).message == "custom {who}"
    e = new(77777, extra={"who": "me"})
    assert e.msg == "custom me"


def test_wrap_preserves_cause_and_code():
    base = ValueError("boom")
    w = wrap(base, codes.LLM_CALL_FAILED, extra={"reason": "boom"})
    assert w.cause is base
    assert w.code == codes.LLM_CALL_FAILED
    assert match_code(w, codes.LLM_CALL_FAILED)


def test_wrap_is_not_affect_stability_for_session_errors():
    e = new(codes.SESS_NOT_FOUND, extra={"id": "x"})
    assert e.is_affect_stability is False


def test_match_code_along_cause_chain():
    base = ValueError("inner")
    inner = wrap(base, codes.LLM_CALL_FAILED, extra={"reason": "inner"})
    outer = wrap(inner, codes.ENG_NOT_RUNNING, extra={"session_id": "s"})
    assert match_code(outer, codes.LLM_CALL_FAILED)
    assert match_code(outer, codes.ENG_NOT_RUNNING)
    assert not match_code(outer, codes.ENG_INVALID_TRANSITION)


def test_error_is_exception_and_raiseable():
    with pytest.raises(Exception) as ei:
        raise new(codes.ENG_PLAYER_ACTION_INVALID, extra={"reason": "missing"})
    assert ei.value.code == codes.ENG_PLAYER_ACTION_INVALID
    assert "missing" in ei.value.msg
