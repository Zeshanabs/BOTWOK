"""NotificationService: in-app notifications (+ NOTIFICATION_CREATED) and email / Slack / webhook delivery.

External channels are delivered asynchronously by ``jobs.notifications.deliver`` (enqueued by the
NOTIFICATION_CREATED consumer in ``app/events/consumers_identity.py``). Channel senders are best effort.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import smtplib
import socket
from collections.abc import Iterable
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import seal, unseal
from app.core.errors import not_found
from app.core.events import emit
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.models.identity import User, Workspace, WorkspaceMember
from app.models.platform import Notification, Webhook

log = get_logger("notifications")

IN_APP = "in_app"
EXTERNAL_CHANNELS = ("email", "slack", "webhook")
SEVERITIES = ("info", "success", "warning", "error")


# ---------------------------------------------------------------- secret helpers (Slack/webhook URLs at rest)
def seal_secret(value: str, aad: str) -> dict[str, Any]:
    s = seal(value, aad)
    return {"ct": base64.b64encode(s.ciphertext).decode(), "nonce": base64.b64encode(s.nonce).decode(), "kv": s.key_version}


def unseal_secret(blob: dict[str, Any] | None, aad: str) -> str | None:
    if not blob or not isinstance(blob, dict) or "ct" not in blob:
        return None
    try:
        return unseal(base64.b64decode(blob["ct"]), base64.b64decode(blob["nonce"]), int(blob.get("kv", 1)), aad)
    except Exception as e:  # wrong key / corrupted
        log.warning("notifications.secret_unseal_failed", error=str(e))
        return None


def channel_aad(workspace_id: UUID | str, name: str) -> str:
    return f"ws:{workspace_id}:notify:{name}"


def configured_channels(workspace: Workspace) -> list[str]:
    """Default channels for a workspace: in_app plus every enabled/configured external channel."""
    nc = (workspace.settings or {}).get("notification_channels") or {}
    out = [IN_APP] if nc.get("in_app", True) else []
    if nc.get("email"):
        out.append("email")
    if nc.get("slack_webhook"):
        out.append("slack")
    if nc.get("webhook"):
        out.append("webhook")
    return out or [IN_APP]


# ---------------------------------------------------------------- channel senders (best effort)
def _smtp_send(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        user = getattr(settings, "smtp_user", "") or getattr(settings, "smtp_username", "")
        password = getattr(settings, "smtp_password", "")
        if user and password:
            s.starttls()
            s.login(user, password)
        s.send_message(msg)


async def send_email(to: str | Iterable[str], subject: str, text: str, html: str | None = None) -> bool:
    """Send one email via stdlib smtplib in a worker thread (mailpit on localhost:1025 locally). Never raises."""
    recipients = [to] if isinstance(to, str) else [t for t in to if t]
    if not recipients:
        return False
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        await asyncio.to_thread(_smtp_send, msg)
        return True
    except Exception as e:
        log.warning("email.send_failed", error=str(e), recipients=len(recipients))
        return False


async def _url_allowed(url: str) -> bool:
    """Minimal SSRF guard for outbound posts: http(s) only; private/loopback targets only allowed locally."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    if settings.is_local:
        return True
    if p.scheme != "https":
        return False
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, p.hostname, p.port or 443)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


async def post_json(url: str, body: dict[str, Any] | str, headers: dict[str, str] | None = None) -> bool:
    """POST JSON (Slack incoming webhook / generic webhook); `body` may be pre-serialized. Never raises."""
    try:
        if not await _url_allowed(url):
            log.warning("notifications.url_blocked")
            return False
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            content = body if isinstance(body, str) else json.dumps(body, default=str)
            r = await c.post(url, content=content, headers={"Content-Type": "application/json", **(headers or {})})
            return 200 <= r.status_code < 300
    except Exception as e:
        log.warning("notifications.post_failed", error=str(e))
        return False


def _abs_link(link: str | None) -> str | None:
    if not link:
        return None
    return link if link.startswith("http") else f"{settings.public_base_url.rstrip('/')}/{link.lstrip('/')}"


def _envelope(n: Notification) -> dict[str, Any]:
    return {"event": "NOTIFICATION_CREATED", "id": str(n.id), "workspace_id": str(n.workspace_id), "kind": n.kind,
            "title": n.title, "body": n.body, "link": _abs_link(n.link), "severity": n.severity, "payload": n.payload,
            "created_at": n.created_at.isoformat() if n.created_at else None}


class NotificationService:
    """Notifications for every module. ``notify`` is safe to call inside any service transaction."""

    send_email = staticmethod(send_email)

    @staticmethod
    async def notify(db: AsyncSession, workspace_id: UUID, kind: str, title: str, body: str | None = None,
                     link: str | None = None, user_id: UUID | None = None, severity: str = "info",
                     channels: list[str] | None = None, payload: dict[str, Any] | None = None) -> Notification:
        """Create a notification row and emit NOTIFICATION_CREATED in the caller's transaction.

        ``channels=None`` → the workspace's configured channels (in_app + enabled email/Slack/webhook).
        """
        if channels is None:
            ws = await db.get(Workspace, workspace_id)
            channels = configured_channels(ws) if ws else [IN_APP]
        chans = [c for c in dict.fromkeys(channels) if c == IN_APP or c in EXTERNAL_CHANNELS] or [IN_APP]
        sev = severity if severity in SEVERITIES else "info"
        n = Notification(workspace_id=workspace_id, user_id=user_id, kind=kind, title=title[:500], body=body, link=link,
                         severity=sev, payload=payload or {}, channels=chans, delivered={})
        db.add(n)
        await db.flush()
        await emit(db, "NOTIFICATION_CREATED",
                   {"notification_id": str(n.id), "kind": kind, "title": n.title, "body": body, "link": link,
                    "severity": sev, "user_id": str(user_id) if user_id else None, "channels": chans},
                   workspace_id=workspace_id, actor={"type": "system"})
        return n

    # ------------------------------------------------------------ in-app inbox
    @staticmethod
    def _visible(workspace_id: UUID, user_id: UUID):
        return (Notification.workspace_id == workspace_id) & or_(Notification.user_id == user_id, Notification.user_id.is_(None))

    @classmethod
    async def list(cls, db: AsyncSession, workspace_id: UUID, user_id: UUID, *, unread_only: bool = False,
                   cursor: str | None = None, limit: int = 50) -> tuple[list[Notification], str | None, int]:
        """→ (items newest-first, next_cursor, unread_count)."""
        limit = max(1, min(limit, 200))
        base = cls._visible(workspace_id, user_id)
        q = select(Notification).where(base)
        if unread_only:
            q = q.where(Notification.read_at.is_(None))
        c = decode_cursor(cursor)
        if c:
            at = datetime.fromisoformat(c["at"])
            q = q.where(or_(Notification.created_at < at, (Notification.created_at == at) & (Notification.id < UUID(c["id"]))))
        rows = list((await db.execute(q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            last = rows[limit - 1]
            nxt = encode_cursor({"at": last.created_at.isoformat(), "id": str(last.id)})
        unread = (await db.execute(select(func.count()).select_from(Notification)
                                   .where(base, Notification.read_at.is_(None)))).scalar_one()
        return rows[:limit], nxt, int(unread)

    @classmethod
    async def mark_read(cls, db: AsyncSession, workspace_id: UUID, user_id: UUID, notification_id: UUID) -> Notification:
        n = (await db.execute(select(Notification).where(cls._visible(workspace_id, user_id),
                                                         Notification.id == notification_id))).scalar_one_or_none()
        if not n:
            raise not_found("Notification")
        if n.read_at is None:
            n.read_at = datetime.now(UTC)
        return n

    @classmethod
    async def mark_all_read(cls, db: AsyncSession, workspace_id: UUID, user_id: UUID) -> int:
        res = await db.execute(update(Notification).where(cls._visible(workspace_id, user_id), Notification.read_at.is_(None))
                               .values(read_at=datetime.now(UTC)))
        return int(getattr(res, "rowcount", 0) or 0)

    # ------------------------------------------------------------ external delivery (worker)
    @staticmethod
    async def _email_recipients(db: AsyncSession, n: Notification) -> list[str]:
        if n.user_id:
            u = await db.get(User, n.user_id)
            users = [u] if u else []
        else:
            users = list((await db.execute(select(User).join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                                           .where(WorkspaceMember.workspace_id == n.workspace_id))).scalars())
        out = []
        for u in users:
            prefs = (u.preferences or {}).get("notifications") or {}
            if u.is_active and prefs.get("email", True):
                out.append(u.email)
        return out

    @classmethod
    async def deliver(cls, db: AsyncSession, notification_id: UUID) -> dict[str, Any]:
        """Deliver every pending external channel of one notification; records results in `delivered`.

        Returns ``{"sent": [...], "failed": [...]}``. Idempotent per channel (already-delivered channels are skipped).
        """
        n = (await db.execute(select(Notification).where(Notification.id == notification_id).with_for_update())).scalar_one_or_none()
        if not n:
            return {"sent": [], "failed": [], "missing": True}
        ws = await db.get(Workspace, n.workspace_id)
        nc = ((ws.settings if ws else {}) or {}).get("notification_channels") or {}
        delivered = dict(n.delivered or {})
        sent: list[str] = []
        failed: list[str] = []
        now = datetime.now(UTC).isoformat()
        for ch in n.channels or []:
            if ch == IN_APP or (isinstance(delivered.get(ch), dict) and delivered[ch].get("at")):
                continue
            ok = False
            skipped = None
            if ch == "email":
                to = await cls._email_recipients(db, n)
                if not to:
                    skipped = "no_recipients"
                else:
                    link = _abs_link(n.link)
                    text = "\n\n".join(x for x in [n.body or "", link or ""] if x) or n.title
                    ok = await send_email(to, f"[Botwok] {n.title}", text)
            elif ch == "slack":
                url = unseal_secret(nc.get("slack_webhook"), channel_aad(n.workspace_id, "slack"))
                if not url:
                    skipped = "not_configured"
                else:
                    link = _abs_link(n.link)
                    txt = f"*{n.title}*" + (f"\n{n.body}" if n.body else "") + (f"\n<{link}|Open in Botwok>" if link else "")
                    ok = await post_json(url, {"text": txt})
            elif ch == "webhook":
                ok, skipped = await cls._deliver_webhooks(db, n, nc)
            if skipped:
                delivered[ch] = {"skipped": skipped, "at": now}
            elif ok:
                delivered[ch] = {"at": now}
                sent.append(ch)
            else:
                prev = delivered.get(ch)
                attempts = int(prev.get("attempts", 0)) + 1 if isinstance(prev, dict) else 1
                delivered[ch] = {"error": "delivery_failed", "attempts": attempts, "last_attempt_at": now}
                failed.append(ch)
        n.delivered = delivered
        return {"sent": sent, "failed": failed}

    @staticmethod
    async def _deliver_webhooks(db: AsyncSession, n: Notification, nc: dict[str, Any]) -> tuple[bool, str | None]:
        body = _envelope(n)
        targets: list[tuple[str, str | None]] = []
        url = unseal_secret(nc.get("webhook"), channel_aad(n.workspace_id, "webhook"))
        if url:
            targets.append((url, None))
        hooks = (await db.execute(select(Webhook).where(Webhook.workspace_id == n.workspace_id, Webhook.direction == "outbound",
                                                       Webhook.status == "active"))).scalars()
        for h in hooks:
            evs = set(h.events or [])
            if h.url and (not evs or evs & {"*", "NOTIFICATION_CREATED", n.kind}):
                secret = None
                if h.secret_ciphertext and h.secret_nonce:
                    try:
                        secret = unseal(h.secret_ciphertext, h.secret_nonce, h.key_version or 1)
                    except Exception:
                        secret = None
                targets.append((h.url, secret))
        if not targets:
            return False, "not_configured"
        raw = json.dumps(body, default=str)
        results = []
        for target, secret in targets:
            headers = {"X-Botwok-Event": "NOTIFICATION_CREATED"}
            if secret:
                headers["X-Botwok-Signature"] = "sha256=" + hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
            results.append(await post_json(target, raw, headers))
        return any(results), None
