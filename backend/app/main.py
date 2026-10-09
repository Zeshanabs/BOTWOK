"""FastAPI application factory."""
from __future__ import annotations

import importlib
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.sse import router as sse_router
from app.config import settings
from app.core.logging import configure_logging, get_logger, request_context

configure_logging(settings.log_level)
log = get_logger("app")

ROUTER_MODULES = ["auth", "workspaces", "brands", "social", "research", "competitors", "trends", "ideas", "content",
                  "campaigns", "media", "calendar", "scheduling", "publishing", "analytics", "insights", "reports",
                  "automations", "approvals", "notifications", "ai", "settings", "admin", "webhooks"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", env=settings.app_env)
    from app.workers.app import procrastinate_app
    await procrastinate_app.open_async()
    try:
        from app.events import load_consumers
        load_consumers()
    except Exception as e:  # consumers are optional in the API process
        log.warning("consumers.not_loaded", error=str(e))
    try:
        from app.integrations.storage.s3 import ensure_buckets
        await ensure_buckets()
    except Exception as e:  # storage optional during early development
        log.warning("storage.unavailable", error=str(e))
    yield
    await procrastinate_app.close_async()
    log.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="Botwok API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_context.set({"request_id": rid})
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        response.headers["Cache-Control"] = "no-store"
        log.info("http", method=request.method, path=request.url.path, status=response.status_code,
                 duration_ms=int((time.perf_counter() - start) * 1000))
        return response

    app.include_router(sse_router, prefix="/api/v1")
    for name in ROUTER_MODULES:
        try:
            mod = importlib.import_module(f"app.api.v1.{name}")
        except ModuleNotFoundError as e:
            if e.name == f"app.api.v1.{name}":
                continue
            raise
        app.include_router(mod.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()
