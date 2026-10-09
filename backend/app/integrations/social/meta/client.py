"""MetaGraphClient: shared Graph API client for Facebook, Instagram and Threads adapters (doc 27 §27.1-27.3).

* Pinned to ``settings.meta_graph_version`` (Threads is versioned separately: ``v1.0`` on graph.threads.net).
* ``appsecret_proof`` (HMAC-SHA256 of the access token with the app secret) is attached to every call.
* Error mapping per doc 28 §28.2: code 190 → auth (subcodes 458/460 → revoked), 4/17/32/613/80001/80002 → rate_limited
  (wait from ``X-Business-Use-Case-Usage.estimated_time_to_regain_access``), 368 → permanent (policy), 10 and
  200-299 → auth (missing permission), 100 → validation, ``is_transient`` → transient.
* Usage headers (``X-App-Usage``, ``X-Business-Use-Case-Usage``) are captured into Redis by ``ResilientClient``.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from app.config import settings
from app.core.ports.social_adapter import PublishError
from app.integrations.social.base import UPLOAD_TIMEOUT_S, ResilientClient, _estimated_time_to_regain, redact

GRAPH_HOST = "https://graph.facebook.com"
IG_HOST = "https://graph.instagram.com"
THREADS_HOST = "https://graph.threads.net"
THREADS_VERSION = "v1.0"
RATE_LIMIT_CODES = {4, 17, 32, 613, 80001, 80002, 80004, 80005, 80006, 80007, 80008, 80009, 80014}
REVOKED_SUBCODES = {458, 460, 463, 467}


def appsecret_proof(access_token: str, app_secret: str | None = None) -> str:
    secret = (app_secret if app_secret is not None else settings.meta_app_secret) or ""
    return hmac.new(secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


def map_graph_error(resp: httpx.Response) -> PublishError | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return None
    err = body["error"]
    code = err.get("code")
    sub = err.get("error_subcode")
    msg = err.get("message") or ""
    try:
        code_i = int(code) if code is not None else None
    except (TypeError, ValueError):
        code_i = None
    raw = redact(body)
    retry_after = None
    for h in ("x-business-use-case-usage", "x-app-usage"):
        if resp.headers.get(h):
            try:
                import json
                eta = _estimated_time_to_regain(json.loads(resp.headers[h]))
                if eta:
                    retry_after = eta * 60
            except ValueError:
                pass
    if code_i == 190:
        if sub in REVOKED_SUBCODES:
            return PublishError("auth", f"meta token revoked/expired: {msg}", code="revoked", raw=raw)
        return PublishError("auth", f"meta token invalid: {msg}", code="190", raw=raw)
    if code_i in RATE_LIMIT_CODES or code_i == 341 or code_i == 9:
        return PublishError("rate_limited", f"meta rate limit ({code}): {msg}", code=str(code), retry_after_s=retry_after or 3600, raw=raw)
    if code_i == 368:
        return PublishError("permanent", f"meta policy block: {msg}", code="368", raw=raw)
    if code_i == 10 or (code_i is not None and 200 <= code_i <= 299):
        return PublishError("auth", f"meta permission missing: {msg}", code=str(code), raw=raw)
    if code_i == 100 or code_i == 36000 or code_i == 36001 or code_i == 36003 or code_i == 9007:
        return PublishError("validation", f"meta invalid parameter: {msg}", code=str(code), raw=raw)
    if code_i == 24 or code_i == 25 or code_i == 2207051:
        return PublishError("rate_limited", f"meta publishing limit: {msg}", code=str(code), retry_after_s=retry_after or 3600, raw=raw)
    if err.get("is_transient") or code_i in (1, 2):
        return PublishError("transient", f"meta transient error ({code}): {msg}", code=str(code), raw=raw)
    if resp.status_code == 400:
        return PublishError("validation", f"meta rejected ({code}): {msg}", code=str(code), raw=raw)
    return None


class MetaGraphClient:
    """Thin JSON client. ``path`` is relative to the versioned base (e.g. ``/me/accounts``)."""

    def __init__(self, platform: str, host: str = GRAPH_HOST, version: str | None = None):
        self.platform = platform
        self.host = host
        self.version = version if version is not None else settings.meta_graph_version
        self.http = ResilientClient(platform)
        self.app_secret = settings.meta_app_secret

    def url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        base = f"{self.host}/{self.version}" if self.version else self.host
        return f"{base}/{path.lstrip('/')}"

    def _params(self, token: str | None, params: dict[str, Any] | None) -> dict[str, Any]:
        p = {k: v for k, v in (params or {}).items() if v is not None}
        if token:
            p["access_token"] = token
            if self.app_secret and self.host == GRAPH_HOST:
                p["appsecret_proof"] = appsecret_proof(token, self.app_secret)
        return p

    async def get(self, path: str, token: str | None, params: dict[str, Any] | None = None, *, account_id: Any = None) -> Any:
        resp = await self.http.request("GET", self.url(path), params=self._params(token, params), account_id=account_id,
                                       error_mapper=map_graph_error)
        return resp.json()

    async def post(self, path: str, token: str | None, data: dict[str, Any] | None = None, *, account_id: Any = None,
                   files: dict[str, Any] | None = None, timeout_s: float | None = None, write: bool = True) -> Any:
        payload = self._params(token, data)
        resp = await self.http.request("POST", self.url(path), data=payload, files=files, account_id=account_id, write=write,
                                       timeout_s=timeout_s or (UPLOAD_TIMEOUT_S if files else None), error_mapper=map_graph_error)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"_text": resp.text}

    async def delete(self, path: str, token: str | None, params: dict[str, Any] | None = None, *, account_id: Any = None) -> Any:
        resp = await self.http.request("DELETE", self.url(path), params=self._params(token, params), account_id=account_id,
                                       ok=(200, 204, 404), error_mapper=map_graph_error)
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            return {}

    async def get_all(self, path: str, token: str | None, params: dict[str, Any] | None = None, *, limit: int = 100,
                      account_id: Any = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        body = await self.get(path, token, params, account_id=account_id)
        while True:
            out.extend(body.get("data", []))
            nxt = (body.get("paging") or {}).get("next")
            if not nxt or len(out) >= limit:
                break
            resp = await self.http.request("GET", nxt, account_id=account_id, error_mapper=map_graph_error)
            body = resp.json()
        return out[:limit]


def insights_to_dict(body: dict[str, Any]) -> dict[str, Any]:
    """Graph insights ``{"data": [{"name", "values": [{"value"}]}]}`` → ``{name: value}`` (last value)."""
    out: dict[str, Any] = {}
    for item in body.get("data", []):
        name = item.get("name")
        vals = item.get("values") or []
        if "total_value" in item and isinstance(item["total_value"], dict):
            out[name] = item["total_value"].get("value")
        elif vals:
            out[name] = vals[-1].get("value")
        else:
            out[name] = item.get("value")
    return out
