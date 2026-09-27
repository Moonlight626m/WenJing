import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.composition import get_container
from app.controllers.admin import router as admin_router
from app.controllers.auth import router as auth_router
from app.controllers.errors import error_response
from app.controllers.routes import router
from app.controllers.scripts import router as scripts_router
from app.infrastructure.config import get_settings
from app.infrastructure.errx import Error as WJError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 组合根建立事件循环绑定资源（生成 workflow checkpointer，issue #28）。
    container = get_container()
    await container.open()
    try:
        yield
    finally:
        await container.close()


def create_app() -> FastAPI:
    from app.infrastructure.diagnostics.logging import configure_logging

    settings = get_settings()
    configure_logging(debug=settings.debug)
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip() for o in settings.cors_origins.split(",") if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(scripts_router)
    app.include_router(admin_router)

    @app.exception_handler(WJError)
    async def _wj_error_handler(request: Request, exc: WJError) -> JSONResponse:
        return error_response(exc)

    @app.middleware("http")
    async def correlation_and_metrics(request, call_next):  # type: ignore[no-untyped-def]
        from app.infrastructure.diagnostics.context import bind_request, reset_ids
        from app.infrastructure.diagnostics.metrics import metrics, observe_latency

        reset_ids()
        req_id = bind_request()
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        observe_latency(metrics, "wenjing_command", time.perf_counter() - started)
        metrics.inc("wenjing_requests_total")
        if response.status_code >= 500:
            metrics.inc("wenjing_errors_total")
        return response

    # 访问日志中间件放最外层（后注册的先执行），能看到经异常处理器转换后的最终状态码
    from app.infrastructure.diagnostics.access_log import AccessLogMiddleware

    app.add_middleware(AccessLogMiddleware, log_body=settings.log_body)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
