"""Identity API integration tests against the real local Postgres + Redis (skipped when unreachable)."""
from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from app.config import settings

pytestmark = pytest.mark.integration


def _services_reachable() -> bool:
    try:
        import psycopg
        with psycopg.connect(settings.database_url_sync, connect_timeout=2) as conn:
            conn.execute("SELECT 1 FROM users LIMIT 1")
        import redis
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


if not _services_reachable():
    pytest.skip("Postgres/Redis not reachable (or schema not migrated)", allow_module_level=True)

PASSWORD = "correct-horse-battery"


class Api:
    def __init__(self, client: httpx.AsyncClient, emails: list[str]) -> None:
        self.c = client
        self.emails = emails

    def email(self) -> str:
        e = f"it-{uuid.uuid4().hex[:12]}@example.test"
        self.emails.append(e)
        return e

    async def signup(self, email: str | None = None, **extra) -> httpx.Response:
        r = await self.c.post("/api/v1/auth/signup", json={"email": email or self.email(), "password": PASSWORD, **extra})
        self.c.cookies.clear()
        return r

    async def post(self, path: str, token: str | None = None, cookie: str | None = None, **kw) -> httpx.Response:
        headers = dict(kw.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if cookie:
            headers["Cookie"] = f"botwok_refresh={cookie}"
        r = await self.c.post(path, headers=headers, **kw)
        self.c.cookies.clear()
        return r

    async def req(self, method: str, path: str, token: str, ws: str | None = None, **kw) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"}
        if ws:
            headers["X-Workspace-Id"] = ws
        r = await self.c.request(method, path, headers=headers, **kw)
        self.c.cookies.clear()
        return r


def refresh_cookie(r: httpx.Response) -> str:
    for h in r.headers.get_list("set-cookie"):
        if h.startswith("botwok_refresh="):
            assert "HttpOnly" in h and "Path=/api/v1/auth" in h and "samesite=lax" in h.lower()
            return h.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("no refresh cookie")


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    from sqlalchemy import text

    from app.core import db as core_db
    from app.core import redis as core_redis
    from app.main import app

    await core_db.engine.dispose(close=False)  # drop connections bound to other event loops
    core_redis._client = None
    ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    emails: list[str] = []
    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield Api(client, emails)
    if emails:
        async with core_db.SessionLocal() as db:
            await db.execute(text("DELETE FROM workspaces WHERE id IN (SELECT wm.workspace_id FROM workspace_members wm "
                                  "JOIN users u ON u.id = wm.user_id WHERE u.email = ANY(:e))"), {"e": emails})
            await db.execute(text("DELETE FROM workspaces WHERE created_by IN (SELECT id FROM users WHERE email = ANY(:e))"),
                             {"e": emails})
            await db.execute(text("DELETE FROM users WHERE email = ANY(:e)"), {"e": emails})
            await db.commit()
        r = core_redis.get_redis()
        await r.delete(*[f"auth:fail:{e}" for e in emails])
    if core_redis._client is not None:
        await core_redis._client.aclose()
        core_redis._client = None
    await core_db.engine.dispose()


async def test_signup_me_refresh_rotation_reuse_logout(api: Api) -> None:
    email = api.email()
    r = await api.signup(email, full_name="Ada Lovelace")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == email and body["token_type"] == "bearer"
    assert body["workspace"]["role"] == "owner" and body["workspace"]["name"] == "Ada's Workspace"
    access, r1 = body["access_token"], refresh_cookie(r)
    assert any(h.startswith("botwok_access=") and "Path=/" in h for h in r.headers.get_list("set-cookie"))

    me = await api.req("GET", "/api/v1/auth/me", access)
    assert me.status_code == 200, me.text
    assert [m["role"] for m in me.json()["memberships"]] == ["owner"]

    dup = await api.signup(email)
    assert dup.status_code == 409

    # rotation
    rr = await api.post("/api/v1/auth/refresh", cookie=r1)
    assert rr.status_code == 200, rr.text
    r2 = refresh_cookie(rr)
    assert r2 != r1 and rr.json()["access_token"]

    # reuse of the rotated token → whole family revoked
    reuse = await api.post("/api/v1/auth/refresh", cookie=r1)
    assert reuse.status_code == 401 and reuse.json()["type"].endswith("/session_revoked")
    after = await api.post("/api/v1/auth/refresh", cookie=r2)
    assert after.status_code == 401

    # login → logout → refresh fails
    lg = await api.post("/api/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert lg.status_code == 200, lg.text
    r3 = refresh_cookie(lg)
    out = await api.post("/api/v1/auth/logout", cookie=r3)
    assert out.status_code == 204
    assert any(h.startswith("botwok_refresh=") and "Max-Age=0" in h for h in out.headers.get_list("set-cookie"))
    assert (await api.post("/api/v1/auth/refresh", cookie=r3)).status_code == 401

    bad = await api.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["type"].endswith("/invalid_credentials")
    assert (await api.req("GET", "/api/v1/auth/me", "garbage")).status_code == 401


async def test_login_lockout_after_ten_failures(api: Api) -> None:
    email = api.email()
    assert (await api.signup(email)).status_code == 201
    for _ in range(10):
        assert (await api.post("/api/v1/auth/login", json={"email": email, "password": "nope-nope"})).status_code == 401
    locked = await api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 423 and locked.json()["type"].endswith("/locked")


async def test_password_reset_flow(api: Api) -> None:
    from app.core.db import SessionLocal
    from app.services.auth_service import AuthService

    email = api.email()
    assert (await api.signup(email)).status_code == 201
    assert (await api.post("/api/v1/auth/password/reset", json={"email": "nobody@example.test"})).status_code == 202
    async with SessionLocal() as db:
        token = await AuthService.request_password_reset(db, email)
        await db.commit()
    assert token
    ok = await api.post("/api/v1/auth/password/reset/confirm", json={"token": token, "new_password": "brand-new-pass"})
    assert ok.status_code == 200, ok.text
    again = await api.post("/api/v1/auth/password/reset/confirm", json={"token": token, "new_password": "brand-new-pass"})
    assert again.status_code == 400  # single use
    assert (await api.post("/api/v1/auth/login", json={"email": email, "password": "brand-new-pass"})).status_code == 200


async def test_workspace_member_rbac(api: Api) -> None:
    owner = (await api.signup(workspace_name="RBAC Co")).json()
    o_tok, ws = owner["access_token"], owner["workspace"]["id"]
    assert owner["workspace"]["slug"].startswith("rbac-co")
    e_email = api.email()
    editor = (await api.signup(e_email)).json()
    e_tok, e_id = editor["access_token"], editor["user"]["id"]

    inv = await api.req("POST", f"/api/v1/workspaces/{ws}/invitations", o_tok, json={"email": e_email, "role": "editor"})
    assert inv.status_code == 201, inv.text
    token = inv.json()["token"]
    assert token and inv.json()["status"] == "pending"
    acc = await api.req("POST", f"/api/v1/invitations/{token}/accept", e_tok)
    assert acc.status_code == 200 and acc.json()["role"] == "editor"
    assert (await api.req("POST", f"/api/v1/invitations/{token}/accept", e_tok)).status_code == 409

    members = await api.req("GET", f"/api/v1/workspaces/{ws}/members", e_tok)
    assert members.status_code == 200 and {m["role"] for m in members.json()} == {"owner", "editor"}
    o_id = owner["user"]["id"]

    # editor cannot change roles, invite, remove others or manage API keys
    assert (await api.req("PATCH", f"/api/v1/workspaces/{ws}/members/{o_id}", e_tok, json={"role": "viewer"})).status_code == 403
    assert (await api.req("PATCH", f"/api/v1/workspaces/{ws}/members/{e_id}", e_tok, json={"role": "admin"})).status_code == 403
    assert (await api.req("POST", f"/api/v1/workspaces/{ws}/invitations", e_tok,
                          json={"email": "x@example.test", "role": "viewer"})).status_code == 403
    assert (await api.req("DELETE", f"/api/v1/workspaces/{ws}/members/{o_id}", e_tok)).status_code == 403
    assert (await api.req("GET", "/api/v1/settings/api-keys", e_tok, ws=ws)).status_code == 403
    assert (await api.req("PATCH", f"/api/v1/workspaces/{ws}", e_tok, json={"name": "Hijack"})).status_code == 403

    # owner can; last-owner protection holds
    ch = await api.req("PATCH", f"/api/v1/workspaces/{ws}/members/{e_id}", o_tok, json={"role": "approver"})
    assert ch.status_code == 200 and ch.json()["role"] == "approver"
    last = await api.req("PATCH", f"/api/v1/workspaces/{ws}/members/{o_id}", o_tok, json={"role": "admin"})
    assert last.status_code == 409 and last.json()["type"].endswith("/last_owner")
    assert (await api.req("DELETE", f"/api/v1/workspaces/{ws}/members/{o_id}", o_tok)).status_code == 409

    key = await api.req("POST", "/api/v1/settings/api-keys", o_tok, ws=ws, json={"name": "ci", "scopes": ["content:read"]})
    assert key.status_code == 201 and key.json()["secret"].startswith("bw_live_" + key.json()["key_prefix"] + "_")
    keys = await api.req("GET", "/api/v1/settings/api-keys", o_tok, ws=ws)
    assert keys.status_code == 200 and "secret" not in keys.json()[0]

    audit = await api.req("GET", "/api/v1/admin/audit-logs", o_tok, ws=ws)
    assert audit.status_code == 200
    actions = {a["action"] for a in audit.json()["items"]}
    assert {"workspace.create", "invitation.create", "invitation.accept", "member.role_change", "api_key.create"} <= actions

    # non-members don't see the workspace; members can leave
    stranger = (await api.signup()).json()["access_token"]
    assert (await api.req("GET", f"/api/v1/workspaces/{ws}", stranger)).status_code == 404
    assert (await api.req("DELETE", f"/api/v1/workspaces/{ws}/members/{e_id}", e_tok)).status_code == 204


async def test_settings_notifications_and_admin(api: Api) -> None:
    from uuid import UUID

    from app.core.db import SessionLocal
    from app.services.notification_service import NotificationService

    owner = (await api.signup()).json()
    tok, ws = owner["access_token"], owner["workspace"]["id"]

    put = await api.req("PUT", "/api/v1/settings/workspace", tok, ws=ws,
                        json={"timezone": "Europe/Paris", "notification_channels": {"slack_webhook_url": "https://hooks.slack.com/services/T/B/sekret"}})
    assert put.status_code == 200, put.text
    s = put.json()
    assert s["timezone"] == "Europe/Paris" and s["notification_channels"]["slack_configured"] is True
    assert "sekret" not in put.text
    assert (await api.req("PUT", "/api/v1/settings/workspace", tok, ws=ws, json={"timezone": "Mars/Base"})).status_code == 422

    budgets = await api.req("GET", "/api/v1/settings/budgets", tok, ws=ws)
    assert {(b["kind"], b["period"], b["limit_value"]) for b in budgets.json()} == {("ai_cost", "month", 50.0), ("ai_cost", "day", 10.0)}
    upd = await api.req("PUT", "/api/v1/settings/budgets", tok, ws=ws,
                        json={"budgets": [{"kind": "ai_cost", "period": "day", "limit_value": None},
                                          {"kind": "search_calls", "period": "month", "limit_value": 1000, "hard": False}]})
    assert upd.status_code == 200 and {(b["kind"], b["period"]) for b in upd.json()} == {("ai_cost", "month"), ("search_calls", "month")}

    async with SessionLocal() as db:
        await NotificationService.notify(db, UUID(ws), "test", "Hello", body="World", channels=["in_app"])
        await NotificationService.notify(db, UUID(ws), "test", "Personal", user_id=UUID(owner["user"]["id"]))
        await db.commit()
    lst = await api.req("GET", "/api/v1/notifications", tok, ws=ws)
    assert lst.status_code == 200 and lst.json()["unread_count"] == 2
    assert lst.json()["items"][1]["channels"] == ["in_app"]
    assert set(lst.json()["items"][0]["channels"]) == {"in_app", "slack"}  # workspace default channels
    nid = lst.json()["items"][0]["id"]
    assert (await api.req("POST", f"/api/v1/notifications/{nid}/read", tok, ws=ws)).json()["read_at"]
    assert (await api.req("POST", "/api/v1/notifications/read-all", tok, ws=ws)).json() == {"updated": 1}

    ev = await api.req("GET", "/api/v1/admin/events", tok, ws=ws, params={"name": "NOTIFICATION_CREATED"})
    assert ev.status_code == 200 and len(ev.json()["items"]) == 2
    health = await api.req("GET", "/api/v1/admin/health", tok, ws=ws)
    assert health.status_code == 200 and health.json()["checks"]["database"]["ok"] is True
    assert (await api.req("GET", "/api/v1/admin/jobs", tok, ws=ws)).status_code == 200
    costs = await api.req("GET", "/api/v1/admin/costs", tok, ws=ws)
    assert costs.status_code == 200 and costs.json()["total_cost_usd"] == 0
    exp = await api.req("POST", "/api/v1/settings/export", tok, ws=ws)
    assert exp.status_code == 202
    assert (await api.req("GET", exp.json()["status_url"].removeprefix(""), tok, ws=ws)).status_code == 404


async def test_auth_rate_limit(api: Api) -> None:
    codes = [(await api.post("/api/v1/auth/verify-email")).status_code for _ in range(21)]
    assert codes[:20] == [202] * 20
    last = await api.post("/api/v1/auth/verify-email")
    assert last.status_code == 429 and int(last.headers["retry-after"]) >= 1
