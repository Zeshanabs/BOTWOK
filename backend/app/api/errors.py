from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import ProblemError
from app.core.logging import get_logger

log = get_logger("api")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError):
        return JSONResponse(status_code=exc.status_code, media_type="application/problem+json",
                            content={"type": f"https://botwok.dev/errors/{exc.type}", "title": exc.title, "status": exc.status_code,
                                     "detail": exc.detail, "instance": str(request.url.path), "errors": exc.errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        # plain HTTPExceptions (unknown routes, 405, auth helpers) also become Problem Details
        slug = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict",
                422: "validation_error", 429: "rate_limited"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, media_type="application/problem+json", headers=getattr(exc, "headers", None),
                            content={"type": f"https://botwok.dev/errors/{slug}", "title": str(exc.detail) if exc.detail else slug.replace("_", " ").title(),
                                     "status": exc.status_code, "detail": str(exc.detail) if exc.detail else None, "instance": str(request.url.path), "errors": []})

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"code": e.get("type"), "field": ".".join(str(x) for x in e.get("loc", [])), "message": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, media_type="application/problem+json",
                            content={"type": "https://botwok.dev/errors/validation_error", "title": "Validation failed", "status": 422,
                                     "detail": f"{len(errors)} issue(s)", "instance": str(request.url.path), "errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled", path=str(request.url.path), error=str(exc))
        return JSONResponse(status_code=500, media_type="application/problem+json",
                            content={"type": "https://botwok.dev/errors/internal", "title": "Internal error", "status": 500,
                                     "detail": "Unexpected error", "instance": str(request.url.path), "errors": []})
