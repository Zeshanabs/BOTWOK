"""SchedulingService + scheduler-loop functions (doc 12).

Module-level functions are called by ``app/workers/scheduler.py`` every tick (leader only):
``dispatch_due_posts(db)`` (the exact ``FOR UPDATE SKIP LOCKED`` dispatch from §12.3, enqueueing the publish job in the
same transaction), ``dispatch_retries(db)`` (``queued`` rows whose ``next_attempt_at`` passed), ``expire_leases(db)``
(stale ``publishing`` rows → reconciliation job, never a blind retry) and ``materialize_recurring(db)`` (rrule → rows
14 days ahead). ``SchedulingService`` implements the operations table (§12.4), validation at scheduling time (doc 11
§11.5), best-time slots (§12.6) and the calendar aggregation (§12.8).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, conflict, forbidden, not_found, validation
from app.core.events import emit
from app.core.logging import get_logger
from app.models.brand import Brand
from app.models.content import ContentItem, ContentVariant
from app.models.enums import AccountStatus, ContentStatus, Platform, ScheduleStatus
from app.models.identity import User, Workspace
from app.models.scheduling import PostMetric, PublishAttempt, PublishedPost, RecurringSchedule, ScheduledPost
from app.models.social import SocialAccount
from app.services.publishing_service import PublishingService, _audit, _notify
from app.services.token_vault import TokenVault
from app.workers.queue import AlreadyEnqueued, cancel_pending, defer_in_txn, pending_exists

log = get_logger("scheduling")

PUBLISH_TASK = "jobs.publishing.publish_post"
RECONCILE_TASK = "jobs.publishing.reconcile"
PUBLISH_QUEUE = "publishing"
LATE_TOLERANCE_HOURS = 6
LEASE_MINUTES = 15
MATERIALIZE_AHEAD = timedelta(days=14)
LIVE = (ScheduleStatus.scheduled, ScheduleStatus.queued, ScheduleStatus.publishing)
MIN_GAP_MINUTES: dict[str, int] = {"instagram": 120, "linkedin": 240, "x": 30, "tiktok": 240, "youtube": 1440, "facebook": 120,
                                   "threads": 60, "pinterest": 60, "gbp": 1440}
# Generic priors (score 0..1) by platform → hour of day; weekends are damped for B2B platforms. Labeled "generic" in results.
_HOUR_PRIORS: dict[str, dict[int, float]] = {
    "default": {7: .5, 8: .7, 9: 1.0, 10: 1.0, 11: .9, 12: .8, 13: .8, 14: .6, 15: .6, 16: .6, 17: .8, 18: .8, 19: .7, 20: .5, 21: .4},
    "linkedin": {7: .6, 8: .9, 9: 1.0, 10: 1.0, 11: .8, 12: .7, 13: .6, 14: .5, 15: .5, 16: .6, 17: .7, 18: .5},
    "instagram": {8: .5, 9: .6, 10: .7, 11: .9, 12: 1.0, 13: .9, 14: .6, 15: .6, 16: .6, 17: .7, 18: .8, 19: 1.0, 20: .9, 21: .7},
    "tiktok": {10: .5, 11: .6, 12: .6, 14: .5, 16: .6, 17: .7, 18: .9, 19: 1.0, 20: 1.0, 21: .9, 22: .7},
    "x": {7: .6, 8: .9, 9: 1.0, 10: .9, 11: .7, 12: .9, 13: .7, 15: .6, 17: .9, 18: .8, 19: .6, 20: .5},
    "youtube": {12: .6, 13: .6, 14: .8, 15: 1.0, 16: 1.0, 17: .9, 18: .8, 19: .7, 20: .6},
    "facebook": {8: .6, 9: .8, 10: .9, 11: .9, 12: .8, 13: 1.0, 14: .8, 15: .8, 16: .7, 18: .7, 19: .8, 20: .7},
    "threads": {8: .6, 9: .7, 11: .8, 12: .9, 13: .8, 17: .8, 18: .9, 19: 1.0, 20: .9, 21: .8},
    "pinterest": {12: .5, 14: .6, 15: .7, 19: .8, 20: 1.0, 21: 1.0, 22: .9},
    "gbp": {9: .9, 10: 1.0, 11: .9, 12: .8, 14: .7, 16: .7},
}
_WEEKEND_DAMP = {"linkedin": 0.5, "x": 0.8, "gbp": 0.7}


def _now() -> datetime:
    return datetime.now(UTC)


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise validation(f"unknown timezone {name!r}", [{"code": "invalid_timezone", "field": "timezone", "message": str(e)}]) from e


def _ws_setting(ws: Workspace | None, *path: str, default: Any = None) -> Any:
    cur: Any = (ws.settings if ws else {}) or {}
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return default if cur is None else cur


def _user_id(member: Any) -> UUID | None:
    user = getattr(member, "user", None)
    if user is not None and getattr(user, "id", None):
        return user.id
    if isinstance(member, dict):
        v = member.get("user_id")
        return UUID(str(v)) if v else None
    return getattr(member, "user_id", None)


def _ws_id(member: Any) -> UUID:
    if isinstance(member, dict):
        return UUID(str(member["workspace_id"]))
    return member.workspace_id


def _has(member: Any, role: str) -> bool:
    fn = getattr(member, "has", None)
    return bool(fn(role)) if fn else True


# ==================================================================================================
# Scheduler-loop functions
# ==================================================================================================
_DUE_SQL = text("""
    UPDATE scheduled_posts SET status='queued', queued_at=now()
    WHERE id IN (SELECT id FROM scheduled_posts
                 WHERE status='scheduled' AND scheduled_at <= now()
                 ORDER BY priority DESC, scheduled_at
                 FOR UPDATE SKIP LOCKED LIMIT 50)
    RETURNING id, attempt_count, workspace_id
""")

_RETRY_SQL = text("""
    UPDATE scheduled_posts SET next_attempt_at=NULL, queued_at=now()
    WHERE id IN (SELECT id FROM scheduled_posts
                 WHERE status='queued' AND next_attempt_at IS NOT NULL AND next_attempt_at <= now()
                 ORDER BY priority DESC, next_attempt_at
                 FOR UPDATE SKIP LOCKED LIMIT 50)
    RETURNING id, attempt_count, workspace_id
""")


async def _enqueue_publish(db: AsyncSession, sp_id: UUID, attempt_no: int, workspace_id: UUID, priority: int = 0) -> bool:
    try:
        await defer_in_txn(db, PUBLISH_TASK, queue=PUBLISH_QUEUE, queueing_lock=f"publish:{sp_id}", priority=priority,
                           args={"scheduled_post_id": str(sp_id), "attempt_no": attempt_no, "workspace_id": str(workspace_id)})
        return True
    except AlreadyEnqueued:
        return False


async def dispatch_due_posts(db: AsyncSession) -> int:
    """Due ``scheduled`` rows → ``queued`` + publish job, in the caller's transaction (doc 12 §12.3).

    Before enqueueing, each row is re-checked: variant still approved, account active, not past the late tolerance;
    otherwise it is held as ``paused`` with a notification (never publish stale or unapproved content silently)."""
    rows = (await db.execute(_DUE_SQL)).mappings().all()
    if not rows:
        return 0
    now = _now()
    n = 0
    for r in rows:
        sp = await db.get(ScheduledPost, r["id"])
        if sp is None:
            continue
        ws = await db.get(Workspace, sp.workspace_id)
        late_h = float(_ws_setting(ws, "scheduling", "late_tolerance_hours", default=LATE_TOLERANCE_HOURS))
        variant = await db.get(ContentVariant, sp.content_variant_id)
        account = await db.get(SocialAccount, sp.social_account_id)
        reason: str | None = None
        title = body = None
        if variant is None or variant.status != ContentStatus.approved:
            reason, title = "variant_not_approved", "Post paused: content is not approved"
            body = f"The variant is {variant.status.value if variant else 'missing'}; approve it and resume the post."
        elif account is None or account.status != AccountStatus.active:
            reason, title = "account_inactive", "Post paused: social account needs reconnecting"
            body = f"{account.display_name if account else 'The account'} is {account.status.value if account else 'missing'}."
        elif now - sp.scheduled_at > timedelta(hours=late_h):
            reason, title = "missed_window", "Missed window — publish now or reschedule?"
            body = f"The post was due {sp.scheduled_at.isoformat()} but the scheduler was not running; it was held instead of publishing late."
        if reason:
            sp.status = ScheduleStatus.paused
            sp.queued_at = None
            sp.last_error = f"{reason}: {body}"
            await emit(db, "POST_PAUSED", {"scheduled_post_id": str(sp.id), "reason": reason, "content_variant_id": str(sp.content_variant_id),
                                           "social_account_id": str(sp.social_account_id), "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id)
            await _notify(db, sp.workspace_id, "publish.paused", title or "Post paused", body, f"/w/{ws.slug}/publishing" if ws else "/publishing",
                          user_id=sp.created_by, severity="warning")
            continue
        if await _enqueue_publish(db, sp.id, int(r["attempt_count"]) + 1, sp.workspace_id, priority=sp.priority):
            n += 1
    return n


async def dispatch_retries(db: AsyncSession) -> int:
    """``queued`` rows whose ``next_attempt_at`` passed → publish job (same transaction). Also re-enqueues orphaned
    ``queued`` rows (no pending job for > 10 min), which can only happen after manual queue surgery."""
    rows = (await db.execute(_RETRY_SQL)).mappings().all()
    n = 0
    for r in rows:
        if await _enqueue_publish(db, r["id"], int(r["attempt_count"]) + 1, r["workspace_id"]):
            n += 1
    stale_cutoff = _now() - timedelta(minutes=10)
    orphans = (await db.execute(select(ScheduledPost).where(ScheduledPost.status == ScheduleStatus.queued, ScheduledPost.next_attempt_at.is_(None),
                                                            ScheduledPost.queued_at < stale_cutoff).limit(50))).scalars().all()
    for sp in orphans:
        if await pending_exists(db, f"publish:{sp.id}"):
            continue
        sp.queued_at = _now()
        if await _enqueue_publish(db, sp.id, sp.attempt_count + 1, sp.workspace_id, priority=sp.priority):
            n += 1
    return n


async def expire_leases(db: AsyncSession) -> int:
    """``publishing`` rows older than 15 min without an attempt heartbeat → ``jobs.publishing.reconcile`` (which
    resumes via ``queued`` only after reconciliation proves nothing was posted, else records the post or fails)."""
    cutoff = _now() - timedelta(minutes=LEASE_MINUTES)
    fresh = exists().where(and_(PublishAttempt.scheduled_post_id == ScheduledPost.id, PublishAttempt.status == "running",
                                PublishAttempt.heartbeat_at >= cutoff))
    rows = (await db.execute(select(ScheduledPost).where(ScheduledPost.status == ScheduleStatus.publishing,
                                                         or_(ScheduledPost.publishing_started_at.is_(None), ScheduledPost.publishing_started_at < cutoff),
                                                         ~fresh).limit(50))).scalars().all()
    n = 0
    for sp in rows:
        if sp.publishing_started_at and sp.publishing_started_at < _now() - timedelta(hours=24):
            # reconciliation itself keeps failing → stop looping; a human verifies
            sp.status = ScheduleStatus.failed
            sp.last_error = "stuck in publishing for 24 h; reconciliation failed repeatedly — verify manually"
            await emit(db, "PUBLISH_FAILED", {"scheduled_post_id": str(sp.id), "category": "ambiguous", "message": sp.last_error,
                                              "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id)
            n += 1
            continue
        lock = f"reconcile:{sp.id}"
        if await pending_exists(db, lock):
            continue
        try:
            await defer_in_txn(db, RECONCILE_TASK, queue=PUBLISH_QUEUE, queueing_lock=lock,
                               args={"scheduled_post_id": str(sp.id), "workspace_id": str(sp.workspace_id)})
            sp.last_error = "worker lease expired; reconciling with the platform"
            n += 1
        except AlreadyEnqueued:
            continue
    return n


async def materialize_recurring(db: AsyncSession, *, ahead: timedelta = MATERIALIZE_AHEAD, now: datetime | None = None) -> int:
    """Expand active ``recurring_schedules`` (kind ``repost_variant``) into concrete ``scheduled_posts`` up to 14 days ahead.
    ``slot_template``/``automation`` kinds are materialized by their owners (automation engine)."""
    now = now or _now()
    horizon = now + ahead
    rows = (await db.execute(select(RecurringSchedule).where(RecurringSchedule.status == "active", RecurringSchedule.kind == "repost_variant",
                                                             or_(RecurringSchedule.last_materialized_until.is_(None),
                                                                 RecurringSchedule.last_materialized_until < horizon)))).scalars().all()
    created = 0
    for r in rows:
        payload = r.payload or {}
        try:
            variant_id = UUID(str(payload["content_variant_id"]))
            account_id = UUID(str(payload["social_account_id"]))
        except (KeyError, ValueError):
            r.status = "paused"
            log.warning("recurring.invalid_payload", id=str(r.id))
            continue
        tz = ZoneInfo(r.timezone or "UTC")
        dtstart_raw = payload.get("dtstart")
        dtstart = datetime.fromisoformat(dtstart_raw).astimezone(tz) if dtstart_raw else (r.created_at or now).astimezone(tz)
        try:
            rule = rrulestr(r.rrule, dtstart=dtstart.replace(tzinfo=None))
        except (ValueError, TypeError) as e:
            r.status = "paused"
            log.warning("recurring.invalid_rrule", id=str(r.id), error=str(e))
            continue
        start = max(r.last_materialized_until or now, now)
        start_local = start.astimezone(tz).replace(tzinfo=None)
        end_local = horizon.astimezone(tz).replace(tzinfo=None)
        occurrences = list(rule.between(start_local, end_local, inc=True))
        for occ in occurrences:
            local = occ.replace(tzinfo=tz, fold=0)   # DST gaps shift forward, ambiguous times → first occurrence
            at = local.astimezone(UTC)
            dup = (await db.execute(select(ScheduledPost.id).where(ScheduledPost.recurring_schedule_id == r.id, ScheduledPost.scheduled_at == at))).first()
            if dup:
                continue
            sp = ScheduledPost(workspace_id=r.workspace_id, brand_id=r.brand_id, content_variant_id=variant_id, social_account_id=account_id,
                               scheduled_at=at, timezone=r.timezone, status=ScheduleStatus.scheduled, priority=int(payload.get("priority") or 0),
                               recurring_schedule_id=r.id, created_by=r.created_by)
            try:
                async with db.begin_nested():   # add inside: begin_nested() flushes pending objects before the SAVEPOINT
                    db.add(sp)
                    await db.flush()
                created += 1
                await emit(db, "POST_SCHEDULED", {"scheduled_post_id": str(sp.id), "content_variant_id": str(variant_id), "social_account_id": str(account_id),
                                                  "scheduled_at": at.isoformat(), "recurring_schedule_id": str(r.id), "brand_id": str(r.brand_id)},
                           workspace_id=r.workspace_id)
            except IntegrityError:
                continue   # a live schedule for this variant/account already exists
        r.last_materialized_until = horizon
        nxt = rule.after(end_local)
        r.next_run_at = nxt.replace(tzinfo=tz).astimezone(UTC) if nxt else None
    return created


# ==================================================================================================
# SchedulingService
# ==================================================================================================
class SchedulingService:
    def __init__(self, publishing: PublishingService | None = None, vault: TokenVault | None = None) -> None:
        self.publishing = publishing or PublishingService()
        self.vault = vault or self.publishing.vault

    # ---- lookups -----------------------------------------------------------------------------------------
    async def get(self, db: AsyncSession, workspace_id: UUID, sp_id: UUID, *, for_update: bool = False) -> ScheduledPost:
        q = select(ScheduledPost).where(ScheduledPost.id == sp_id, ScheduledPost.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        sp = (await db.execute(q)).scalars().unique().one_or_none()
        if sp is None:
            raise not_found("Scheduled post")
        return sp

    async def list(self, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, status: list[str] | None = None,
                   platform: str | None = None, social_account_id: UUID | None = None, since: datetime | None = None, until: datetime | None = None,
                   limit: int = 200, offset: int = 0) -> list[ScheduledPost]:
        q = select(ScheduledPost).where(ScheduledPost.workspace_id == workspace_id)
        if brand_id:
            q = q.where(ScheduledPost.brand_id == brand_id)
        if status:
            q = q.where(ScheduledPost.status.in_([ScheduleStatus(s) for s in status]))
        if social_account_id:
            q = q.where(ScheduledPost.social_account_id == social_account_id)
        if platform:
            q = q.join(SocialAccount, SocialAccount.id == ScheduledPost.social_account_id).where(SocialAccount.platform == Platform(platform))
        if since:
            q = q.where(ScheduledPost.scheduled_at >= since)
        if until:
            q = q.where(ScheduledPost.scheduled_at <= until)
        return list((await db.execute(q.order_by(ScheduledPost.scheduled_at.asc()).offset(offset).limit(limit))).scalars().unique())

    # ---- schedule ----------------------------------------------------------------------------------------
    async def schedule(self, db: AsyncSession, member: Any, variant_id: UUID, account_id: UUID, scheduled_at: datetime, timezone: str,
                       priority: int = 0, *, force: bool = False, recurring_schedule_id: UUID | None = None, created_by: UUID | None = None,
                       actor: dict[str, Any] | None = None) -> ScheduledPost:
        ws_id = _ws_id(member)
        if not _has(member, "editor"):
            raise forbidden("Scheduling requires editor or higher")
        tz = _tz(timezone)
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=tz)
        at = scheduled_at.astimezone(UTC)
        variant = await db.get(ContentVariant, variant_id)
        if variant is None or variant.workspace_id != ws_id:
            raise not_found("Content variant")
        item = await db.get(ContentItem, variant.content_item_id)
        account = await db.get(SocialAccount, account_id)
        if account is None or account.workspace_id != ws_id:
            raise not_found("Social account")
        errors: list[dict[str, Any]] = []
        if account.platform != variant.platform:
            errors.append({"code": "platform_mismatch", "field": "social_account_id",
                           "message": f"variant targets {variant.platform.value} but the account is {account.platform.value}"})
        if account.status != AccountStatus.active:
            errors.append({"code": "account_not_active", "field": "social_account_id", "message": f"account is {account.status.value}; reconnect it first"})
        ws = await db.get(Workspace, ws_id)
        allow_drafts = bool(_ws_setting(ws, "scheduling", "allow_drafts", default=False))
        if variant.status != ContentStatus.approved and not (allow_drafts and variant.status in (ContentStatus.draft, ContentStatus.ai_generated, ContentStatus.needs_review)):
            errors.append({"code": "variant_not_approved", "field": "content_variant_id", "message": f"variant is {variant.status.value}; approve it before scheduling"})
        if errors:
            raise validation("Cannot schedule", errors)
        # token expiry vs scheduled time (refuse when the platform cannot refresh)
        tokens = None
        try:
            tokens = await self.vault.get_tokens(db, account)
        except LookupError:
            raise validation("Cannot schedule", [{"code": "no_token", "field": "social_account_id", "message": "account has no live token; reconnect it"}]) from None
        adapter = self.publishing.adapter_for(account)
        if tokens.expires_at and tokens.expires_at < at and not adapter.refresh_supported(tokens):
            raise validation("Cannot schedule", [{"code": "token_expires_before_schedule", "field": "scheduled_at",
                                                  "message": f"the {account.platform.value} token expires {tokens.expires_at.isoformat()} and cannot be refreshed; reconnect closer to the date"}])
        # content validation (deterministic + adapter) — stored on the variant for Studio
        vres, req = await self.publishing.validate(db, variant, account)
        variant.validation = vres
        if not vres["ok"]:
            raise validation("Content failed platform validation", vres["errors"])
        # limit headroom from the last probe
        remaining = ((account.health or {}).get("limits_remaining") or {}).get("posts_24h")
        if remaining is not None and remaining <= 0:
            raise validation("Cannot schedule", [{"code": "platform_limit_reached", "field": "social_account_id",
                                                  "message": "the platform's 24-hour publishing limit is exhausted for this account"}])
        # duplicate fingerprint within 24 h (409 unless force)
        dup = await self.publishing.find_duplicate(db, account.id, req.fingerprint)
        if dup is not None and not force:
            raise ProblemError(409, "possible_duplicate", "Possible duplicate",
                               f"the same content was published to this account at {dup.published_at.isoformat()} (post {dup.external_id}); pass force=true to override")
        user_id = created_by or _user_id(member) or (item.created_by if item else None)
        if user_id is None:
            raise validation("Cannot schedule", [{"code": "created_by_required", "field": "created_by", "message": "no user to attribute the schedule to"}])
        sp = ScheduledPost(workspace_id=ws_id, brand_id=(item.brand_id if item else account.brand_id), content_variant_id=variant.id,
                           social_account_id=account.id, scheduled_at=at, timezone=timezone, status=ScheduleStatus.scheduled, priority=priority,
                           recurring_schedule_id=recurring_schedule_id, created_by=user_id)
        try:
            async with db.begin_nested():   # add inside: begin_nested() flushes pending objects before the SAVEPOINT
                db.add(sp)
                await db.flush()
        except IntegrityError as e:
            raise conflict("duplicate_live_schedule", "this variant is already scheduled, queued or publishing on this account") from e
        if force and dup is not None:
            # seed state so the worker-time duplicate check honours the override (attempt 0 is never executed)
            db.add(PublishAttempt(workspace_id=ws_id, scheduled_post_id=sp.id, attempt_no=0, idempotency_key=f"{sp.idempotency_root}:0", status="seed",
                                  state={"allow_duplicate": True}, request_fingerprint=req.fingerprint, finished_at=_now()))
            await db.flush()
        await emit(db, "POST_SCHEDULED", {"scheduled_post_id": str(sp.id), "content_variant_id": str(variant.id), "social_account_id": str(account.id),
                                          "scheduled_at": at.isoformat(), "timezone": timezone, "brand_id": str(sp.brand_id), "platform": account.platform.value,
                                          "warnings": vres.get("warnings", [])}, workspace_id=ws_id,
                   actor=actor or {"type": "user", "id": str(user_id)})
        await _audit(db, member if not isinstance(member, dict) else actor or member, "scheduling.schedule", "scheduled_post", sp.id,
                     after={"scheduled_at": at.isoformat(), "variant_id": str(variant.id), "account_id": str(account.id)}, workspace_id=ws_id)
        return sp

    async def schedule_from_proposal(self, db: AsyncSession, workspace_id: UUID, *, variant_id: Any, scheduled_at: datetime, social_account_id: Any = None,
                                     platform: str | None = None, note: str | None = None, actor: dict[str, Any] | None = None, priority: int = 0) -> ScheduledPost:
        """Executed by the ApprovalGate after a human approved ``publishing.propose_schedule`` (doc 05 §5.2.8)."""
        ws_id = UUID(str(workspace_id))
        variant = await db.get(ContentVariant, UUID(str(variant_id)))
        if variant is None or variant.workspace_id != ws_id:
            raise not_found("Content variant")
        account_id = UUID(str(social_account_id)) if social_account_id else None
        if account_id is None:
            q = select(SocialAccount).where(SocialAccount.workspace_id == ws_id, SocialAccount.status == AccountStatus.active)
            item = await db.get(ContentItem, variant.content_item_id)
            if item:
                q = q.where(SocialAccount.brand_id == item.brand_id)
            q = q.where(SocialAccount.platform == (Platform(platform) if platform else variant.platform))
            if variant.social_account_id:
                q = q.where(SocialAccount.id == variant.social_account_id)
            accounts = (await db.execute(q)).scalars().all()
            if len(accounts) != 1:
                raise validation("Cannot schedule", [{"code": "account_ambiguous", "field": "social_account_id",
                                                      "message": f"{len(accounts)} candidate accounts; specify social_account_id"}])
            account_id = accounts[0].id
        item = await db.get(ContentItem, variant.content_item_id)
        brand = await db.get(Brand, item.brand_id) if item else None
        user_id = None
        for key in ("user_id", "approved_by", "requested_by"):
            if actor and actor.get(key):
                try:
                    user_id = UUID(str(actor[key]))
                    break
                except ValueError:
                    continue
        user_id = user_id or (item.created_by if item else None) or (brand.created_by if brand else None)
        member = {"workspace_id": ws_id, "user_id": user_id, "type": actor.get("type", "agent") if actor else "agent", "id": (actor or {}).get("id")}
        sp = await self.schedule(db, member, variant.id, account_id, scheduled_at, (brand.timezone if brand else "UTC"), priority, created_by=user_id,
                                 actor=actor)
        if note:
            sp.last_error = None
        return sp

    # ---- operations (doc 12 §12.4) ----------------------------------------------------------------------
    async def reschedule(self, db: AsyncSession, member: Any, sp_id: UUID, *, scheduled_at: datetime | None = None, timezone: str | None = None,
                         priority: int | None = None) -> ScheduledPost:
        sp = await self.get(db, _ws_id(member), sp_id, for_update=True)
        if not _has(member, "editor"):
            raise forbidden("Requires editor")
        if sp.status not in (ScheduleStatus.scheduled, ScheduleStatus.queued):
            raise conflict("invalid_transition", f"cannot edit a post in status {sp.status.value}")
        before = {"scheduled_at": sp.scheduled_at.isoformat(), "timezone": sp.timezone, "priority": sp.priority}
        if timezone:
            _tz(timezone)
            sp.timezone = timezone
        if scheduled_at is not None:
            tz = _tz(sp.timezone)
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=tz)
            new_at = scheduled_at.astimezone(UTC)
            if sp.status == ScheduleStatus.queued:
                await cancel_pending(db, f"publish:{sp.id}")
                sp.status = ScheduleStatus.scheduled
                sp.next_attempt_at = None
                sp.queued_at = None
            sp.scheduled_at = new_at
        if priority is not None:
            sp.priority = priority
        await emit(db, "POST_RESCHEDULED", {"scheduled_post_id": str(sp.id), "scheduled_at": sp.scheduled_at.isoformat(), "timezone": sp.timezone,
                                            "before": before, "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id,
                   actor={"type": "user", "id": str(_user_id(member))})
        await _audit(db, member, "scheduling.reschedule", "scheduled_post", sp.id, before=before,
                     after={"scheduled_at": sp.scheduled_at.isoformat(), "timezone": sp.timezone, "priority": sp.priority}, workspace_id=sp.workspace_id)
        return sp

    async def pause(self, db: AsyncSession, member: Any, sp_id: UUID) -> ScheduledPost:
        sp = await self.get(db, _ws_id(member), sp_id, for_update=True)
        if sp.status != ScheduleStatus.scheduled:
            raise conflict("invalid_transition", f"only scheduled posts can be paused (status {sp.status.value})")
        sp.status = ScheduleStatus.paused
        await emit(db, "POST_PAUSED", {"scheduled_post_id": str(sp.id), "reason": "user", "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id,
                   actor={"type": "user", "id": str(_user_id(member))})
        await _audit(db, member, "scheduling.pause", "scheduled_post", sp.id, workspace_id=sp.workspace_id)
        return sp

    async def resume(self, db: AsyncSession, member: Any, sp_id: UUID, *, scheduled_at: datetime | None = None) -> ScheduledPost:
        sp = await self.get(db, _ws_id(member), sp_id, for_update=True)
        if sp.status != ScheduleStatus.paused:
            raise conflict("invalid_transition", f"only paused posts can be resumed (status {sp.status.value})")
        if scheduled_at is not None:
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=_tz(sp.timezone))
            sp.scheduled_at = scheduled_at.astimezone(UTC)
        elif sp.scheduled_at < _now():
            raise conflict("time_passed", "the scheduled time has passed; provide a new scheduled_at to resume")
        sp.status = ScheduleStatus.scheduled
        sp.last_error = None
        await emit(db, "POST_RESCHEDULED", {"scheduled_post_id": str(sp.id), "scheduled_at": sp.scheduled_at.isoformat(), "resumed": True,
                                            "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id, actor={"type": "user", "id": str(_user_id(member))})
        await _audit(db, member, "scheduling.resume", "scheduled_post", sp.id, workspace_id=sp.workspace_id)
        return sp

    async def cancel(self, db: AsyncSession, member: Any, sp_id: UUID) -> ScheduledPost:
        sp = await self.get(db, _ws_id(member), sp_id, for_update=True)
        if sp.status not in (ScheduleStatus.scheduled, ScheduleStatus.queued, ScheduleStatus.paused, ScheduleStatus.failed):
            raise conflict("invalid_transition", f"cannot cancel a post in status {sp.status.value}")
        await cancel_pending(db, f"publish:{sp.id}")
        sp.status = ScheduleStatus.cancelled
        sp.next_attempt_at = None
        await emit(db, "POST_CANCELLED", {"scheduled_post_id": str(sp.id), "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id,
                   actor={"type": "user", "id": str(_user_id(member))})
        await _audit(db, member, "scheduling.cancel", "scheduled_post", sp.id, workspace_id=sp.workspace_id)
        return sp

    async def retry(self, db: AsyncSession, member: Any, sp_id: UUID) -> ScheduledPost:
        sp = await self.get(db, _ws_id(member), sp_id, for_update=True)
        if not _has(member, "editor"):
            raise forbidden("Requires editor")
        if sp.status != ScheduleStatus.failed:
            raise conflict("invalid_transition", f"only failed posts can be retried (status {sp.status.value})")
        sp.status = ScheduleStatus.queued
        sp.queued_at = _now()
        sp.next_attempt_at = None
        sp.last_error = None
        if sp.attempt_count >= sp.max_attempts:
            sp.max_attempts = sp.attempt_count + 1   # a manual retry always gets one more attempt
        await _enqueue_publish(db, sp.id, sp.attempt_count + 1, sp.workspace_id, priority=sp.priority)
        await emit(db, "POST_SCHEDULED", {"scheduled_post_id": str(sp.id), "retry": True, "brand_id": str(sp.brand_id)}, workspace_id=sp.workspace_id,
                   actor={"type": "user", "id": str(_user_id(member))})
        await _audit(db, member, "scheduling.retry", "scheduled_post", sp.id, workspace_id=sp.workspace_id)
        return sp

    async def publish_now(self, db: AsyncSession, member: Any, variant_id: UUID, account_id: UUID, *, force: bool = False) -> ScheduledPost:
        """Existing scheduled/paused post for the pair → now + priority 10; otherwise a new schedule at now()."""
        ws_id = _ws_id(member)
        existing = (await db.execute(select(ScheduledPost).where(ScheduledPost.workspace_id == ws_id, ScheduledPost.content_variant_id == variant_id,
                                                                 ScheduledPost.social_account_id == account_id,
                                                                 ScheduledPost.status.in_((ScheduleStatus.scheduled, ScheduleStatus.paused)))
                                     .with_for_update())).scalars().unique().first()
        if existing is not None:
            if existing.status == ScheduleStatus.paused:
                existing.status = ScheduleStatus.scheduled
                existing.last_error = None
            existing.scheduled_at = _now()
            existing.priority = 10
            await emit(db, "POST_RESCHEDULED", {"scheduled_post_id": str(existing.id), "publish_now": True, "brand_id": str(existing.brand_id)},
                       workspace_id=ws_id, actor={"type": "user", "id": str(_user_id(member))})
            await _audit(db, member, "publishing.publish_now", "scheduled_post", existing.id, workspace_id=ws_id)
            return existing
        account = await db.get(SocialAccount, account_id)
        tzname = "UTC"
        if account is not None:
            brand = await db.get(Brand, account.brand_id)
            tzname = brand.timezone if brand else "UTC"
        sp = await self.schedule(db, member, variant_id, account_id, _now(), tzname, 10, force=force)
        await _audit(db, member, "publishing.publish_now", "scheduled_post", sp.id, workspace_id=ws_id)
        return sp

    # ---- recurring ---------------------------------------------------------------------------------------
    async def create_recurring(self, db: AsyncSession, member: Any, data: dict[str, Any]) -> RecurringSchedule:
        ws_id = _ws_id(member)
        if not _has(member, "editor"):
            raise forbidden("Requires editor")
        _tz(data.get("timezone") or "UTC")
        try:
            rrulestr(data["rrule"], dtstart=_now().replace(tzinfo=None))
        except (KeyError, ValueError) as e:
            raise validation("Invalid rrule", [{"code": "invalid_rrule", "field": "rrule", "message": str(e)}]) from e
        kind = data.get("kind") or "repost_variant"
        payload = dict(data.get("payload") or {})
        if kind == "repost_variant":
            try:
                variant = await db.get(ContentVariant, UUID(str(payload["content_variant_id"])))
                account = await db.get(SocialAccount, UUID(str(payload["social_account_id"])))
            except (KeyError, ValueError) as e:
                raise validation("payload needs content_variant_id and social_account_id", [{"code": "payload", "field": "payload", "message": str(e)}]) from e
            if variant is None or variant.workspace_id != ws_id or account is None or account.workspace_id != ws_id:
                raise not_found("Variant or account")
        r = RecurringSchedule(workspace_id=ws_id, brand_id=UUID(str(data["brand_id"])), name=data["name"], rrule=data["rrule"],
                              timezone=data.get("timezone") or "UTC", kind=kind, payload=payload, status="active", created_by=_user_id(member))
        db.add(r)
        await db.flush()
        if kind == "repost_variant":
            await materialize_recurring(db)
        await _audit(db, member, "scheduling.recurring.create", "recurring_schedule", r.id, after={"rrule": r.rrule, "kind": kind}, workspace_id=ws_id)
        return r

    async def list_recurring(self, db: AsyncSession, workspace_id: UUID, brand_id: UUID | None = None) -> list[RecurringSchedule]:
        q = select(RecurringSchedule).where(RecurringSchedule.workspace_id == workspace_id)
        if brand_id:
            q = q.where(RecurringSchedule.brand_id == brand_id)
        return list((await db.execute(q.order_by(RecurringSchedule.created_at.desc()))).scalars())

    # ---- best times (doc 12 §12.6) ----------------------------------------------------------------------
    async def best_times(self, db: AsyncSession, brand_id: UUID, platform: str, social_account_id: UUID | None, from_: datetime, to: datetime,
                         count: int = 5, *, workspace_id: UUID | None = None) -> dict[str, Any]:
        brand = await db.get(Brand, brand_id)
        account = await db.get(SocialAccount, social_account_id) if social_account_id else None
        ws = await db.get(Workspace, brand.workspace_id) if brand else None
        tz = _tz(brand.timezone if brand else "UTC")
        plat = Platform(platform)
        # 1) observed engagement by (weekday, hour) — latest capture per post over the last 90 days
        latest = (select(PostMetric.published_post_id, func.max(PostMetric.captured_at).label("captured_at"))
                  .group_by(PostMetric.published_post_id).subquery())
        q = (select(PostMetric.engagement_rate, PublishedPost.published_at)
             .join(latest, and_(latest.c.published_post_id == PostMetric.published_post_id, latest.c.captured_at == PostMetric.captured_at))
             .join(PublishedPost, PublishedPost.id == PostMetric.published_post_id)
             .where(PublishedPost.brand_id == brand_id, PublishedPost.platform == plat, PublishedPost.deleted_at.is_(None),
                    PublishedPost.published_at >= _now() - timedelta(days=90), PostMetric.engagement_rate.is_not(None)))
        if account is not None:
            q = q.where(PublishedPost.social_account_id == account.id)
        cells: dict[tuple[int, int], list[float]] = defaultdict(list)
        for rate, published_at in (await db.execute(q)).all():
            local = published_at.astimezone(tz)
            cells[(local.weekday(), local.hour)].append(float(rate))
        total_posts = sum(len(v) for v in cells.values())
        observed_max = max((statistics.mean(v) for v in cells.values() if len(v) >= 3), default=0.0)
        priors = _HOUR_PRIORS.get(platform, _HOUR_PRIORS["default"])
        damp = _WEEKEND_DAMP.get(platform, 0.9)
        # 2) occupied slots on the account (min gap) and token expiry
        gap_min = int(_ws_setting(ws, "scheduling", "min_gap_minutes", platform, default=MIN_GAP_MINUTES.get(platform, 60)))
        occupied: list[datetime] = []
        token_expiry: datetime | None = None
        if account is not None:
            rows = (await db.execute(select(ScheduledPost.scheduled_at).where(ScheduledPost.social_account_id == account.id,
                                                                            ScheduledPost.status.in_((*LIVE, ScheduleStatus.paused)),
                                                                            ScheduledPost.scheduled_at.between(from_ - timedelta(minutes=gap_min), to + timedelta(minutes=gap_min))))).scalars().all()
            occupied = list(rows)
            pub = (await db.execute(select(PublishedPost.published_at).where(PublishedPost.social_account_id == account.id, PublishedPost.deleted_at.is_(None),
                                                                           PublishedPost.published_at >= from_ - timedelta(minutes=gap_min)))).scalars().all()
            occupied += list(pub)
            try:
                token_expiry = await self.vault.access_expires_at(db, account.id)
                adapter = self.publishing.adapter_for(account)
                if adapter.refresh_supported(await self.vault.get_tokens(db, account)):
                    token_expiry = None
            except LookupError:
                token_expiry = None
        # 3) candidate slots: every hour in the window (brand tz), scored, filtered, ranked
        start = max(from_.astimezone(tz), _now().astimezone(tz)).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end = to.astimezone(tz)
        slots: list[dict[str, Any]] = []
        cur = start
        while cur <= end:
            at_utc = cur.astimezone(UTC)
            if token_expiry and at_utc > token_expiry:
                break
            if any(abs((at_utc - o).total_seconds()) < gap_min * 60 for o in occupied):
                cur += timedelta(hours=1)
                continue
            key = (cur.weekday(), cur.hour)
            obs = cells.get(key, [])
            if len(obs) >= 3:
                score, basis, n = statistics.mean(obs) / observed_max if observed_max else 0.0, "observed", len(obs)
            else:
                score = priors.get(cur.hour, 0.2) * (damp if cur.weekday() >= 5 else 1.0)
                basis, n = "generic", len(obs)
                if obs:   # blend thin evidence with the prior
                    score = 0.5 * score + 0.5 * (statistics.mean(obs) / observed_max if observed_max else score)
                    basis = "blended"
            slots.append({"at": at_utc.isoformat(), "local": cur.isoformat(), "weekday": cur.weekday(), "hour": cur.hour,
                          "score": round(float(score), 4), "basis": basis, "n": n})
            cur += timedelta(hours=1)
        slots.sort(key=lambda s: (-s["score"], s["at"]))
        chosen: list[dict[str, Any]] = []
        for s in slots:
            s_at = datetime.fromisoformat(s["at"])
            if any(abs((s_at - datetime.fromisoformat(c["at"])).total_seconds()) < gap_min * 60 for c in chosen):
                continue
            chosen.append(s)
            if len(chosen) >= count:
                break
        evidence = f"based on {total_posts} posts" if total_posts else "generic prior"
        return {"slots": chosen, "timezone": tz.key, "evidence": evidence, "n_posts": total_posts, "min_gap_minutes": gap_min,
                "token_expires_at": token_expiry.isoformat() if token_expiry else None}

    # ---- calendar (doc 12 §12.8) ------------------------------------------------------------------------
    async def calendar(self, db: AsyncSession, workspace_id: UUID, from_: datetime, to: datetime, *, brand_id: UUID | None = None,
                       platform: list[str] | None = None, status: list[str] | None = None, campaign: UUID | None = None, pillar: UUID | None = None,
                       member: UUID | None = None, approval: str | None = None, include_tray: bool = True) -> dict[str, Any]:
        q = (select(ScheduledPost, ContentVariant, ContentItem, SocialAccount, User.full_name)
             .join(ContentVariant, ContentVariant.id == ScheduledPost.content_variant_id)
             .join(ContentItem, ContentItem.id == ContentVariant.content_item_id)
             .join(SocialAccount, SocialAccount.id == ScheduledPost.social_account_id)
             .join(User, User.id == ScheduledPost.created_by, isouter=True)
             .where(ScheduledPost.workspace_id == workspace_id, ScheduledPost.scheduled_at >= from_, ScheduledPost.scheduled_at <= to))
        if brand_id:
            q = q.where(ScheduledPost.brand_id == brand_id)
        if platform:
            q = q.where(SocialAccount.platform.in_([Platform(p) for p in platform]))
        if status:
            q = q.where(ScheduledPost.status.in_([ScheduleStatus(s) for s in status]))
        if campaign:
            q = q.where(ContentItem.campaign_id == campaign)
        if pillar:
            q = q.where(ContentItem.pillar_id == pillar)
        if member:
            q = q.where(or_(ScheduledPost.created_by == member, ContentItem.assigned_to == member))
        if approval == "pending":
            q = q.where(ContentItem.status == ContentStatus.needs_review)
        elif approval == "approved":
            q = q.where(ContentItem.status == ContentStatus.approved)
        rows = (await db.execute(q.order_by(ScheduledPost.scheduled_at.asc()))).unique().all()
        sp_ids = [r[0].id for r in rows]
        urls: dict[UUID, str | None] = {}
        if sp_ids:
            for pp in (await db.execute(select(PublishedPost).where(PublishedPost.scheduled_post_id.in_(sp_ids), PublishedPost.deleted_at.is_(None)))).scalars():
                urls[pp.scheduled_post_id] = pp.external_url
        cards = [self._card(sp, v, item, acc, name, urls.get(sp.id)) for sp, v, item, acc, name in rows]
        tray: list[dict[str, Any]] = []
        if include_tray:
            live = exists().where(and_(ScheduledPost.content_variant_id == ContentVariant.id, ScheduledPost.status.in_((*LIVE, ScheduleStatus.paused, ScheduleStatus.published))))
            tq = (select(ContentVariant, ContentItem).join(ContentItem, ContentItem.id == ContentVariant.content_item_id)
                  .where(ContentVariant.workspace_id == workspace_id, ContentVariant.status == ContentStatus.approved, ContentItem.deleted_at.is_(None), ~live))
            if brand_id:
                tq = tq.where(ContentItem.brand_id == brand_id)
            if platform:
                tq = tq.where(ContentVariant.platform.in_([Platform(p) for p in platform]))
            if campaign:
                tq = tq.where(ContentItem.campaign_id == campaign)
            if pillar:
                tq = tq.where(ContentItem.pillar_id == pillar)
            for v, item in (await db.execute(tq.order_by(ContentVariant.updated_at.desc()).limit(200))).unique().all():
                tray.append({"id": str(v.id), "kind": "unscheduled", "status": "approved", "platform": v.platform.value, "format": v.format.value,
                             "content_item": {"id": str(item.id), "title": item.title, "status": item.status.value, "pillar_id": str(item.pillar_id) if item.pillar_id else None,
                                              "campaign_id": str(item.campaign_id) if item.campaign_id else None, "content_type": item.content_type.value if item.content_type else None},
                             "variant": {"id": str(v.id), "format": v.format.value, "text_preview": (v.text or "")[:140], "media_count": len(v.assets or []),
                                         "social_account_id": str(v.social_account_id) if v.social_account_id else None}})
        return {"from": from_.isoformat(), "to": to.isoformat(), "cards": cards, "tray": tray}

    @staticmethod
    def _card(sp: ScheduledPost, v: ContentVariant, item: ContentItem, acc: SocialAccount, creator: str | None, url: str | None) -> dict[str, Any]:
        return {"id": str(sp.id), "kind": "scheduled_post", "status": sp.status.value, "scheduled_at": sp.scheduled_at.isoformat(), "timezone": sp.timezone,
                "platform": acc.platform.value, "priority": sp.priority, "attempt_count": sp.attempt_count, "last_error": sp.last_error,
                "next_attempt_at": sp.next_attempt_at.isoformat() if sp.next_attempt_at else None, "published_at": sp.published_at.isoformat() if sp.published_at else None,
                "published_url": url, "recurring_schedule_id": str(sp.recurring_schedule_id) if sp.recurring_schedule_id else None,
                "account": {"id": str(acc.id), "platform": acc.platform.value, "display_name": acc.display_name, "handle": acc.handle, "avatar_url": acc.avatar_url},
                "content_item": {"id": str(item.id), "title": item.title, "status": item.status.value, "pillar_id": str(item.pillar_id) if item.pillar_id else None,
                                 "campaign_id": str(item.campaign_id) if item.campaign_id else None, "content_type": item.content_type.value if item.content_type else None,
                                 "risk_level": item.risk_level.value if item.risk_level else None},
                "variant": {"id": str(v.id), "format": v.format.value, "text_preview": (v.text or "")[:140], "media_count": len(v.assets or []), "status": v.status.value},
                "created_by": {"id": str(sp.created_by), "name": creator}}


def serialize_scheduled_post(sp: ScheduledPost, account: SocialAccount | None = None, creator: User | None = None, validation_: dict[str, Any] | None = None) -> dict[str, Any]:
    """Doc 17 §17.3 ScheduledPost envelope."""
    attempts = [{"id": str(a.id), "attempt_no": a.attempt_no, "status": a.status, "error_category": a.error_category, "error_code": a.error_code,
                 "error_message": a.error_message, "started_at": a.started_at.isoformat() if a.started_at else None,
                 "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                 "segments_done": len((a.state or {}).get("segment_external_ids") or [])} for a in (sp.attempts or []) if a.attempt_no > 0]
    partial = next((a["segments_done"] for a in reversed(attempts) if a["segments_done"]), 0) if sp.status != ScheduleStatus.published else 0
    return {"id": str(sp.id), "workspace_id": str(sp.workspace_id), "brand_id": str(sp.brand_id), "content_variant_id": str(sp.content_variant_id),
            "social_account_id": str(sp.social_account_id),
            "social_account": {"id": str(account.id), "platform": account.platform.value, "display_name": account.display_name, "handle": account.handle} if account else None,
            "scheduled_at": sp.scheduled_at.isoformat(), "timezone": sp.timezone, "status": sp.status.value, "priority": sp.priority,
            "attempt_count": sp.attempt_count, "max_attempts": sp.max_attempts, "next_attempt_at": sp.next_attempt_at.isoformat() if sp.next_attempt_at else None,
            "queued_at": sp.queued_at.isoformat() if sp.queued_at else None, "publishing_started_at": sp.publishing_started_at.isoformat() if sp.publishing_started_at else None,
            "published_at": sp.published_at.isoformat() if sp.published_at else None, "last_error": sp.last_error, "partially_published_segments": partial,
            "recurring_schedule_id": str(sp.recurring_schedule_id) if sp.recurring_schedule_id else None, "native_schedule": sp.native_schedule,
            "validation": validation_, "attempts": attempts,
            "created_by": {"id": str(sp.created_by), "name": creator.full_name if creator else None}, "created_at": sp.created_at.isoformat() if sp.created_at else None,
            "updated_at": sp.updated_at.isoformat() if sp.updated_at else None}
