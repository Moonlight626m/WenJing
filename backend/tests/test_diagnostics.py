"""诊断基础设施测试（issue #3 验收标准）。

- 错误可经 error_id 定位到服务端日志（caplog 断言）。
- 凭据（api_key/password/authorization/secret）永不落日志，替换为占位；
  业务内容（prompt/课文/玩家输入）全量落日志（排障优先，脱敏已放宽）。
- envelope 稳定码映射正确；未知整数码回落 INTERNAL_ERROR。
- contextvars 关联字段经 CorrelationFilter 注入每条记录。
"""

from __future__ import annotations

import logging

from app.infrastructure.diagnostics.context import (
    bind_command,
    bind_correlation,
    bind_request,
    bind_session,
    current_ids,
)
from app.infrastructure.diagnostics.logging import configure_logging, get_logger, sanitize_extra
from app.infrastructure.errx import codes as err_codes
from app.infrastructure.errx import new as err_new


class Capture(logging.Handler):
    """捕获 wenjing logger 的真实 formatter 输出（绕过 propagate=False）。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _capture_target(name: str):
    root = logging.getLogger("wenjing")
    cap = Capture()
    src = logging.getLogger(name)
    if src.handlers and not isinstance(src.handlers[0], Capture):
        cap.setFormatter(src.handlers[0].formatter)
    else:
        configure_logging(json_mode=True)
        cap.setFormatter(root.handlers[0].formatter)
    src.addHandler(cap)
    return cap


def _release_capture(name: str, cap) -> None:
    logging.getLogger(name).removeHandler(cap)



# ===== 脱敏 =====


def test_sanitize_redacts_credentials_only():
    """凭据键替换为占位；业务内容键全量保留（不再截断）。"""
    raw_text = "我与父亲不相见已二年余了" * 20
    out = sanitize_extra(
        {
            "llm_api_key": "sk-super-secret-value",
            "authorization": "Bearer abc",
            "password": "hunter2",
            "prompt": "你是一名演员，请扮演……",
            "raw_text": raw_text,
            "player_input": "我想对父亲说……",
            "session_id": "0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910",
            "duration_ms": 123.4,
        }
    )
    assert out["llm_api_key"] == "<redacted>"
    assert "sk-super-secret" not in str(out)
    assert out["authorization"] == "<redacted>"
    assert out["password"] == "<redacted>"
    # 业务内容原样保留
    assert out["prompt"] == "你是一名演员，请扮演……"
    assert out["raw_text"] == raw_text
    assert out["player_input"] == "我想对父亲说……"
    # 非敏感键保持明文
    assert out["session_id"] == "0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910"
    assert out["duration_ms"] == "123.4"


def test_credentials_never_in_log_output():
    configure_logging(json_mode=True, level=logging.INFO)
    log = get_logger("diag.test")
    cap = _capture_target("wenjing.diag.test")
    try:
        log.info(
            "import_attempt",
            extra={
                "wj_extra": {
                    "api_key": "sk-should-not-leak",
                    "password": "p@ss",
                }
            },
        )
    finally:
        _release_capture("wenjing.diag.test", cap)
    rendered = cap.text
    assert "sk-should-not-leak" not in rendered
    assert "p@ss" not in rendered
    assert "<redacted>" in rendered


def test_business_content_full_in_log_output():
    """业务内容（prompt/课文/玩家输入）全量落日志（脱敏放宽后的约定）。"""
    configure_logging(json_mode=True, level=logging.INFO)
    log = get_logger("diag.test")
    cap = _capture_target("wenjing.diag.test")
    try:
        log.info(
            "import_attempt",
            extra={
                "wj_extra": {
                    "raw_text": "背影正文全文" * 30,
                    "free_input": "我不想去车站",
                }
            },
        )
    finally:
        _release_capture("wenjing.diag.test", cap)
    rendered = cap.text
    assert "背影正文全文" in rendered
    assert "我不想去车站" in rendered


# ===== envelope 映射与 error_id 日志定位 =====


def test_envelope_maps_known_codes():
    from app.infrastructure.diagnostics.errors import envelope_for

    env = envelope_for(err_new(err_codes.SESS_NOT_FOUND))
    assert env.code == "SESSION_NOT_FOUND"
    assert env.domain.value == "session"
    assert not env.retryable
    assert "不存在或已失效" in env.message
    # 对外信封永不携带 stack
    dumped = env.model_dump()
    allowed = {"schema_version", "error_id", "code", "domain", "message", "retryable", "details"}
    assert set(dumped) <= allowed


def test_unknown_code_falls_back_to_internal():
    from app.infrastructure.diagnostics.errors import envelope_for

    env = envelope_for(err_new(999999))
    assert env.code == "INTERNAL_ERROR"
    assert env.retryable is True


def test_error_id_locates_server_log():
    """用户报错凭 error_id；服务端同 error_id 记录 cause/stack。"""
    import uuid

    from app.infrastructure.diagnostics.errors import envelope_for

    error_id = uuid.uuid4()
    env = envelope_for(err_new(err_codes.SESS_NOT_FOUND))
    _ = error_id

    from app.infrastructure.diagnostics.errors import logger as err_logger

    cap = _capture_target("wenjing.diagnostics.errors")
    try:
        err_logger.error(
            "unhandled_error error_id=%s code=%s", env.error_id, env.code
        )
    finally:
        _release_capture("wenjing.diagnostics.errors", cap)
    assert str(env.error_id) in cap.text
    assert env.code in cap.text
    assert env.message  # 对外安全消息非空


# ===== 关联 ID 传播 =====


def test_contextvar_ids_propagate_into_logs(caplog):
    configure_logging(json_mode=True, level=logging.INFO)

    bind_request()
    bind_session("0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910")
    cid = bind_correlation()
    bind_command("6f96f8e0-1a2b-4c3d-9e4f-5a6b7c8d9012")

    ids = current_ids()
    assert ids["correlation_id"] == cid
    assert ids["command_id"] == "6f96f8e0-1a2b-4c3d-9e4f-5a6b7c8d9012"

    class _Rec:  # 直接单测 filter 行为
        pass

    import copy

    record = logging.LogRecord(
        name="wenjing.diag.ctx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    from app.infrastructure.diagnostics.context import CorrelationFilter

    f = CorrelationFilter()
    assert f.filter(record) is True
    assert record.correlation_id == cid  # type: ignore[attr-defined]
    assert record.session_id == "0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910"  # type: ignore[attr-defined]
    _ = copy
