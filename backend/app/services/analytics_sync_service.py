"""AnalyticsSyncService (doc 13 §13.3): account metrics daily, post metrics on a decaying cadence, quota awareness,
per-metric failures never fail the whole sync, ``ANALYTICS_*`` events, snapshots recomputed afterwards."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.normalize import ACCOUNT_METRIC_KEYS, POST_METRIC_KEYS
from app.analytics.snapshots import recompute_snapshots
from app.core.events import emit
from app.core.logging import get_logger
from app.core.ports.social_adapter import PublishError
from app.integrations.social.registry import get_adapter
from app.models.brand import Brand
from app.models.enums import AccountStatus
from app.models.platform import UsageBudget, UsageLedger
from app.models.scheduling import AccountMetric, PostMetric, PublishedPost
from app.models.social import SocialAccount
from app.services.publishing_service import _notify
from app.services.token_vault import TokenVault
from app.workers.queue import AlreadyEnqueued, defer_in_txn

log = get_logger("analytics.sync")

# decaying cadence after publish (hours): 1h, 6h, 24h, 72h, 7d, 14d, 30d, then monthly × 6
CADENCE_HOURS: tuple[int, ...] = (1, 6, 24, 72, 168, 336, 720, 1440, 2160, 2880, 3600, 4320, 5040)
PLATFORM_LAST_PULL_HOURS: dict[str, int] = {"x": 720}   # owner-only X metrics stop at 30 days → last pull at day 30
ACCOUNT_SYNC_HOUR = 3
READ_COST_USD: dict[str, float] = {"x": 0.001}
SYNC_TASK = "jobs.analytics.sync_account"


def _now() -> datetime:
    return datetime.now(UTC)


def cadence_points(platform: str) -> tuple[int, ...]:
    last = PLATFORM_LAST_PULL_HOURS.get(platform)
    return tuple(h for h in CADENCE_HOURS if last is None or h <= last)


def next_due(published_at: datetime, last_captured_at: datetime | None, platform: str) -> datetime | None:
    """First cadence point strictly after the last capture (or the first point when never captured)."""
    for h in cadence_points(platform):
        at = published_at + timedelta(hours=h)
        if last_captured_at is None or at > last_captured_at:
            return at
    return None


def is_due(published_at: datetime, last_captured_at: datetime | None, platform: str, now: datetime | None = None) -> bool:
    due = next_due(published_at, last_captured_at, platform)
    return due is not None and due <= (now or _now())


class AnalyticsSyncService:
    vault = TokenVault()

    @classmethod
    async def _budget_ok(cls, db: AsyncSession, workspace_id: UUID, platform: str) -> tuple[bool, str | None]:
        """BudgetGuard-lite: ``usage_budgets(kind=platform_reads)`` vs the ledger for the period."""
        budgets = (await db.execute(select(UsageBudget).where(UsageBudget.workspace_id == workspace_id, UsageBudget.kind.in_(("platform_reads", f"platform_reads:{platform}"))))).scalars().all()
        for b in budgets:
            start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
            if b.period == "month":
                start = start.replace(day=1)
            q = select(func.coalesce(func.sum(UsageLedger.cost_usd if platform == "x" else UsageLedger.quantity), 0)).where(
                UsageLedger.workspace_id == workspace_id, UsageLedger.kind == "platform_reads", UsageLedger.occurred_at >= start)
            if b.kind.endswith(f":{platform}"):
                q = q.where(UsageLedger.provider == platform)
            used = float((await db.execute(q)).scalar() or 0)
            if used >= float(b.limit_value) and b.hard:
                return False, f"platform_reads budget exhausted ({used}/{b.limit_value} per {b.period})"
        return True, None

    @classmethod
    async def _book(cls, db: AsyncSession, workspace_id: UUID, account: SocialAccount, normalized: dict[str, Any], ref_type: str, ref_id: UUID) -> None:
        raw = normalized.get("raw") or {}
        platform = account.platform.value
        units = float(raw.get("quota_units") or 1)
        cost = float(raw.get("cost_usd") or READ_COST_USD.get(platform, 0.0))
        db.add(UsageLedger(workspace_id=workspace_id, kind="platform_reads", provider=platform, platform=account.platform, quantity=units, cost_usd=cost,
                           ref_type=ref_type, ref_id=ref_id))

    @classmethod
    async def sync_account(cls, db: AsyncSession, account_id: UUID, *, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
        now = now or _now()
        account = await db.get(SocialAccount, account_id)
        if account is None:
            return {"status": "missing"}
        if account.status != AccountStatus.active:
            return {"status": "skipped", "reason": f"account {account.status.value}"}
        ok, why = await cls._budget_ok(db, account.workspace_id, account.platform.value)
        if not ok:
            return {"status": "skipped", "reason": why}
        adapter = get_adapter(account.platform.value)
        try:
            tokens = await cls.vault.get_tokens(db, account)
        except LookupError:
            return {"status": "skipped", "reason": "no token"}
        brand = await db.get(Brand, account.brand_id)
        tz = ZoneInfo(brand.timezone if brand and brand.timezone else "UTC")
        today = now.astimezone(tz).date()
        await emit(db, "ANALYTICS_SYNC_STARTED", {"account_id": str(account.id), "platform": account.platform.value}, workspace_id=account.workspace_id)
        result: dict[str, Any] = {"status": "ok", "account_id": str(account.id), "account_metrics": None, "posts_pulled": 0, "posts_due": 0, "errors": []}
        try:
            # ---- account metrics (daily) ----
            existing = (await db.execute(select(AccountMetric).where(AccountMetric.social_account_id == account.id, AccountMetric.date == today))).scalars().first()
            if force or existing is None or now.astimezone(tz).hour >= ACCOUNT_SYNC_HOUR and (existing.raw or {}).get("partial"):
                try:
                    normalized = await adapter.get_account_metrics(account, tokens)
                    await cls._upsert_account_metrics(db, account, today, normalized)
                    await cls._book(db, account.workspace_id, account, normalized, "account_metrics", account.id)
                    result["account_metrics"] = "updated"
                except PublishError as e:
                    if e.category == "auth":
                        raise
                    result["errors"].append({"scope": "account", "category": e.category, "code": e.code, "message": e.message[:200]})
                    if e.category == "rate_limited":
                        result["retry_after_s"] = e.retry_after_s
            # ---- post metrics (cadence) ----
            posts = (await db.execute(select(PublishedPost).where(PublishedPost.social_account_id == account.id, PublishedPost.deleted_at.is_(None),
                                                                  PublishedPost.published_at >= now - timedelta(days=220)))).scalars().all()
            for pp in posts:
                if result.get("retry_after_s"):
                    break
                last = (await db.execute(select(func.max(PostMetric.captured_at)).where(PostMetric.published_post_id == pp.id))).scalar()
                if not force and not is_due(pp.published_at, last, account.platform.value, now):
                    continue
                result["posts_due"] += 1
                try:
                    normalized = await adapter.get_post_metrics(account, tokens, pp.external_id)
                    await cls._upsert_post_metrics(db, account, pp, normalized, now)
                    await cls._book(db, account.workspace_id, account, normalized, "post_metrics", pp.id)
                    result["posts_pulled"] += 1
                except PublishError as e:
                    if e.category == "auth":
                        raise
                    result["errors"].append({"scope": "post", "published_post_id": str(pp.id), "category": e.category, "code": e.code, "message": e.message[:200]})
                    if e.category == "rate_limited":
                        result["retry_after_s"] = e.retry_after_s
        except PublishError as e:
            account.status = AccountStatus.expired if e.code != "revoked" else AccountStatus.revoked
            account.health = {**(account.health or {}), "token_valid": False, "last_error": e.message[:300]}
            await emit(db, "SOCIAL_ACCOUNT_EXPIRED", {"account_id": str(account.id), "platform": account.platform.value, "reason": e.message[:300]},
                       workspace_id=account.workspace_id)
            await emit(db, "ANALYTICS_SYNC_FAILED", {"account_id": str(account.id), "category": "auth", "message": e.message[:300]}, workspace_id=account.workspace_id)
            await _notify(db, account.workspace_id, "social.reconnect", f"Reconnect {account.display_name}", "Analytics sync failed: the token is no longer valid.",
                          "/settings/social", severity="warning")
            return {"status": "auth_failed", "account_id": str(account.id)}
        if result.get("retry_after_s"):
            try:
                await defer_in_txn(db, SYNC_TASK, queue="analytics", queueing_lock=f"analytics:{account.id}",
                                   args={"account_id": str(account.id), "workspace_id": str(account.workspace_id)},
                                   schedule_at=now + timedelta(seconds=int(result["retry_after_s"])))
            except AlreadyEnqueued:
                pass
        await emit(db, "ANALYTICS_UPDATED", {"account_id": str(account.id), "platform": account.platform.value, "posts_pulled": result["posts_pulled"],
                                             "account_metrics": result["account_metrics"], "errors": len(result["errors"])}, workspace_id=account.workspace_id)
        if result["posts_pulled"] or result["account_metrics"]:
            try:
                await recompute_snapshots(db, account.workspace_id, account.brand_id)
            except Exception as e:  # noqa: BLE001
                log.warning("snapshots.failed", error=str(e)[:200])
        if result["errors"]:
            await emit(db, "ANALYTICS_SYNC_FAILED", {"account_id": str(account.id), "partial": True, "errors": result["errors"][:10]}, workspace_id=account.workspace_id)
        return result

    @classmethod
    async def sync_post(cls, db: AsyncSession, published_post_id: UUID) -> dict[str, Any]:
        pp = await db.get(PublishedPost, published_post_id)
        if pp is None or pp.deleted_at:
            return {"status": "missing"}
        account = await db.get(SocialAccount, pp.social_account_id)
        if account is None or account.status != AccountStatus.active:
            return {"status": "skipped"}
        ok, why = await cls._budget_ok(db, account.workspace_id, account.platform.value)
        if not ok:
            return {"status": "skipped", "reason": why}
        adapter = get_adapter(account.platform.value)
        tokens = await cls.vault.get_tokens(db, account)
        try:
            normalized = await adapter.get_post_metrics(account, tokens, pp.external_id)
        except PublishError as e:
            await emit(db, "ANALYTICS_SYNC_FAILED", {"account_id": str(account.id), "published_post_id": str(pp.id), "category": e.category, "message": e.message[:300]},
                       workspace_id=account.workspace_id)
            if e.category == "auth":
                account.status = AccountStatus.expired
            return {"status": "failed", "category": e.category, "retry_after_s": e.retry_after_s}
        await cls._upsert_post_metrics(db, account, pp, normalized, _now())
        await cls._book(db, account.workspace_id, account, normalized, "post_metrics", pp.id)
        await emit(db, "ANALYTICS_UPDATED", {"account_id": str(account.id), "published_post_id": str(pp.id), "posts_pulled": 1}, workspace_id=account.workspace_id)
        return {"status": "ok", "published_post_id": str(pp.id)}

    # ---- upserts ----
    @classmethod
    async def _upsert_post_metrics(cls, db: AsyncSession, account: SocialAccount, pp: PublishedPost, normalized: dict[str, Any], now: datetime) -> None:
        m = normalized.get("metrics") or {}
        window = normalized.get("window") or "lifetime"
        existing = (await db.execute(select(PostMetric).where(PostMetric.published_post_id == pp.id, PostMetric.window == window,
                                                              func.date(PostMetric.captured_at) == now.date()))).scalars().first()
        row = existing or PostMetric(workspace_id=pp.workspace_id, published_post_id=pp.id, platform=account.platform, window=window)
        row.captured_at = now
        for k in POST_METRIC_KEYS:
            setattr(row, k, m.get(k))
        row.engagement_rate = normalized.get("engagement_rate")
        row.engagement_rate_basis = normalized.get("engagement_rate_basis")
        row.availability = normalized.get("availability") or {}
        row.raw = _trim(normalized.get("raw"))
        db.add(row)
        await db.flush()

    @classmethod
    async def _upsert_account_metrics(cls, db: AsyncSession, account: SocialAccount, day: date, normalized: dict[str, Any]) -> None:
        m = normalized.get("metrics") or {}
        prev = (await db.execute(select(AccountMetric).where(AccountMetric.social_account_id == account.id, AccountMetric.date < day)
                                 .order_by(AccountMetric.date.desc()).limit(1))).scalars().first()
        values: dict[str, Any] = {k: m.get(k) for k in ACCOUNT_METRIC_KEYS}
        if values.get("followers_delta") is None and values.get("followers") is not None and prev is not None and prev.followers is not None:
            values["followers_delta"] = int(values["followers"]) - int(prev.followers)
            avail = dict(normalized.get("availability") or {})
            avail["followers_delta"] = "derived"
            normalized["availability"] = avail
        stmt = pg_insert(AccountMetric).values(workspace_id=account.workspace_id, social_account_id=account.id, date=day, raw=_trim(normalized.get("raw")),
                                               availability=normalized.get("availability") or {}, **values)
        stmt = stmt.on_conflict_do_update(index_elements=["social_account_id", "date"], set_={**values, "raw": stmt.excluded.raw, "availability": stmt.excluded.availability})
        await db.execute(stmt)


def _trim(raw: Any) -> Any:
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if k not in ("access_token",)}
    return raw


async def dispatch_analytics_cadence(db: AsyncSession, *, now: datetime | None = None, limit: int = 100) -> int:
    """Scheduler hook (every 5 min): enqueue ``jobs.analytics.sync_account`` for accounts with a daily sync due (brand tz
    03:00) or post pulls due by cadence. Queueing locks make this safe to call repeatedly."""
    now = now or _now()
    accounts = (await db.execute(select(SocialAccount, Brand.timezone).join(Brand, Brand.id == SocialAccount.brand_id)
                                 .where(SocialAccount.status == AccountStatus.active).limit(500))).all()
    n = 0
    for account, tzname in accounts:
        tz = ZoneInfo(tzname or "UTC")
        local = now.astimezone(tz)
        due = False
        if local.hour >= ACCOUNT_SYNC_HOUR:
            has_today = (await db.execute(select(AccountMetric.id).where(AccountMetric.social_account_id == account.id, AccountMetric.date == local.date()))).first()
            due = has_today is None
        if not due:
            latest = (select(PostMetric.published_post_id, func.max(PostMetric.captured_at).label("captured_at")).group_by(PostMetric.published_post_id).subquery())
            rows = (await db.execute(select(PublishedPost.published_at, latest.c.captured_at)
                                     .join(latest, latest.c.published_post_id == PublishedPost.id, isouter=True)
                                     .where(PublishedPost.social_account_id == account.id, PublishedPost.deleted_at.is_(None),
                                            PublishedPost.published_at >= now - timedelta(days=220)))).all()
            due = any(is_due(p_at, c_at, account.platform.value, now) for p_at, c_at in rows)
        if not due:
            continue
        try:
            await defer_in_txn(db, SYNC_TASK, queue="analytics", queueing_lock=f"analytics:{account.id}",
                               args={"account_id": str(account.id), "workspace_id": str(account.workspace_id)})
            n += 1
        except AlreadyEnqueued:
            continue
        if n >= limit:
            break
    return n
