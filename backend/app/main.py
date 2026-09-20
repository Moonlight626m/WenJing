import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.controllers.admin import router as admin_router
from app.controllers.auth import router as auth_router
from app.controllers.errors import error_response
from app.controllers.routes import router
from app.controllers.scripts import router as scripts_router
from app.infrastructure.config import get_settings
from app.infrastructure.errx import Error as WJError

logger = logging.getLogger("wenjing.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 生成 workflow 的 checkpointer（issue #28）：psycopg（非 asyncpg）连接，
    # setup() 幂等建 checkpointer 四表（saver 自管迁移，与 Alembic 无关）。
    settings = get_settings()
    checkpoint_pool = (
        await _open_checkpointer(settings.database_url) if settings.llm_api_key else None
    )
    try:
        yield
    finally:
        if checkpoint_pool is not None:
            await checkpoint_pool.close()


async def _open_checkpointer(database_url: str):
    """async 创建 AsyncPostgresSaver 并注册；只捕连接/建表异常（注入/配置错误显式暴露）。

    PG 不可达时降级返回 None：workflow 无 checkpointer 也可跑（闸门恢复 #34 完整启用）。
    """
    from app.controllers.scripts import set_generation_checkpointer

    pool = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        conninfo = database_url.replace("+asyncpg", "")
        pool = AsyncConnectionPool(conninfo=conninfo, open=False, min_size=1)
        saver = AsyncPostgresSaver(pool)
        await pool.open()
        await saver.setup()
        set_generation_checkpointer(saver)
        return pool
    except Exception as exc:  # noqa: BLE001
        logger.warning("generation_checkpointer_setup_failed_degraded reason=%s", exc)
        if pool is not None:
            # 连接失败时回收已创建的 pool，防泄漏
            await pool.close()
        return None


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
