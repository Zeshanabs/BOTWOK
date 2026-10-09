"""Inbound platform webhooks (doc 11 §11.7): Meta verification + signed payloads (deauthorize / data deletion /
status callbacks) and a generic per-platform receiver. Payloads are stored in ``audit_logs`` (actor=system)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.deps import DB
from app.config import settings
from app.core.errors import ProblemError
from app.core.logging import get_logger
from app.models.platform import AuditLog
from app.services.social_account_service import SocialAccountService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger("webhooks")
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "botwok-verify")
META_PLATFORMS = ("facebook", "instagram", "threads")


def _verify_meta_signature(body: bytes, header: str | None) -> bool:
    if not settings.meta_app_secret:
        return settings.is_local   # locally without an app secret we cannot verify; production refuses
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.meta_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def _parse_signed_request(sr: str) -> dict[str, Any] | None:
    """Meta ``signed_request`` (deauthorize / data deletion callbacks): base64url(sig).base64url(json payload)."""
    try:
        sig_b64, payload_b64 = sr.split(".", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
    except (ValueError, TypeError):
        return None
    if settings.meta_app_secret:
        expected = hmac.new(settings.meta_app_secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, sig):
            return None
    return payload if isinstance(payload, dict) else None


async def _store(db: DB, platform: str, kind: str, payload: Any, meta: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(workspace_id=None, actor_type="system", actor_id=f"webhook:{platform}", action=f"webhook.{platform}.{kind}", target_type="webhook",
                    target_id=platform, after=payload if isinstance(payload, (dict, list)) else {"raw": str(payload)[:4000]}, meta=meta))


@router.get("/meta")
async def meta_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == META_VERIFY_TOKEN and q.get("hub.challenge"):
        return PlainTextResponse(q["hub.challenge"])
    raise ProblemError(403, "forbidden", "Verification failed")


@router.post("/meta")
async def meta_webhook(request: Request, db: DB):
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        sr = form.get("signed_request")
        payload = _parse_signed_request(str(sr)) if sr else None
        if payload is None:
            raise ProblemError(403, "invalid_signature", "signed_request missing or invalid")
        kind = "data_deletion" if "data_deletion" in str(request.url.path) or form.get("kind") == "data_deletion" else "deauthorize"
        user_id = str(payload.get("user_id") or "")
        await _store(db, "meta", kind, payload)
        n = 0
        for platform in META_PLATFORMS:
            n += await SocialAccountService.mark_revoked(db, platform=platform, user_external_id=user_id, reason=kind)
        await db.commit()
        code = hashlib.sha256(f"{user_id}:{kind}".encode()).hexdigest()[:16]
        return {"url": f"{settings.public_base_url.rstrip('/')}/privacy/deletion?code={code}", "confirmation_code": code, "accounts": n}
    if not _verify_meta_signature(body, request.headers.get("x-hub-signature-256")):
        raise ProblemError(403, "invalid_signature", "X-Hub-Signature-256 verification failed")
    try:
        payload = json.loads(body or b"{}")
    except ValueError as e:
        raise ProblemError(400, "invalid_payload", "Body is not JSON") from e
    obj = payload.get("object") if isinstance(payload, dict) else None
    platform = {"page": "facebook", "instagram": "instagram", "threads": "threads", "user": "facebook", "permissions": "facebook"}.get(str(obj), "meta")
    await _store(db, platform, str(obj or "event"), payload, {"signature_verified": bool(settings.meta_app_secret)})
    revoked = 0
    for entry in (payload.get("entry") or []) if isinstance(payload, dict) else []:
        changes = entry.get("changes") or []
        for ch in changes:
            field = ch.get("field") or ""
            value = ch.get("value") or {}
            if field in ("permissions", "deauthorize") or value.get("verb") == "remove" and field == "user":
                ext = str(entry.get("id") or entry.get("uid") or "")
                for p in META_PLATFORMS:
                    revoked += await SocialAccountService.mark_revoked(db, platform=p, external_ids=[ext], user_external_id=ext, reason="deauthorized via webhook")
    await db.commit()
    return {"received": True, "revoked": revoked}


@router.post("/{platform}")
async def generic_webhook(platform: str, request: Request, db: DB):
    body = await request.body()
    try:
        payload: Any = json.loads(body) if body else {}
    except ValueError:
        payload = {"raw": body.decode("utf-8", "replace")[:4000]}
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("content-type", "user-agent", "x-signature", "x-tiktok-signature", "x-goog-channel-id")}
    await _store(db, platform, "event", payload, {"headers": headers, "signature_verified": False})
    if platform == "tiktok" and isinstance(payload, dict) and payload.get("event", "").startswith("post.publish"):
        log.info("webhook.tiktok", tiktok_event=payload.get("event"))
    await db.commit()
    return Response(status_code=200)
