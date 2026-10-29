"""PublishingService — the publish worker state machine (doc 11 §11.3), reconciliation (§11.3), duplicate layers
(§11.4), platform deletes (§11.6) and queue/attempt views.

Exactly-once *in effect*:
1. CAS ``queued → publishing`` only when ``attempt_count == attempt_no - 1`` (stale/duplicate jobs are no-ops).
2. ``publish_attempts`` row with ``idempotency_key = f"{idempotency_root}:{attempt_no}"`` and the *resumed* state of the
   previous attempt (intermediate ids: creation_id, media_ids, upload_url, publish_id, segment_external_ids[]).
3. ``adapter.publish`` (state persisted as it goes; heartbeat during uploads).
4. Success → ``published_posts`` + ``status=published`` + ``PUBLISH_SUCCESS`` + notification.
5. Failure table by category (validation/permanent → failed; auth → refresh once then requeue; rate_limited →
   ``next_attempt_at`` from Retry-After; transient → 1/5/15/30/60 min backoff, dead letter after ``max_attempts``;
   ambiguous → ``reconcile()`` before any retry).
"""
from __future__ import annotations

import random
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, conflict, forbidden, not_found
from app.core.events import emit
from app.core.logging import get_logger
from app.core.ports.social_adapter import MediaInput, PublishError, PublishRequest
from app.integrations.social.base import AttemptState, acquire_rate_limit, fingerprint, normalize_text, redact
from app.integrations.social.registry import get_adapter
from app.models.content import ContentItem, ContentVariant
from app.models.enums import AccountStatus, ContentStatus, ScheduleStatus
from app.models.platform import UsageLedger
from app.models.scheduling import PublishAttempt, PublishedPost, ScheduledPost
from app.models.social import SocialAccount
from app.services.token_vault import TokenVault
from app.workers.queue import AlreadyEnqueued, defer_in_txn

log = get_logger("publishing")

BACKOFF_MINUTES = (1, 5, 15, 30, 60)
JITTER_MAX = 0.20
RATE_LIMIT_DEFAULT_S = 900
RATE_LIMIT_GIVE_UP = timedelta(hours=24)
DUPLICATE_WINDOW = timedelta(hours=24)
RECONCILE_LOOKBACK = timedelta(minutes=5)
PRESIGN_TTL_S = 3600
PUBLISH_TASK = "jobs.publishing.publish_post"
PUBLISH_QUEUE = "publishing"
X_COST_POST, X_COST_POST_URL, X_COST_DELETE = 0.015, 0.20, 0.010


def _now() -> datetime:
    return datetime.now(UTC)


def _segment_text(seg: Any) -> str:
    if isinstance(seg, str):
        return seg
    if isinstance(seg, dict):
        for k in ("text", "body", "caption", "content"):
            if isinstance(seg.get(k), str):
                return seg[k]
    return ""


def compose_text(text: str | None, hashtags: list[str] | None) -> str:
    try:
        from app.content.validators import compose_text as _compose
        return _compose(text, hashtags)
    except ImportError:
        text = text or ""
        tags = [t if t.startswith("#") else f"#{t}" for t in (hashtags or []) if t]
        missing = [t for t in tags if t.casefold() not in text.casefold()]
        return (text + ("\n\n" + " ".join(missing) if missing else "")).strip()


async def _notify(db: AsyncSession, workspace_id: UUID, kind: str, title: str, body: str | None = None, link: str | None = None,
                  user_id: UUID | None = None, severity: str = "info") -> None:
    try:
        from app.services.notification_service import NotificationService
    except ImportError:
        return
    try:
        await NotificationService.notify(db, workspace_id, kind, title, body, link, user_id=user_id, severity=severity)
    except Exception as e:  # pragma: no cover - notifications never break publishing
        log.warning("notify.failed", kind=kind, error=str(e))


async def _audit(db: AsyncSession, actor: Any, action: str, target_type: str, target_id: Any, *, before: Any = None, after: Any = None,
                 workspace_id: UUID | None = None) -> None:
    try:
        from app.services.audit_service import audit
    except ImportError:
        return
    try:
        await audit(db, actor, action, target_type, target_id, before=before, after=after, workspace_id=workspace_id)
    except Exception as e:  # pragma: no cover
        log.warning("audit.failed", action=action, error=str(e))


def _link(ws_slug: str | None, path: str) -> str:
    return f"/w/{ws_slug}{path}" if ws_slug else path


class PublishingService:
    """Stateless; a ``session_factory`` (defaults to ``SessionLocal``) and an ``adapter_for`` hook are injectable for tests."""

    def __init__(self, *, session_factory: Any = None, adapter_for: Any = None, vault: TokenVault | None = None,
                 worker_id: str | None = None) -> None:
        self._session_factory = session_factory
        self.adapter_for = adapter_for or (lambda account: get_adapter(account.platform))
        self.vault = vault or TokenVault()
        self.worker_id = worker_id or socket.gethostname()

    @property
    def session_factory(self) -> Any:
        if self._session_factory is None:
            from app.core.db import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    # ==================================================================================================
    # Request building
    # ==================================================================================================
    async def build_request(self, db: AsyncSession, sp: ScheduledPost, variant: ContentVariant | None = None,
                            account: SocialAccount | None = None) -> PublishRequest:
        variant = variant or await db.get(ContentVariant, sp.content_variant_id)
        account = account or await db.get(SocialAccount, sp.social_account_id)
        if variant is None or account is None:
            raise PublishError("permanent", "variant or account no longer exists", code="missing_refs")
        return await self.build_request_for_variant(db, variant, account)

    async def build_request_for_variant(self, db: AsyncSession, variant: ContentVariant, account: SocialAccount) -> PublishRequest:
        from app.integrations.storage.s3 import storage
        try:
            from app.services.media_service import MediaService
        except ImportError:
            MediaService = None  # noqa: N806
        item = await db.get(ContentItem, variant.content_item_id)
        await db.refresh(variant, ["assets"])
        text = compose_text(variant.text, list(variant.hashtags or []))
        segments = [_segment_text(s) for s in (variant.segments or [])]
        segments = [s for s in segments if s.strip()]
        if segments and variant.format.value not in ("carousel",):
            # thread-style: the first segment is the main post; hashtags go on the main text only if absent
            if not variant.text:
                text = segments[0]
        media: list[MediaInput] = []
        infos: list[dict[str, Any]] = []
        shas: list[str] = []
        for ca in sorted(variant.assets or [], key=lambda a: a.position):
            m = ca.media
            if m is None or getattr(m, "deleted_at", None):
                continue
            url, is_public = None, False
            presigned = None
            try:
                if MediaService is not None:
                    url, is_public = await MediaService.public_url(m, PRESIGN_TTL_S)
                else:
                    url = storage.public_url(m.bucket, m.object_key)
                    is_public = url is not None
                    if not url:
                        url = await storage.presign_get(m.bucket, m.object_key, PRESIGN_TTL_S)
            except Exception as e:  # storage unavailable → bytes loader still works if storage comes back
                log.warning("media.url_failed", error=str(e))
            if url and not is_public:
                presigned, url = url, None
            bucket, key = m.bucket, m.object_key

            async def _load(bucket: str = bucket, key: str = key) -> bytes:
                return await storage.get(bucket, key)
            kind = "video" if (m.mime or "").startswith("video/") else ("image" if (m.mime or "").startswith("image/") else (m.kind or "document"))
            alt = ca.alt_text if ca.alt_text is not None else m.alt_text
            media.append(MediaInput(url=url, bytes_loader=_load, mime=m.mime, alt_text=alt, kind=kind))
            infos.append({"media_asset_id": str(m.id), "sha256": m.sha256, "width": m.width, "height": m.height, "bytes": m.bytes,
                          "duration_ms": m.duration_ms, "mime": m.mime, "alt_text": alt, "kind": kind, "presigned_url": presigned,
                          "is_public": is_public, "ai_generated": m.ai_generated})
            shas.append(m.sha256)
        meta: dict[str, Any] = {**(variant.platform_metadata or {})}
        meta.setdefault("format", variant.format.value)
        meta.setdefault("title", (item.title if item else None))
        if item is not None and variant.format.value == "video" and not meta.get("description"):
            meta.setdefault("description", text)
        meta.update({"media_info": infos, "media_sha256": shas, "hashtags": list(variant.hashtags or []),
                     "variant_id": str(variant.id), "content_item_id": str(variant.content_item_id),
                     "is_ai_generated": meta.get("is_ai_generated", any(i.get("ai_generated") for i in infos) or None)})
        req = PublishRequest(text=text, segments=segments if len(segments) > 1 else [], media=media, metadata=meta)
        req.fingerprint = fingerprint(req, account.id)
        return req

    # ==================================================================================================
    # Duplicate detection (layer 7)
    # ==================================================================================================
    async def find_duplicate(self, db: AsyncSession, social_account_id: UUID, fp: str, *, exclude_scheduled_post_id: UUID | None = None,
                             within: timedelta = DUPLICATE_WINDOW) -> PublishedPost | None:
        q = (select(PublishedPost).join(PublishAttempt, PublishAttempt.scheduled_post_id == PublishedPost.scheduled_post_id)
             .where(PublishedPost.social_account_id == social_account_id, PublishedPost.deleted_at.is_(None),
                    PublishedPost.published_at >= _now() - within, PublishAttempt.request_fingerprint == fp,
                    PublishAttempt.status.in_(("succeeded", "reconciled"))))
        if exclude_scheduled_post_id is not None:
            q = q.where(PublishedPost.scheduled_post_id != exclude_scheduled_post_id)
        return (await db.execute(q.order_by(PublishedPost.published_at.desc()).limit(1))).scalars().first()

    # ==================================================================================================
    # Worker state machine
    # ==================================================================================================
    async def run_attempt(self, scheduled_post_id: UUID | str, attempt_no: int, workspace_id: UUID | str | None = None) -> str:
        """Entry point of ``jobs.publishing.publish_post``. Returns a short outcome label (for logs/tests)."""
        sp_id = UUID(str(scheduled_post_id))
        sf = self.session_factory
        # ---- phase 1: CAS + attempt row (one transaction) -------------------------------------------------
        async with sf() as db:
            sp = (await db.execute(select(ScheduledPost).where(ScheduledPost.id == sp_id).with_for_update())).scalar_one_or_none()
            if sp is None:
                return "missing"
            if sp.status != ScheduleStatus.queued or sp.attempt_count != attempt_no - 1:
                log.info("publish.stale_job", scheduled_post_id=str(sp_id), status=sp.status.value, attempt_no=attempt_no)
                return "stale"
            existing = (await db.execute(select(PublishedPost).where(PublishedPost.scheduled_post_id == sp_id,
                                                                     PublishedPost.deleted_at.is_(None)))).scalars().first()
            if existing is not None:
                sp.status = ScheduleStatus.published
                sp.published_at = existing.published_at
                await db.commit()
                return "already_published"
            account = await db.get(SocialAccount, sp.social_account_id)
            variant = await db.get(ContentVariant, sp.content_variant_id)
            if account is None or variant is None:
                sp.status = ScheduleStatus.failed
                sp.last_error = "variant or account no longer exists"
                await emit(db, "PUBLISH_FAILED", self._payload(sp, category="permanent", message=sp.last_error), workspace_id=sp.workspace_id)
                await db.commit()
                return "failed"
            if account.status != AccountStatus.active:
                sp.status = ScheduleStatus.paused
                sp.last_error = f"social account is {account.status.value}; reconnect to resume"
                await emit(db, "POST_PAUSED", self._payload(sp, reason="account_" + account.status.value), workspace_id=sp.workspace_id)
                await _notify(db, sp.workspace_id, "publish.paused", "Post paused: account needs reconnecting",
                              f"{account.display_name} ({account.platform.value}) is {account.status.value}.",
                              _link(await self._slug(db, sp.workspace_id), "/settings/social"), user_id=sp.created_by, severity="warning")
                await db.commit()
                return "paused"
            if variant.status != ContentStatus.approved:
                sp.status = ScheduleStatus.paused
                sp.last_error = f"variant is {variant.status.value}, not approved"
                await emit(db, "POST_PAUSED", self._payload(sp, reason="variant_not_approved"), workspace_id=sp.workspace_id)
                await _notify(db, sp.workspace_id, "publish.paused", "Post paused: content no longer approved", sp.last_error,
                              _link(await self._slug(db, sp.workspace_id), f"/studio/{variant.content_item_id}"), user_id=sp.created_by, severity="warning")
                await db.commit()
                return "paused"
            last_state = await self._last_state(db, sp_id)
            req = await self.build_request(db, sp, variant, account)
            try:
                tokens = await self.vault.get_tokens(db, account)
            except LookupError:
                tokens = None
            sp.status = ScheduleStatus.publishing
            sp.publishing_started_at = _now()
            sp.attempt_count = attempt_no
            sp.next_attempt_at = None
            attempt = PublishAttempt(workspace_id=sp.workspace_id, scheduled_post_id=sp.id, attempt_no=attempt_no,
                                     idempotency_key=f"{sp.idempotency_root}:{attempt_no}", status="running", state=dict(last_state),
                                     request_fingerprint=req.fingerprint, worker_id=self.worker_id, heartbeat_at=_now())
            db.add(attempt)
            await db.flush()
            dup = await self.find_duplicate(db, sp.social_account_id, req.fingerprint, exclude_scheduled_post_id=sp.id)
            if dup is not None and not last_state.get("allow_duplicate"):
                err = PublishError("permanent", f"possible duplicate of post {dup.external_id} published {dup.published_at.isoformat()}",
                                   code="possible_duplicate", raw={"published_post_id": str(dup.id)})
                await self._fail_in_txn(db, sp, attempt, err, dict(last_state), account)
                await db.commit()
                return "failed"
            if tokens is None:
                err = PublishError("auth", "no live access token for this account", code="no_token")
                await self._fail_in_txn(db, sp, attempt, err, dict(last_state), account)
                await db.commit()
                return "failed"
            await emit(db, "PUBLISH_STARTED", self._payload(sp, attempt_id=str(attempt.id), attempt_no=attempt_no), workspace_id=sp.workspace_id)
            await db.commit()
            attempt_id = attempt.id
        # ---- phase 2: platform call (no transaction held) ------------------------------------------------
        adapter = self.adapter_for(account)
        state = AttemptState(last_state)
        state.persist = lambda: self._persist_state(attempt_id, state)
        state.heartbeat = lambda: self._heartbeat(attempt_id)
        try:
            await acquire_rate_limit(account.platform.value, account.id)
            result = await adapter.publish(account, tokens, req, state)
        except PublishError as e:
            return await self._handle_failure(sp_id, attempt_id, e, state, req, account, adapter, tokens)
        except Exception as e:  # unexpected adapter crash: the platform may have applied the request → reconcile first
            log.exception("publish.adapter_crash", scheduled_post_id=str(sp_id), error=str(e))
            err = PublishError("ambiguous", f"adapter crashed: {type(e).__name__}: {e}", code="adapter_exception")
            return await self._handle_failure(sp_id, attempt_id, err, state, req, account, adapter, tokens)
        # ---- phase 3: success ----------------------------------------------------------------------------
        async with sf() as db:
            sp = (await db.execute(select(ScheduledPost).where(ScheduledPost.id == sp_id).with_for_update())).scalar_one()
            attempt = await db.get(PublishAttempt, attempt_id)
            await self._record_success(db, sp, attempt, result.external_id, result.external_url, result.published_at, result.segments,
                                       {**result.raw, "fingerprint": req.fingerprint}, dict(state), req, status="succeeded")
            await db.commit()
        return "published"

    async def _last_state(self, db: AsyncSession, sp_id: UUID) -> dict[str, Any]:
        row = (await db.execute(select(PublishAttempt.state).where(PublishAttempt.scheduled_post_id == sp_id)
                                .order_by(PublishAttempt.attempt_no.desc()).limit(1))).scalar_one_or_none()
        return dict(row or {})

    async def _persist_state(self, attempt_id: UUID, state: dict[str, Any]) -> None:
        async with self.session_factory() as db:
            attempt = await db.get(PublishAttempt, attempt_id)
            if attempt is not None:
                attempt.state = dict(state)
                attempt.heartbeat_at = _now()
                await db.commit()

    async def _heartbeat(self, attempt_id: UUID) -> None:
        async with self.session_factory() as db:
            attempt = await db.get(PublishAttempt, attempt_id)
            if attempt is not None:
                attempt.heartbeat_at = _now()
                await db.commit()

    async def _slug(self, db: AsyncSession, workspace_id: UUID) -> str | None:
        from app.models.identity import Workspace
        ws = await db.get(Workspace, workspace_id)
        return ws.slug if ws else None

    @staticmethod
    def _payload(sp: ScheduledPost, **extra: Any) -> dict[str, Any]:
        return {"scheduled_post_id": str(sp.id), "content_variant_id": str(sp.content_variant_id), "social_account_id": str(sp.social_account_id),
                "brand_id": str(sp.brand_id), "status": sp.status.value if hasattr(sp.status, "value") else sp.status,
                "attempt_count": sp.attempt_count, "next_attempt_at": sp.next_attempt_at.isoformat() if sp.next_attempt_at else None, **extra}

    # ---- success -----------------------------------------------------------------------------------------
    async def _record_success(self, db: AsyncSession, sp: ScheduledPost, attempt: PublishAttempt | None, external_id: str,
                              external_url: str | None, published_at: datetime | None, segments: list[dict[str, Any]], raw: dict[str, Any],
                              state: dict[str, Any], req: PublishRequest | None, *, status: str = "succeeded") -> PublishedPost:
        account = await db.get(SocialAccount, sp.social_account_id)
        if account is None:
            raise PublishError("permanent", "account vanished", code="missing_refs")
        published_at = published_at or _now()
        pp = PublishedPost(workspace_id=sp.workspace_id, brand_id=sp.brand_id, scheduled_post_id=sp.id, content_variant_id=sp.content_variant_id,
                           social_account_id=sp.social_account_id, platform=account.platform, external_id=str(external_id),
                           external_url=external_url, segments=segments or [], published_at=published_at, raw=redact(raw))
        try:
            async with db.begin_nested():   # add inside: begin_nested() flushes pending objects before the SAVEPOINT
                db.add(pp)
                await db.flush()
        except IntegrityError:
            # (social_account_id, external_id) already recorded (e.g. by a reconciliation) → reuse it
            pp = (await db.execute(select(PublishedPost).where(PublishedPost.social_account_id == sp.social_account_id,
                                                                PublishedPost.external_id == str(external_id)))).scalar_one()
            if pp.scheduled_post_id is None:
                pp.scheduled_post_id = sp.id
        sp.status = ScheduleStatus.published
        sp.published_at = published_at
        sp.next_attempt_at = None
        sp.last_error = None
        if attempt is not None:
            attempt.status = status
            attempt.finished_at = _now()
            attempt.state = dict(state)
            attempt.platform_response = redact(raw)
        await self._book_usage(db, sp, pp, raw, req)
        await emit(db, "PUBLISH_SUCCESS", self._payload(sp, published_post_id=str(pp.id), external_id=str(external_id), external_url=external_url,
                                                        platform=account.platform.value, published_at=published_at.isoformat(),
                                                        reconciled=status == "reconciled"), workspace_id=sp.workspace_id)
        await _notify(db, sp.workspace_id, "publish.success", f"Published to {account.display_name}",
                      external_url or f"{account.platform.value} post {external_id}", external_url or _link(await self._slug(db, sp.workspace_id), "/publishing"),
                      user_id=sp.created_by, severity="success")
        return pp

    async def _book_usage(self, db: AsyncSession, sp: ScheduledPost, pp: PublishedPost, raw: dict[str, Any], req: PublishRequest | None) -> None:
        platform = pp.platform.value if hasattr(pp.platform, "value") else str(pp.platform)
        try:
            if platform == "x":
                cost = raw.get("cost_usd")
                if cost is None:
                    from app.integrations.social.base import find_urls
                    cost = X_COST_POST_URL if (req and find_urls(req.text)) else X_COST_POST
                db.add(UsageLedger(workspace_id=sp.workspace_id, kind="platform_writes", provider="x", platform=pp.platform,
                                   quantity=max(1, len(pp.segments or []) or 1), cost_usd=float(cost), ref_type="published_post", ref_id=pp.id))
            elif platform == "youtube":
                db.add(UsageLedger(workspace_id=sp.workspace_id, kind="platform_quota", provider=f"youtube:{raw.get('quota_bucket', 'video_uploads')}",
                                   platform=pp.platform, quantity=float(raw.get("quota_units") or 1), cost_usd=0, ref_type="published_post", ref_id=pp.id))
            else:
                db.add(UsageLedger(workspace_id=sp.workspace_id, kind="platform_writes", provider=platform, platform=pp.platform, quantity=1,
                                   cost_usd=0, ref_type="published_post", ref_id=pp.id))
        except Exception as e:  # pragma: no cover
            log.warning("usage.book_failed", error=str(e))

    # ---- failure -----------------------------------------------------------------------------------------
    async def _handle_failure(self, sp_id: UUID, attempt_id: UUID, err: PublishError, state: dict[str, Any], req: PublishRequest,
                              account: SocialAccount, adapter: Any, tokens: Any) -> str:
        async with self.session_factory() as db:
            sp = (await db.execute(select(ScheduledPost).where(ScheduledPost.id == sp_id).with_for_update())).scalar_one()
            attempt = await db.get(PublishAttempt, attempt_id)
            account = await db.get(SocialAccount, account.id) or account
            outcome = await self._fail_in_txn(db, sp, attempt, err, dict(state), account, adapter=adapter, tokens=tokens, req=req)
            await db.commit()
            return outcome

    async def _fail_in_txn(self, db: AsyncSession, sp: ScheduledPost, attempt: PublishAttempt, err: PublishError, state: dict[str, Any],
                           account: SocialAccount, *, adapter: Any = None, tokens: Any = None, req: PublishRequest | None = None) -> str:
        now = _now()
        attempt.state = dict(state)   # fresh object: in-place JSONB mutations are invisible to change tracking
        attempt.error_category = err.category
        attempt.error_code = err.code
        attempt.error_message = (err.message or "")[:2000]
        attempt.platform_response = redact(err.raw) if isinstance(err.raw, (dict, list)) else ({"raw": str(err.raw)[:2000]} if err.raw else None)
        attempt.finished_at = now
        done = len(state.get("segment_external_ids") or [])
        partial = f" (partially published: {done} segment(s) already posted; retry resumes)" if done else ""
        message = f"{err.category}: {err.message}{partial}"
        slug = await self._slug(db, sp.workspace_id)
        link = _link(slug, "/publishing")
        category = "permanent" if err.category == "unsupported" else err.category

        async def fail(reason: str, *, dead: bool = False, severity: str = "error") -> str:
            attempt.state = dict(state)
            attempt.status = "failed" if attempt.status != "ambiguous" else "ambiguous"
            sp.status = ScheduleStatus.failed
            sp.next_attempt_at = None
            sp.last_error = reason[:2000]
            await emit(db, "PUBLISH_FAILED", self._payload(sp, category=category, code=err.code, message=reason, attempt_id=str(attempt.id)),
                       workspace_id=sp.workspace_id)
            if dead:
                await emit(db, "PUBLISH_DEAD_LETTERED", self._payload(sp, attempts=sp.attempt_count, message=reason), workspace_id=sp.workspace_id)
            await _notify(db, sp.workspace_id, "publish.failed", "Publishing failed" + (" (gave up)" if dead else ""), reason, link,
                          user_id=sp.created_by, severity="error" if not dead else "error")
            return "dead_lettered" if dead else "failed"

        async def retry_later(delay_s: float, reason: str) -> str:
            attempt.state = dict(state)
            attempt.status = "failed" if attempt.status != "ambiguous" else "ambiguous"
            sp.status = ScheduleStatus.queued
            sp.next_attempt_at = now + timedelta(seconds=delay_s)
            sp.last_error = reason[:2000]
            await emit(db, "PUBLISH_FAILED", self._payload(sp, category=category, code=err.code, message=reason, attempt_id=str(attempt.id)),
                       workspace_id=sp.workspace_id)
            return "retry_scheduled"

        if category in ("validation", "permanent"):
            return await fail(message)

        if category == "auth":
            refreshed = False
            if adapter is not None and tokens is not None and not state.get("auth_refresh_attempted") and err.code != "revoked":
                state["auth_refresh_attempted"] = True
                attempt.state = dict(state)
                try:
                    new_tokens = await adapter.refresh(tokens)
                    await self.vault.store_tokenset(db, account, new_tokens)
                    refreshed = True
                except Exception as e:  # noqa: BLE001
                    log.warning("publish.refresh_failed", account_id=str(account.id), error=str(e))
            if refreshed:
                attempt.status = "failed"
                sp.status = ScheduleStatus.queued
                sp.next_attempt_at = None
                sp.last_error = "token refreshed; retrying"
                try:
                    await defer_in_txn(db, PUBLISH_TASK, queue=PUBLISH_QUEUE, queueing_lock=f"publish:{sp.id}",
                                       args={"scheduled_post_id": str(sp.id), "attempt_no": sp.attempt_count + 1, "workspace_id": str(sp.workspace_id)})
                except AlreadyEnqueued:
                    pass
                return "requeued"
            new_status = AccountStatus.revoked if err.code == "revoked" else AccountStatus.expired
            account.status = new_status
            account.health = {**(account.health or {}), "token_valid": False, "last_error": err.message[:500], "checked_at": now.isoformat()}
            event = "SOCIAL_ACCOUNT_REVOKED" if new_status == AccountStatus.revoked else "SOCIAL_ACCOUNT_EXPIRED"
            await emit(db, event, {"account_id": str(account.id), "platform": account.platform.value, "reason": err.message[:500]},
                       workspace_id=sp.workspace_id)
            await _notify(db, sp.workspace_id, "social.reconnect", f"Reconnect {account.display_name}",
                          f"The {account.platform.value} connection is {new_status.value}. Reconnect it to publish.", _link(slug, "/settings/social"),
                          severity="warning")
            return await fail(f"account token {new_status.value}: {err.message}")

        if category == "rate_limited":
            if now - sp.scheduled_at > RATE_LIMIT_GIVE_UP:
                return await fail(f"rate limited for more than 24 h: {err.message}", dead=True)
            wait = int(err.retry_after_s or RATE_LIMIT_DEFAULT_S)
            until = now + timedelta(seconds=wait)
            return await retry_later(wait, f"rate limited until {until.strftime('%H:%M UTC')}: {err.message}")

        if category == "transient":
            if sp.attempt_count >= sp.max_attempts:
                return await fail(f"gave up after {sp.attempt_count} attempts: {err.message}", dead=True)
            minutes = BACKOFF_MINUTES[min(sp.attempt_count - 1, len(BACKOFF_MINUTES) - 1)]
            delay = minutes * 60 * (1 + random.uniform(0, JITTER_MAX))
            return await retry_later(delay, message)

        # ambiguous: reconcile before any retry
        attempt.status = "ambiguous"
        outcome = await self.reconcile(db, sp, attempt, adapter=adapter, account=account, tokens=tokens, req=req, state=state)
        if outcome == "published":
            return "published"
        if outcome == "pending":
            return await retry_later(120, f"platform still processing; will check again: {err.message}")
        if outcome == "failed":
            return await fail(f"platform reported failure after ambiguous result: {err.message}")
        if outcome == "cannot_list":
            await _notify(db, sp.workspace_id, "publish.verify", "Verify this post manually",
                          f"{account.platform.value} returned an ambiguous result and cannot list your posts. Check the account before retrying.",
                          link, user_id=sp.created_by, severity="warning")
            return await fail(f"ambiguous result; verify manually: {err.message}")
        # not_found → the platform shows nothing was posted → safe retry with backoff
        if sp.attempt_count >= sp.max_attempts:
            return await fail(f"gave up after {sp.attempt_count} attempts (ambiguous, nothing found): {err.message}", dead=True)
        minutes = BACKOFF_MINUTES[min(sp.attempt_count - 1, len(BACKOFF_MINUTES) - 1)]
        return await retry_later(minutes * 60 * (1 + random.uniform(0, JITTER_MAX)), f"ambiguous result, nothing found on platform; retrying: {err.message}")

    # ---- reconciliation ----------------------------------------------------------------------------------
    async def reconcile(self, db: AsyncSession, sp: ScheduledPost, attempt: PublishAttempt, *, adapter: Any = None, account: SocialAccount | None = None,
                        tokens: Any = None, req: PublishRequest | None = None, state: dict[str, Any] | None = None) -> str:
        """→ ``published`` (row created, status published) | ``pending`` | ``not_found`` | ``cannot_list`` | ``failed``."""
        account = account or await db.get(SocialAccount, sp.social_account_id)
        adapter = adapter or self.adapter_for(account)
        state = dict(state if state is not None else (attempt.state or {}))
        if tokens is None:
            try:
                tokens = await self.vault.get_tokens(db, account)
            except LookupError:
                return "cannot_list"
        if req is None:
            req = await self.build_request(db, sp, None, account)
        # 1) async flows: ask the platform about the intermediate id
        get_status = getattr(adapter, "get_status", None)
        if get_status is not None:
            try:
                st = await get_status(account, tokens, state)
            except Exception as e:  # noqa: BLE001
                log.warning("reconcile.get_status_failed", error=str(e))
                st = None
            if st:
                if st.get("status") == "published" and st.get("external_id"):
                    await self._record_success(db, sp, attempt, st["external_id"], st.get("external_url"), _now(), [], {**(st.get("raw") or {}),
                                               "fingerprint": req.fingerprint, "reconciled_via": "get_status"}, state, req, status="reconciled")
                    return "published"
                if st.get("status") == "pending":
                    return "pending"
                if st.get("status") == "failed":
                    return "failed"
        # 2) list own posts and match the fingerprint (normalized text + time window)
        can_list = getattr(adapter, "can_list_posts", None)
        if can_list is not None and not can_list(account):
            return "cannot_list"
        since = (attempt.started_at or _now()) - RECONCILE_LOOKBACK
        try:
            posts = await adapter.find_recent_posts(account, tokens, since)
        except Exception as e:  # noqa: BLE001
            log.warning("reconcile.list_failed", error=str(e))
            return "pending"
        wanted = normalize_text(req.segments[0] if req.segments else req.text)
        for p in posts:
            if p.created_at and p.created_at < since:
                continue
            if wanted and normalize_text(p.text) == wanted:
                await self._record_success(db, sp, attempt, p.external_id, p.url, p.created_at or _now(), [], {"fingerprint": req.fingerprint,
                                           "reconciled_via": "find_recent_posts", "remote": redact(p.raw)}, state, req, status="reconciled")
                return "published"
        return "not_found"

    async def reconcile_post(self, scheduled_post_id: UUID | str, workspace_id: UUID | str | None = None) -> str:
        """``jobs.publishing.reconcile`` / lease expiry: reconcile a stuck ``publishing`` row, then queue (resume) or fail."""
        sp_id = UUID(str(scheduled_post_id))
        async with self.session_factory() as db:
            sp = (await db.execute(select(ScheduledPost).where(ScheduledPost.id == sp_id).with_for_update())).scalar_one_or_none()
            if sp is None or sp.status != ScheduleStatus.publishing:
                return "noop"
            attempt = (await db.execute(select(PublishAttempt).where(PublishAttempt.scheduled_post_id == sp_id)
                                        .order_by(PublishAttempt.attempt_no.desc()).limit(1))).scalars().first()
            account = await db.get(SocialAccount, sp.social_account_id)
            if attempt is None or account is None:
                sp.status = ScheduleStatus.failed
                sp.last_error = "lease expired without an attempt record"
                await db.commit()
                return "failed"
            outcome = await self.reconcile(db, sp, attempt)
            if outcome == "published":
                pass
            elif outcome in ("pending", "not_found"):
                attempt.status = "ambiguous"
                attempt.error_category = attempt.error_category or "ambiguous"
                attempt.error_message = attempt.error_message or "worker lease expired"
                attempt.finished_at = _now()
                sp.status = ScheduleStatus.queued
                sp.next_attempt_at = _now()
                sp.last_error = "worker lease expired; resuming after reconciliation"
            elif outcome == "cannot_list":
                attempt.status = "ambiguous"
                attempt.finished_at = _now()
                sp.status = ScheduleStatus.failed
                sp.last_error = "worker lease expired; ambiguous result; verify manually"
                await emit(db, "PUBLISH_FAILED", self._payload(sp, category="ambiguous", message=sp.last_error), workspace_id=sp.workspace_id)
                await _notify(db, sp.workspace_id, "publish.verify", "Verify this post manually", sp.last_error,
                              _link(await self._slug(db, sp.workspace_id), "/publishing"), user_id=sp.created_by, severity="warning")
            else:
                attempt.status = "failed"
                attempt.finished_at = _now()
                sp.status = ScheduleStatus.failed
                sp.last_error = "platform reported failure"
                await emit(db, "PUBLISH_FAILED", self._payload(sp, category="permanent", message=sp.last_error), workspace_id=sp.workspace_id)
            await db.commit()
            return outcome

    # ==================================================================================================
    # API-facing operations
    # ==================================================================================================
    async def publish_now(self, db: AsyncSession, member: Any, variant_id: UUID, social_account_id: UUID, *, force: bool = False) -> ScheduledPost:
        from app.services.scheduling_service import SchedulingService
        return await SchedulingService().publish_now(db, member, variant_id, social_account_id, force=force)

    async def publish_from_proposal(self, db: AsyncSession, workspace_id: UUID, *, variant_id: Any, social_account_id: Any = None,
                                    platform: str | None = None, note: str | None = None, actor: dict[str, Any] | None = None) -> ScheduledPost:
        """Called by the ApprovalGate after a human approved ``publishing.propose_publish`` (never by the LLM directly)."""
        from app.services.scheduling_service import SchedulingService
        return await SchedulingService().schedule_from_proposal(db, workspace_id, variant_id=variant_id, scheduled_at=_now(),
                                                                social_account_id=social_account_id, platform=platform, note=note, actor=actor, priority=10)

    async def queue(self, db: AsyncSession, workspace_id: UUID, status: list[str] | None = None, brand_id: UUID | None = None,
                    limit: int = 200) -> list[ScheduledPost]:
        q = select(ScheduledPost).where(ScheduledPost.workspace_id == workspace_id)
        statuses = status or ["scheduled", "queued", "publishing", "failed", "paused"]
        q = q.where(ScheduledPost.status.in_([ScheduleStatus(s) for s in statuses]))
        if brand_id:
            q = q.where(ScheduledPost.brand_id == brand_id)
        return list((await db.execute(q.order_by(ScheduledPost.scheduled_at.asc()).limit(limit))).scalars().unique())

    async def get_attempt(self, db: AsyncSession, workspace_id: UUID, attempt_id: UUID) -> PublishAttempt:
        a = await db.get(PublishAttempt, attempt_id)
        if a is None or a.workspace_id != workspace_id:
            raise not_found("Publish attempt")
        return a

    async def retry_attempt(self, db: AsyncSession, member: Any, attempt_id: UUID) -> ScheduledPost:
        a = await self.get_attempt(db, member.workspace_id, attempt_id)
        from app.services.scheduling_service import SchedulingService
        return await SchedulingService().retry(db, member, a.scheduled_post_id)

    async def list_published(self, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, platform: str | None = None,
                             social_account_id: UUID | None = None, since: datetime | None = None, until: datetime | None = None,
                             include_deleted: bool = False, limit: int = 100, offset: int = 0) -> list[PublishedPost]:
        q = select(PublishedPost).where(PublishedPost.workspace_id == workspace_id)
        if not include_deleted:
            q = q.where(PublishedPost.deleted_at.is_(None))
        if brand_id:
            q = q.where(PublishedPost.brand_id == brand_id)
        if platform:
            q = q.where(PublishedPost.platform == platform)
        if social_account_id:
            q = q.where(PublishedPost.social_account_id == social_account_id)
        if since:
            q = q.where(PublishedPost.published_at >= since)
        if until:
            q = q.where(PublishedPost.published_at <= until)
        return list((await db.execute(q.order_by(PublishedPost.published_at.desc()).offset(offset).limit(limit))).scalars())

    async def delete_published(self, db: AsyncSession, member: Any, published_post_id: UUID) -> PublishedPost:
        """Platform delete → ``deleted_at``; TikTok → 409 platform_does_not_support_delete."""
        if not member.has("admin"):
            raise forbidden("Deleting published posts requires admin")
        pp = await db.get(PublishedPost, published_post_id)
        if pp is None or pp.workspace_id != member.workspace_id:
            raise not_found("Published post")
        if pp.deleted_at:
            return pp
        account = await db.get(SocialAccount, pp.social_account_id)
        adapter = self.adapter_for(account)
        caps = adapter.capabilities(account)
        if not caps.can_delete:
            raise conflict("platform_does_not_support_delete", f"{account.platform.value} has no API delete")
        tokens = await self.vault.get_tokens(db, account)
        try:
            await adapter.delete_post(account, tokens, pp.external_id)
            for seg in pp.segments or []:
                ext = seg.get("external_id") if isinstance(seg, dict) else None
                if ext and ext != pp.external_id:
                    try:
                        await adapter.delete_post(account, tokens, ext)
                    except PublishError as e:
                        log.warning("delete.segment_failed", external_id=ext, error=e.message)
        except PublishError as e:
            if e.category == "unsupported":
                raise conflict("platform_does_not_support_delete", e.message) from e
            raise ProblemError(502, "platform_error", "Platform delete failed", f"{e.category}: {e.message}") from e
        pp.deleted_at = _now()
        if account.platform.value == "x":
            db.add(UsageLedger(workspace_id=pp.workspace_id, kind="platform_writes", provider="x", platform=account.platform, quantity=1,
                               cost_usd=X_COST_DELETE, ref_type="published_post_delete", ref_id=pp.id))
        await emit(db, "CONTENT_STATUS_CHANGED", {"published_post_id": str(pp.id), "content_variant_id": str(pp.content_variant_id),
                                                  "change": "platform_deleted", "external_id": pp.external_id}, workspace_id=pp.workspace_id,
                   actor={"type": "user", "id": str(member.user.id)})
        await _audit(db, member, "publishing.delete_published", "published_post", pp.id, before={"external_id": pp.external_id, "url": pp.external_url},
                     after={"deleted_at": pp.deleted_at.isoformat()}, workspace_id=pp.workspace_id)
        return pp

    # ---- validation helper shared with scheduling ----------------------------------------------------
    async def validate(self, db: AsyncSession, variant: ContentVariant, account: SocialAccount) -> tuple[dict[str, Any], PublishRequest]:
        """Deterministic content validators + adapter validation → ``{ok, issues[], warnings[]}``."""
        req = await self.build_request_for_variant(db, variant, account)
        issues: list[dict[str, Any]] = []
        try:
            from app.content.validators import validate_variant
            data = {"text": variant.text, "segments": variant.segments, "hashtags": variant.hashtags, "media_plan": variant.media_plan,
                    "platform_metadata": variant.platform_metadata, "assets": req.metadata.get("media_info", [])}
            res = validate_variant(variant.platform, variant.format, data)
            issues.extend(res.get("issues") or [])
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - validator bug must not block adapter validation
            log.warning("validate_variant.failed", error=str(e))
        adapter = self.adapter_for(account)
        vr = await adapter.validate_content(account, req)
        seen = {(i.get("code"), i.get("field")) for i in issues}
        for i in vr.issues:
            key = (i.code, i.field)
            if key in seen:
                continue
            issues.append({"code": i.code, "message": i.message, "field": i.field, "severity": i.severity})
        errors = [i for i in issues if i.get("severity", "error") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        return {"ok": not errors, "issues": issues, "errors": errors, "warnings": warnings, "checked_at": _now().isoformat(),
                "platform": account.platform.value, "fingerprint": req.fingerprint}, req

