"""Shared adapter machinery (docs 11 §11.3, 28 §28.1-28.2).

* OAuth helpers: ``oauth_state()``, RFC 7636 PKCE (``pkce_pair``) and TikTok's hex-SHA256 variant (``pkce_pair_hex``).
* ``map_http_error`` maps every HTTP outcome to the error taxonomy
  ``transient | rate_limited | auth | validation | permanent | ambiguous | unsupported`` (``PublishError``).
* ``ResilientClient`` wraps httpx with timeouts, retries (idempotent GETs only, jittered), rate-limit header capture
  into Redis (``platform:{platform}:{account}:remaining``) and connection failure classification
  (connect failure → transient; failure *after* the request was sent → ambiguous for writes).
* ``fingerprint()``: sha256 of normalized text + media hashes + account id used for duplicate prevention and
  reconciliation.
* ``BaseAdapter``: the common skeleton every platform adapter extends (``VERIFIED_AT`` per doc 26 §26.3).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import random
import re
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.ports.social_adapter import (
    Capabilities,
    ConnectableAccount,
    MediaInput,
    PublishError,
    PublishRequest,
    PublishResult,
    RemotePost,
    TokenSet,
    ValidationIssue,
    ValidationResult,
)

log = get_logger("social.base")

VERIFIED_AT = "2026-10-08"
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0
UPLOAD_TIMEOUT_S = 300.0
GET_RETRIES = 3
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------------------------------------------
# OAuth helpers
# --------------------------------------------------------------------------------------------------------------
def oauth_state() -> str:
    """Random, single-use ``state`` (32 bytes, base64url)."""
    return secrets.token_urlsafe(32)


def pkce_verifier(length: int = 64) -> str:
    # RFC 7636: 43..128 unreserved chars
    return secrets.token_urlsafe(length)[:128]


def pkce_challenge_s256(verifier: str) -> str:
    """Standard RFC 7636 S256 challenge: base64url(sha256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce_challenge_hex(verifier: str) -> str:
    """TikTok desktop Login Kit variant: the challenge is the *hex* encoding of sha256(verifier)."""
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def pkce_pair() -> tuple[str, str]:
    v = pkce_verifier()
    return v, pkce_challenge_s256(v)


def pkce_pair_hex() -> tuple[str, str]:
    v = pkce_verifier()
    return v, pkce_challenge_hex(v)


# --------------------------------------------------------------------------------------------------------------
# Text / fingerprint helpers
# --------------------------------------------------------------------------------------------------------------
def normalize_text(text: str | None) -> str:
    return _WS_RE.sub(" ", (text or "").strip()).casefold()


def fingerprint(req: PublishRequest, account_id: Any) -> str:
    """sha256(normalized text (+segments) + media sha256s + account) per doc 11 §11.2."""
    parts = [normalize_text(req.text)]
    parts += [normalize_text(s) for s in (req.segments or [])]
    media_hashes = list(req.metadata.get("media_sha256") or [])
    if not media_hashes:
        media_hashes = [m.url or "" for m in req.media if m.url]
    payload = "\n".join(parts) + "\n" + "|".join(media_hashes) + "\n" + str(account_id)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_urls(text: str | None) -> list[str]:
    return _URL_RE.findall(text or "")


# --------------------------------------------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------------------------------------------
_AUTH_403_HINTS = ("token", "oauth", "expired", "invalid_grant", "unauthorized", "permission", "scope", "revoked",
                   "insufficient", "forbidden_scope", "access_denied")


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        return max(0, int((dt - datetime.now(UTC)).total_seconds()))
    except Exception:
        return None


def _body_snippet(resp: httpx.Response) -> str:
    try:
        return resp.text[:500]
    except Exception:
        return ""


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def redact(obj: Any) -> Any:
    """Strip token-like fields from platform responses before persisting them."""
    if isinstance(obj, dict):
        return {k: ("***" if re.search(r"token|secret|signature|authorization", k, re.I) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj[:50]]
    if isinstance(obj, str) and len(obj) > 2000:
        return obj[:2000] + "…"
    return obj


def map_http_error(resp: httpx.Response, *, sent: bool = True, write: bool = False) -> PublishError:
    """HTTP status → taxonomy (doc 11 §11.3 / doc 28 §28.2). Platform-specific codes are refined by adapters."""
    status = resp.status_code
    body = _safe_json(resp)
    snippet = _body_snippet(resp)
    text_l = (snippet or "").lower()
    code = None
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), (dict, str)) else None
        if isinstance(err, dict):
            code = str(err.get("code") or err.get("type") or err.get("status") or "") or None
        elif isinstance(err, str):
            code = err
        if not code:
            for key in ("code", "serviceErrorCode", "error_code", "title"):
                if body.get(key) is not None:
                    code = str(body.get(key))
                    break
    retry_after = parse_retry_after(resp.headers.get("retry-after") or resp.headers.get("Retry-After"))
    if not retry_after:
        reset = resp.headers.get("x-rate-limit-reset") or resp.headers.get("x-ratelimit-reset")
        if reset:
            try:
                reset_i = int(float(reset))
                retry_after = max(1, reset_i - int(time.time())) if reset_i > 10_000_000 else reset_i
            except ValueError:
                retry_after = None
    if status == 401:
        return PublishError("auth", f"unauthorized: {snippet}", code=code or "401", raw=redact(body))
    if status == 429:
        return PublishError("rate_limited", f"rate limited: {snippet}", code=code or "429", retry_after_s=retry_after or 900,
                            raw=redact(body))
    if status == 403:
        if any(h in text_l for h in _AUTH_403_HINTS):
            return PublishError("auth", f"forbidden (token/permission): {snippet}", code=code or "403", raw=redact(body))
        return PublishError("permanent", f"forbidden: {snippet}", code=code or "403", raw=redact(body))
    if status in (400, 413, 415, 422):
        return PublishError("validation", f"rejected by platform: {snippet}", code=code or str(status), raw=redact(body))
    if 400 <= status < 500:
        return PublishError("permanent", f"client error {status}: {snippet}", code=code or str(status), raw=redact(body))
    if status >= 500:
        # 5xx on a write that was already sent may have been applied upstream (doc 28: "5xx after upload finalize")
        if write and sent and status in (502, 504):
            return PublishError("ambiguous", f"gateway error {status} after send: {snippet}", code=str(status),
                                retry_after_s=retry_after, raw=redact(body))
        return PublishError("transient", f"server error {status}: {snippet}", code=code or str(status),
                            retry_after_s=retry_after, raw=redact(body))
    return PublishError("permanent", f"unexpected status {status}: {snippet}", code=str(status), raw=redact(body))


def map_exception(exc: BaseException, *, write: bool = False) -> PublishError:
    """httpx exceptions → taxonomy. Connection failures never reached the server; read failures after send are
    ambiguous for writes (the platform may have applied the request)."""
    if isinstance(exc, PublishError):
        return exc
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError, httpx.ProxyError)):
        return PublishError("transient", f"connection failed: {exc}", code=type(exc).__name__)
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError,
                        httpx.ReadError, httpx.WriteError, httpx.CloseError)):
        cat = "ambiguous" if write else "transient"
        return PublishError(cat, f"{'request sent but outcome unknown' if write else 'request failed'}: {exc}",
                            code=type(exc).__name__)
    if isinstance(exc, httpx.HTTPError):
        return PublishError("transient", f"http error: {exc}", code=type(exc).__name__)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return PublishError("ambiguous" if write else "transient", "timed out", code="timeout")
    return PublishError("permanent", f"unexpected error: {exc}", code=type(exc).__name__)


# --------------------------------------------------------------------------------------------------------------
# Rate-limit bookkeeping (Redis) and a tiny per-account limiter
# --------------------------------------------------------------------------------------------------------------
async def record_rate_limit(platform: str, account_id: Any, remaining: int | None, reset_at: int | None = None,
                            extra: dict[str, Any] | None = None) -> None:
    """Store the last observed headroom; best effort (Redis down → ignore)."""
    if remaining is None and not extra:
        return
    try:
        from app.core.redis import get_redis
        r = get_redis()
        key = f"platform:{platform}:{account_id}:remaining"
        payload = {"remaining": remaining, "reset_at": reset_at, "observed_at": int(time.time()), **(extra or {})}
        await r.set(key, json.dumps(payload), ex=24 * 3600)
    except Exception as e:  # pragma: no cover - Redis optional in tests
        log.debug("ratelimit.record_failed", error=str(e))


async def read_rate_limit(platform: str, account_id: Any) -> dict[str, Any] | None:
    try:
        from app.core.redis import get_redis
        raw = await get_redis().get(f"platform:{platform}:{account_id}:remaining")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def acquire_rate_limit(platform: str, account_id: Any) -> None:
    """Pre-flight: if the last observed window says 0 remaining and the reset is in the future → rate_limited."""
    info = await read_rate_limit(platform, account_id)
    if not info:
        return
    remaining, reset_at = info.get("remaining"), info.get("reset_at")
    if remaining is not None and int(remaining) <= 0 and reset_at and int(reset_at) > time.time():
        raise PublishError("rate_limited", "local limiter: platform window exhausted", code="local_limiter",
                           retry_after_s=int(int(reset_at) - time.time()) + 1)


def capture_rate_limit_headers(platform: str, account_id: Any, headers: httpx.Headers) -> tuple[int | None, int | None, dict]:
    """Parse the common header families (X ``x-rate-limit-*``, Pinterest ``x-ratelimit-*``, Meta usage JSON)."""
    remaining: int | None = None
    reset_at: int | None = None
    extra: dict[str, Any] = {}
    for k in ("x-rate-limit-remaining", "x-ratelimit-remaining", "ratelimit-remaining"):
        if headers.get(k) is not None:
            try:
                remaining = int(headers[k])
            except ValueError:
                pass
            break
    for k in ("x-rate-limit-reset", "x-ratelimit-reset", "ratelimit-reset"):
        if headers.get(k) is not None:
            try:
                v = int(float(headers[k]))
                reset_at = v if v > 10_000_000 else int(time.time()) + v
            except ValueError:
                pass
            break
    for k in ("x-app-usage", "x-business-use-case-usage", "x-ad-account-usage"):
        if headers.get(k):
            try:
                usage = json.loads(headers[k])
            except ValueError:
                continue
            extra[k] = usage
            pct = _max_usage_pct(usage)
            if pct is not None:
                remaining = min(remaining if remaining is not None else 100, max(0, 100 - int(pct)))
            eta = _estimated_time_to_regain(usage)
            if eta:
                reset_at = int(time.time()) + eta * 60
    return remaining, reset_at, extra


def _max_usage_pct(usage: Any) -> float | None:
    vals: list[float] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("call_count", "total_cputime", "total_time") and isinstance(v, (int, float)):
                    vals.append(float(v))
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(usage)
    return max(vals) if vals else None


def _estimated_time_to_regain(usage: Any) -> int | None:
    found: list[int] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "estimated_time_to_regain_access" and isinstance(v, (int, float)) and v > 0:
                    found.append(int(v))
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(usage)
    return max(found) if found else None


# --------------------------------------------------------------------------------------------------------------
# ResilientClient
# --------------------------------------------------------------------------------------------------------------
class ResilientClient:
    """httpx wrapper: timeouts, retries with full jitter for idempotent GETs only, taxonomy mapping, header capture.

    ``request()`` returns the response for 2xx/3xx and raises ``PublishError`` otherwise (so adapters never see raw
    status handling). ``write=True`` marks non-idempotent calls so post-send failures are classified ``ambiguous``.
    """

    def __init__(self, platform: str, *, base_headers: dict[str, str] | None = None, timeout_s: float = READ_TIMEOUT_S):
        self.platform = platform
        self.base_headers = base_headers or {}
        self.timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        self._client: httpx.AsyncClient | None = None
        self.transport: httpx.AsyncBaseTransport | None = None   # tests may inject a MockTransport

    def _get(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=self.base_headers, follow_redirects=False,
                                             transport=self.transport)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def request(self, method: str, url: str, *, account_id: Any = None, write: bool | None = None,
                      retries: int | None = None, timeout_s: float | None = None, ok: tuple[int, ...] | None = None,
                      error_mapper: Callable[[httpx.Response], PublishError | None] | None = None,
                      **kwargs: Any) -> httpx.Response:
        method = method.upper()
        is_write = write if write is not None else method not in ("GET", "HEAD", "OPTIONS")
        attempts = (retries if retries is not None else (GET_RETRIES if not is_write else 1))
        attempts = max(1, attempts)
        timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S) if timeout_s else self.timeout
        last_err: PublishError | None = None
        for i in range(attempts):
            try:
                resp = await self._get().request(method, url, timeout=timeout, **kwargs)
            except Exception as exc:  # noqa: BLE001 - mapped below
                last_err = map_exception(exc, write=is_write)
                if is_write or last_err.category not in ("transient",) or i == attempts - 1:
                    raise last_err from exc
                await asyncio.sleep(_backoff(i))
                continue
            remaining, reset_at, extra = capture_rate_limit_headers(self.platform, account_id, resp.headers)
            if account_id is not None and (remaining is not None or extra):
                await record_rate_limit(self.platform, account_id, remaining, reset_at, extra)
            if (ok and resp.status_code in ok) or (not ok and resp.status_code < 400):
                return resp
            err = error_mapper(resp) if error_mapper else None
            err = err or map_http_error(resp, sent=True, write=is_write)
            last_err = err
            if not is_write and err.category == "transient" and i < attempts - 1:
                await asyncio.sleep(_backoff(i))
                continue
            raise err
        assert last_err is not None
        raise last_err

    async def get_json(self, url: str, **kw: Any) -> Any:
        return (await self.request("GET", url, **kw)).json()

    async def post_json(self, url: str, **kw: Any) -> Any:
        resp = await self.request("POST", url, **kw)
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"_text": resp.text}


def _backoff(i: int, base: float = 1.0, cap: float = 60.0) -> float:
    return random.uniform(0, min(cap, base * (2 ** i)))


# --------------------------------------------------------------------------------------------------------------
# Attempt state helpers (resume + heartbeat without changing the protocol's ``state: dict``)
# --------------------------------------------------------------------------------------------------------------
class AttemptState(dict):
    """A ``dict`` subclass carrying optional async callbacks: ``persist()`` (write state to publish_attempts) and
    ``heartbeat()`` (touch publish_attempts.heartbeat_at). Adapters call the module helpers below."""
    persist: Callable[[], Any] | None = None
    heartbeat: Callable[[], Any] | None = None


async def save_state(state: dict[str, Any]) -> None:
    cb = getattr(state, "persist", None)
    if cb:
        try:
            await cb()
        except Exception as e:  # pragma: no cover
            log.warning("attempt.state_persist_failed", error=str(e))


async def heartbeat(state: dict[str, Any]) -> None:
    cb = getattr(state, "heartbeat", None)
    if cb:
        try:
            await cb()
        except Exception as e:  # pragma: no cover
            log.warning("attempt.heartbeat_failed", error=str(e))


async def load_media_bytes(m: MediaInput) -> bytes:
    if m.bytes_loader is not None:
        data = m.bytes_loader()
        if asyncio.iscoroutine(data):
            data = await data
        return data
    if m.url:
        async with httpx.AsyncClient(timeout=httpx.Timeout(UPLOAD_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)) as c:
            r = await c.get(m.url)
            if r.status_code >= 400:
                raise PublishError("transient", f"media fetch failed ({r.status_code})", code="media_fetch")
            return r.content
    raise PublishError("validation", "media has neither bytes nor url", code="media_missing")


def media_info(req: PublishRequest, idx: int) -> dict[str, Any]:
    infos = req.metadata.get("media_info") or []
    return infos[idx] if idx < len(infos) and isinstance(infos[idx], dict) else {}


def issue(code: str, message: str, field: str | None = None, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(code=code, message=message, field=field, severity=severity)


def result(issues: list[ValidationIssue]) -> ValidationResult:
    return ValidationResult(ok=not any(i.severity == "error" for i in issues), issues=issues)


def account_attr(account: Any, name: str, default: Any = None) -> Any:
    if account is None:
        return default
    if isinstance(account, dict):
        return account.get(name, default)
    return getattr(account, name, default)


# --------------------------------------------------------------------------------------------------------------
# BaseAdapter
# --------------------------------------------------------------------------------------------------------------
class BaseAdapter:
    """Skeleton for platform adapters. Subclasses override the protocol methods; unsupported operations raise
    ``PublishError('unsupported', ...)`` with a clear message rather than guessing (doc 27 §27.10 rule 5)."""

    platform: str = ""
    verified_at: str = VERIFIED_AT
    VERIFIED_AT: str = VERIFIED_AT
    docs: list[str] = []
    can_list_own_posts: bool = True   # LinkedIn member cannot → reconciliation refuses blind retries

    def __init__(self) -> None:
        self.http = ResilientClient(self.platform)

    # ---- helpers for subclasses -------------------------------------------------------------------------
    def _bearer(self, token: str, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", **extra}

    def map_error(self, exc: BaseException, *, write: bool = False) -> PublishError:
        return map_exception(exc, write=write)

    def now(self) -> datetime:
        return datetime.now(UTC)

    def expires_in(self, seconds: Any) -> datetime | None:
        try:
            s = int(seconds)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(time.time() + s, tz=UTC)

    # ---- protocol defaults (override) -------------------------------------------------------------------
    def capabilities(self, account: Any) -> Capabilities:  # pragma: no cover - abstract
        raise NotImplementedError

    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        raise NotImplementedError

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        raise NotImplementedError

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        raise PublishError("unsupported", f"{self.platform} does not support token refresh for this app", code="no_refresh")

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        raise NotImplementedError

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        raise NotImplementedError

    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        return result([])

    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        raise PublishError("unsupported", f"publishing to {self.platform} is not implemented", code="unsupported")

    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        raise PublishError("unsupported", f"{self.platform} cannot read a single post", code="unsupported")

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        raise PublishError("unsupported", f"{self.platform} does not support deleting posts via API",
                           code="platform_does_not_support_delete")

    async def get_status(self, account: Any, tokens: TokenSet, state: dict[str, Any]) -> dict[str, Any] | None:
        """Async flows (IG containers, TikTok publish_id, YouTube upload) report what the platform knows about an
        in-flight attempt. Return ``{"status": "published", "external_id": ..., "external_url": ...}``,
        ``{"status": "pending"}``, ``{"status": "failed", "message": ...}`` or ``None`` when nothing is known."""
        return None

    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        return normalize_post_metrics(self.platform, {})

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        return normalize_account_metrics(self.platform, {})

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        return []

    async def revoke(self, tokens: TokenSet) -> None:
        """Best-effort platform-side revocation (where an endpoint exists)."""
        return None

    def rate_limits(self) -> list[dict[str, Any]]:
        return []

    def can_list_posts(self, account: Any) -> bool:
        """Whether reconciliation may list the account's own posts (LinkedIn members cannot)."""
        return self.can_list_own_posts

    def refresh_supported(self, tokens: TokenSet | None = None) -> bool:
        return bool(tokens and tokens.refresh_token)

    # ---- shared validation helpers ----------------------------------------------------------------------
    @staticmethod
    def _segments(req: PublishRequest) -> list[str]:
        segs = [s for s in (req.segments or []) if isinstance(s, str)]
        return segs or [req.text or ""]

    @staticmethod
    def _media_kinds(req: PublishRequest) -> tuple[list[MediaInput], list[MediaInput], list[MediaInput]]:
        images = [m for m in req.media if (m.kind or "").startswith("image") or (m.mime or "").startswith("image/")]
        videos = [m for m in req.media if (m.kind or "").startswith("video") or (m.mime or "").startswith("video/")]
        docs = [m for m in req.media if m not in images and m not in videos]
        return images, videos, docs
