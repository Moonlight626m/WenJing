import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    settings = get_settings()
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

    @app.middleware("http")
    async def correlation_and_metrics(request, call_next):  # type: ignore[no-untyped-def]
        from app.diagnostics.context import bind_request, reset_ids
        from app.diagnostics.metrics import metrics, observe_latency

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

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
