"""Identity unit tests (no DB / no Redis)."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token, decode_access_token, hash_token, new_opaque_token
from app.models.enums import MemberRole
from app.schemas.identity import AuditLogOut, BudgetUpdate, LoginRequest, SignupRequest, normalize_email
from app.services.audit_service import jsonable, resolve_actor, safe_ip
from app.services.auth_service import (
    LOCKOUT_MAX_FAILURES,
    LOCKOUT_WINDOW_S,
    derive_workspace_name,
    is_locked_out,
    lockout_key,
    register_failure,
)
from app.services.notification_service import channel_aad, configured_channels, seal_secret, unseal_secret
from app.services.workspace_service import (
    API_KEY_PREFIX,
    mask_url,
    new_api_key,
    parse_api_key,
    slugify,
    validate_scopes,
)


# ---------------------------------------------------------------- token hashing
def test_hash_token_is_deterministic_sha256() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert len(hash_token("abc")) == 64


def test_new_opaque_token_returns_matching_hash_and_is_random() -> None:
    t1, h1 = new_opaque_token()
    t2, h2 = new_opaque_token()
    assert hash_token(t1) == h1 and hash_token(t2) == h2
    assert t1 != t2 and len(t1) >= 60  # 48 random bytes, urlsafe-b64


def test_access_token_carries_workspace_and_role_claims() -> None:
    uid, ws = uuid4(), uuid4()
    claims = decode_access_token(create_access_token(uid, ws, "owner"))
    assert claims["sub"] == str(uid) and claims["ws"] == str(ws) and claims["role"] == "owner" and claims["jti"]


# ---------------------------------------------------------------- lockout
def test_lockout_threshold() -> None:
    assert LOCKOUT_MAX_FAILURES == 10 and LOCKOUT_WINDOW_S == 900
    assert not is_locked_out(None)
    assert not is_locked_out("9")
    assert is_locked_out("10")
    assert is_locked_out(11)


def test_lockout_key_is_normalized() -> None:
    assert lockout_key("  Sam@Example.COM ") == "auth:fail:sam@example.com"


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True


async def test_register_failure_sets_window_once_and_locks_at_ten() -> None:
    r = FakeRedis()
    counts = [await register_failure(r, "a@b.co") for _ in range(10)]
    assert counts == list(range(1, 11))
    assert r.ttls[lockout_key("a@b.co")] == LOCKOUT_WINDOW_S
    assert is_locked_out(counts[-1]) and not is_locked_out(counts[-2])


# ---------------------------------------------------------------- slugs & names
@pytest.mark.parametrize(("name", "slug"), [
    ("Acme Inc.", "acme-inc"),
    ("  Café   Déjà Vu!! ", "cafe-deja-vu"),
    ("---", "workspace"),
    ("", "workspace"),
    ("x", "x-workspace"),
    ("API", "api-workspace"),
    ("a" * 100, "a" * 48),
])
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_derive_workspace_name() -> None:
    assert derive_workspace_name("sam@x.io", None, "  Acme  ") == "Acme"
    assert derive_workspace_name("sam@x.io", "Sam Lee", None) == "Sam's Workspace"
    assert derive_workspace_name("jane.doe@x.io", None, None) == "Jane Doe's Workspace"


# ---------------------------------------------------------------- API keys
def test_api_key_format_and_parse() -> None:
    full, prefix, key_hash = new_api_key()
    assert full.startswith(f"{API_KEY_PREFIX}{prefix}_")
    assert len(prefix) == 8 and all(c in "0123456789abcdef" for c in prefix)
    assert parse_api_key(full) == prefix
    assert key_hash == hash_token(full) and full not in key_hash
    assert parse_api_key("bw_live_zz_nope") is None
    assert parse_api_key("Bearer something") is None
    assert new_api_key()[0] != full


def test_validate_scopes() -> None:
    assert validate_scopes(["content:write", "analytics:read", "content:write"]) == ["content:write", "analytics:read"]
    from app.core.errors import ProblemError
    for bad in (["members:write"], ["content:delete"], ["Content:read"], ["admin:read"]):
        with pytest.raises(ProblemError):
            validate_scopes(bad)


# ---------------------------------------------------------------- schemas
def test_email_normalization_accepts_local_domains() -> None:
    assert normalize_email(" Demo@Botwok.LOCAL ") == "demo@botwok.local"
    assert LoginRequest(email="demo@botwok.local", password="x").email == "demo@botwok.local"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


def test_signup_password_policy() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.co", password="short")
    assert SignupRequest(email="a@b.co", password="long-enough").full_name is None


def test_budget_update_validation() -> None:
    assert BudgetUpdate(kind="ai_cost", period="month", limit_value=50).limit_value == 50
    with pytest.raises(ValidationError):
        BudgetUpdate(kind="ai_cost", period="year", limit_value=50)
    with pytest.raises(ValidationError):
        BudgetUpdate(kind="ai_cost", period="day", limit_value=-1)


def test_audit_log_out_coerces_ip() -> None:
    import ipaddress
    out = AuditLogOut(id=1, actor_type="user", actor_id="x", action="a", ip=ipaddress.ip_address("10.0.0.1"))
    assert out.ip == "10.0.0.1"


# ---------------------------------------------------------------- audit helpers
def test_resolve_actor_variants() -> None:
    ws = uuid4()
    member = SimpleNamespace(user=SimpleNamespace(id=uuid4()), workspace_id=ws, role=MemberRole.admin)
    assert resolve_actor(member) == ("user", str(member.user.id), ws)
    assert resolve_actor(None) == ("system", "system", None)
    assert resolve_actor({"type": "agent", "id": "writer", "workspace_id": str(ws)}) == ("agent", "writer", ws)
    assert resolve_actor({"type": "bogus"})[0] == "system"


def test_jsonable_and_safe_ip() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal
    u = uuid4()
    assert jsonable({"id": u, "at": datetime(2026, 1, 1, tzinfo=UTC), "n": Decimal("1.5"), "r": MemberRole.owner}) == {
        "id": str(u), "at": "2026-01-01T00:00:00+00:00", "n": 1.5, "r": "owner"}
    assert safe_ip("testclient") is None and safe_ip("127.0.0.1") == "127.0.0.1" and safe_ip(None) is None


# ---------------------------------------------------------------- notification channel helpers
def test_secret_sealing_roundtrip_and_channels() -> None:
    ws = uuid4()
    blob = seal_secret("https://hooks.slack.com/services/T/B/x", channel_aad(ws, "slack"))
    assert "hooks.slack.com" not in str(blob)
    assert unseal_secret(blob, channel_aad(ws, "slack")) == "https://hooks.slack.com/services/T/B/x"
    assert unseal_secret(blob, channel_aad(uuid4(), "slack")) is None  # AAD-bound to the workspace
    w = SimpleNamespace(settings={"notification_channels": {"email": True, "slack_webhook": blob}})
    assert configured_channels(w) == ["in_app", "email", "slack"]
    assert configured_channels(SimpleNamespace(settings={})) == ["in_app"]
    assert mask_url("https://hooks.slack.com/services/T/B/abcd1234") == "https://hooks.slack.com/…1234"
