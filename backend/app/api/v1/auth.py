"""Auth routes: signup, login, refresh (rotating httpOnly cookie), logout, me, password reset."""
from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.deps import DB, CurrentUser
from app.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.schemas.identity import (
    LoginRequest,
    MembershipOut,
    MeOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
    WorkspaceOut,
)
from app.services.auth_service import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    AuthService,
    IssuedSession,
)

log = get_logger("api.auth")

AUTH_RATE_LIMIT = 20  # requests per minute per IP (doc 17 §17.1)


async def check_auth_rate_limit(request: Request, limit: int = AUTH_RATE_LIMIT) -> int | None:
    """Fixed 1-minute window per client IP. Returns Retry-After seconds when limited, else None. Fails open."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    key = f"rl:auth:{ip}:{int(now // 60)}"
    try:
        r = get_redis()
        n = int(await r.incr(key))
        if n == 1:
            await r.expire(key, 70)
    except Exception as e:
        log.warning("ratelimit.unavailable", error=str(e))
        return None
    if n > limit:
        return max(1, 60 - int(now % 60))
    return None


class AuthRateLimitedRoute(APIRoute):
    """Applies the per-IP auth rate limit to every non-GET route and answers 429 with Retry-After."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            if request.method != "GET":
                retry = await check_auth_rate_limit(request)
                if retry is not None:
                    return JSONResponse(status_code=429, media_type="application/problem+json", headers={"Retry-After": str(retry)},
                                        content={"type": "https://botwok.dev/errors/rate_limited", "title": "Too many requests",
                                                 "status": 429, "detail": f"Retry in {retry}s", "instance": request.url.path,
                                                 "errors": []})
            return await original(request)

        return handler


router = APIRouter(prefix="/auth", tags=["auth"], route_class=AuthRateLimitedRoute)


def _client(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), (request.client.host if request.client else None)


def set_auth_cookies(response: Response, issued: IssuedSession) -> None:
    secure = not settings.is_local
    response.set_cookie(REFRESH_COOKIE, issued.refresh_token, max_age=settings.refresh_token_days * 86400, httponly=True,
                        secure=secure, samesite="lax", path=REFRESH_COOKIE_PATH)
    response.set_cookie(ACCESS_COOKIE, issued.access_token, max_age=issued.expires_in, httponly=True, secure=secure,
                        samesite="lax", path="/")


def clear_auth_cookies(response: Response) -> None:
    secure = not settings.is_local
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, secure=secure, samesite="lax")
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, secure=secure, samesite="lax")


def _token_response(issued: IssuedSession) -> TokenResponse:
    ws = WorkspaceOut.model_validate(issued.workspace).model_copy(update={"role": issued.role}) if issued.workspace else None
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in, user=UserOut.model_validate(issued.user),
                         workspace=ws, role=issued.role)


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, request: Request, response: Response, db: DB) -> TokenResponse:
    ua, ip = _client(request)
    issued = await AuthService.signup(db, email=body.email, password=body.password, full_name=body.full_name,
                                      workspace_name=body.workspace_name, invitation_token=body.invitation_token,
                                      user_agent=ua, ip=ip, request=request)
    await db.commit()
    set_auth_cookies(response, issued)
    return _token_response(issued)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response, db: DB) -> TokenResponse:
    ua, ip = _client(request)
    issued = await AuthService.login(db, email=body.email, password=body.password, workspace_id=body.workspace_id,
                                     user_agent=ua, ip=ip, request=request)
    await db.commit()
    set_auth_cookies(response, issued)
    return _token_response(issued)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: DB, body: RefreshRequest | None = None,
                  x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id")) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None)
    ws_id = body.workspace_id if body and body.workspace_id else None
    if ws_id is None and x_workspace_id:
        try:
            ws_id = UUID(x_workspace_id)
        except ValueError:
            ws_id = None
    ua, ip = _client(request)
    issued = await AuthService.refresh(db, token, workspace_id=ws_id, user_agent=ua, ip=ip, request=request)
    await db.commit()
    set_auth_cookies(response, issued)
    return _token_response(issued)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DB, body: RefreshRequest | None = None) -> None:
    token = request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None)
    await AuthService.logout(db, token, request=request)
    await db.commit()
    clear_auth_cookies(response)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, db: DB) -> MeOut:
    data = await AuthService.me(db, user)
    return MeOut(user=UserOut.model_validate(data["user"]),
                 memberships=[MembershipOut(workspace=WorkspaceOut.model_validate(m["workspace"]).model_copy(update={"role": m["role"]}),
                                            role=m["role"]) for m in data["memberships"]])


@router.post("/password/reset", status_code=202)
async def password_reset(body: PasswordResetRequest, request: Request, db: DB) -> dict[str, str]:
    await AuthService.request_password_reset(db, body.email, request=request)
    await db.commit()
    return {"status": "accepted", "detail": "If an account exists for this email, a reset link has been sent."}


@router.post("/password/reset/confirm", status_code=200)
async def password_reset_confirm(body: PasswordResetConfirm, request: Request, response: Response, db: DB) -> dict[str, str]:
    await AuthService.confirm_password_reset(db, body.token, body.new_password, request=request)
    await db.commit()
    clear_auth_cookies(response)
    return {"status": "ok", "detail": "Password updated; please sign in again."}


@router.post("/verify-email", status_code=202)
async def verify_email() -> dict[str, str]:
    """Optional email verification (when SMTP is configured) — stub for now."""
    return {"status": "accepted"}
