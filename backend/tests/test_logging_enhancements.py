"""日志增强测试：

- 访问日志中间件：req/resp 全量落日志（log_body 开关）、4xx/5xx/未捕获异常走 error 级。
- 静默 fallback 点：上游组件构建失败回落下游前，必须落 warning。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.infrastructure.diagnostics.access_log import AccessLogMiddleware
from app.infrastructure.diagnostics.logging import configure_logging
from app.infrastructure.errx import new


class Capture(logging.Handler):
    """捕获 wenjing logger 的真实 formatter 输出。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _capture(name: str) -> Capture:
    configure_logging(json_mode=True)
    root = logging.getLogger("wenjing")
    cap = Capture()
    cap.setFormatter(root.handlers[0].formatter)
    src = logging.getLogger(name)
    src.addHandler(cap)
    return cap


def _release(name: str, cap: Capture) -> None:
    logging.getLogger(name).removeHandler(cap)


def _echo_app(*, log_body: bool = True) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict:
        body = await request.body()
        return {"echo": body.decode("utf-8")}

    @app.post("/login")
    async def login(request: Request) -> dict:
        await request.body()
        return {"ok": True}

    @app.get("/bad")
    async def bad() -> None:
        raise HTTPException(status_code=422, detail="bad input")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    app.add_middleware(AccessLogMiddleware, log_body=log_body)
    return app


# ===== 访问日志中间件 =====


def test_access_log_info_includes_req_resp_body():
    client = TestClient(_echo_app())
    cap = _capture("wenjing.api.access")
    try:
        resp = client.post("/echo", content='{"q":"课文原文"}'.encode())
        assert resp.status_code == 200
        assert resp.json() == {"echo": '{"q":"课文原文"}'}
    finally:
        _release("wenjing.api.access", cap)
    text = cap.text
    assert "api_request" in text
    assert "POST" in text and "/echo" in text
    assert '"request_body":"{\\"q\\":\\"课文原文\\"}"' in text or "课文原文" in text
    assert '"status": "200"' in text
    assert '"duration_ms"' in text
    # 响应体也全量落日志
    assert "课文原文" in text


def test_access_log_error_on_4xx_business_error():
    client = TestClient(_echo_app())
    cap = _capture("wenjing.api.access")
    try:
        resp = client.get("/bad")
        assert resp.status_code == 422
    finally:
        _release("wenjing.api.access", cap)
    assert "api_request_failed" in cap.text
    assert '"status": "422"' in cap.text


def test_access_log_error_on_unhandled_exception():
    client = TestClient(_echo_app(), raise_server_exceptions=False)
    cap = _capture("wenjing.api.access")
    try:
        resp = client.get("/boom")
        assert resp.status_code == 500
    finally:
        _release("wenjing.api.access", cap)
    text = cap.text
    assert "api_request_unhandled_exception" in text
    assert "RuntimeError" in text and "kaboom" in text


def test_access_log_redacts_credentials_in_body():
    """登录等请求 body 中的密码在日志中必须被替换为占位。"""
    client = TestClient(_echo_app())
    cap = _capture("wenjing.api.access")
    try:
        resp = client.post("/login", json={"email": "a@b.c", "password": "super-secret-pass"})
        assert resp.status_code == 200
    finally:
        _release("wenjing.api.access", cap)
    text = cap.text
    assert "super-secret-pass" not in text
    assert "<redacted>" in text


def test_access_log_body_switch_off():
    client = TestClient(_echo_app(log_body=False))
    cap = _capture("wenjing.api.access")
    try:
        resp = client.post("/echo", content=b"hello-body")
        assert resp.status_code == 200
    finally:
        _release("wenjing.api.access", cap)
    text = cap.text
    assert "api_request" in text
    assert '"status": "200"' in text
    assert "request_body" not in text
    assert "response_body" not in text


# ===== 静默 fallback 点补 warning =====


def test_routes_llm_factory_fallback_logs_warning():
    from app import composition

    class _StubSettings:
        llm_api_key = "sk-test"
        # session_application 的构造会顺带装配运行期配图调度（#56/#57），
        # 那里要读每会话生图上限与任务 TTL——这两个属性不能省。
        media_max_images_per_session = 0
        media_asset_job_ttl_seconds = 900

        @staticmethod
        def llm_model_config():
            # errx Error 没有 .model 属性 → ModelServiceFactory.build 抛 AttributeError
            return new(999001)

    orig_settings = composition.get_settings
    composition.get_settings = lambda: _StubSettings
    composition.reset_container()
    cap = _capture("wenjing.composition")
    try:
        app_obj = composition.get_container().session_application
        from app.infrastructure.llm.fake import DeterministicAgentLLM

        assert isinstance(app_obj._agent_llm, DeterministicAgentLLM)
    finally:
        _release("wenjing.composition", cap)
        composition.get_settings = orig_settings
        composition.reset_container()
    assert "llm_factory_build_failed_fallback_fake" in cap.text


def test_scripts_llm_fallback_logs_warning():
    from app import composition

    class _StubSettings:
        llm_api_key = "sk-test"
        llm_model = ""
        rag_search_provider = "null"
        # #48 后 ScriptLibrary 的 scene_designer 经 lambda 延迟构建，
        # 构造期不再触碰媒体配置；stub 无需 media_* 属性（与上面那条不同：
        # session_application 会在构造期装配配图调度，所以那边必须给）。

        @staticmethod
        def llm_model_config():
            return new(999001)

    orig_settings = composition.get_settings
    composition.get_settings = lambda: _StubSettings
    composition.reset_container()
    cap = _capture("wenjing.composition")
    try:
        library = composition.get_container().script_library
        assert library._script_llm is None
    finally:
        _release("wenjing.composition", cap)
        composition.get_settings = orig_settings
        composition.reset_container()
    assert "script_llm_build_failed_fallback_degraded" in cap.text


def test_rag_search_failure_logs_warning():
    from app.infrastructure.rag.service import RagService

    class _BoomSearch:
        async def search(self, query, limit=3):
            raise RuntimeError("network down")

    svc = RagService(search_provider=_BoomSearch())
    cap = _capture("wenjing.rag.service")
    try:
        import asyncio

        evidence = asyncio.run(svc.research("背影"))
        assert evidence == []
    finally:
        _release("wenjing.rag.service", cap)
    assert "rag_search_failed_degrade_to_source_only" in cap.text
