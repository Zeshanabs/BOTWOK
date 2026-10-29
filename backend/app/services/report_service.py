"""ReportService (doc 13 §13.6, doc 06 ``report``): report generation and rendering.

``create`` stores a ``reports`` row with ``content.status = "generating"`` and defers ``jobs.reports.generate`` in the same
transaction (falls back to generating inline when the queue is unavailable). ``generate`` builds the deterministic **data
pack** for the kind (KPIs with basis/coverage, accounts, analytics snapshots, top posts, insights, recommendations,
competitor deltas, upcoming schedule, research runs/sources, campaigns), renders Markdown sections + HTML
(``app.services.report_render``), uploads the HTML to the ``reports`` bucket, emits ``REPORT_GENERATED`` and delivers it
to the recipients. When an AI provider is configured, ``create`` also starts the ``report`` agent (tool mode) whose
narrative is merged by ``apply_agent_output`` (tool ``reports.save`` or the ``AI_RUN_COMPLETED`` consumer).
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import stats as S
from app.analytics.queries import brand_tz, compare, kpis, post_rows
from app.config import settings
from app.core.errors import ProblemError, conflict, not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.brand import Brand
from app.models.competitor import Competitor, CompetitorReport
from app.models.content import Campaign, ContentItem, ContentVariant
from app.models.enums import ScheduleStatus
from app.models.identity import User, WorkspaceMember
from app.models.platform import Report
from app.models.research import ResearchRun
from app.models.scheduling import AccountMetric, AnalyticsSnapshot, Recommendation, ScheduledPost
from app.models.social import SocialAccount
from app.services import report_render as R
from app.services.insight_service import (
    InsightService,
    ai_configured,
    audit_safe,
    competitor_deltas,
    paginate,
    start_tool_run,
)

log = get_logger("reports.service")

REPORT_KINDS = ("weekly_performance", "competitor", "competitor_opportunities", "campaign", "research_brief", "custom")
REPORT_STATUSES = ("generating", "ready", "failed")
DATA_PACK_VERSION = 1
MAX_PERIOD_DAYS = 366
CHANNEL_KEYWORDS = ("in_app", "email", "slack", "webhook")
BLOCKS: dict[str, set[str]] = {
    "weekly_performance": {"kpis", "accounts", "snapshots", "top_posts", "trend", "insights", "recommendations",
                           "competitors", "upcoming"},
    "competitor": {"kpis", "competitors", "competitor_analyses", "insights"},
    "competitor_opportunities": {"competitors", "competitor_analyses", "insights", "recommendations"},
    "campaign": {"kpis", "top_posts", "trend", "campaigns", "upcoming"},
    "research_brief": {"research", "insights"},
    "custom": {"kpis", "top_posts", "trend", "insights", "recommendations", "competitors", "research", "upcoming"},
}


def _uuid(v: Any, field: str = "id") -> UUID:
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except (TypeError, ValueError) as e:
        raise validation(f"Invalid {field}", [{"code": "invalid_uuid", "field": field, "message": str(v)}]) from e


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date | datetime) else v


def default_title(kind: str, brand_name: str | None, start: date, end: date) -> str:
    label = R.KIND_LABELS.get(kind, "Report")
    who = f" — {brand_name}" if brand_name else ""
    return f"{label}{who} ({start.isoformat()} → {end.isoformat()})"


def report_status(report: Report) -> str:
    return str((report.content or {}).get("status") or "ready")


def normalize_recipient(r: Any) -> dict[str, Any] | None:
    """'a@b.co' → email; 'slack'|'in_app'|'email'|'webhook' → workspace channel; {'user_id'}|{'email'}|{'channel'}."""
    if isinstance(r, str):
        s = r.strip()
        if not s:
            return None
        if s.lower() in CHANNEL_KEYWORDS:
            return {"type": "channel", "channel": s.lower()}
        if "@" in s and " " not in s:
            return {"type": "email", "email": s}
        try:
            return {"type": "user", "user_id": str(UUID(s))}
        except ValueError:
            return None
    if isinstance(r, dict):
        if r.get("user_id"):
            try:
                return {"type": "user", "user_id": str(UUID(str(r["user_id"])))}
            except ValueError:
                return None
        email = r.get("email") or (r.get("to") if r.get("type") == "email" else None) or r.get("address")
        if email and "@" in str(email):
            return {"type": "email", "email": str(email).strip()}
        ch = str(r.get("channel") or "").lower()
        if ch in CHANNEL_KEYWORDS:
            return {"type": "channel", "channel": ch}
    return None


class ReportService:
    # ------------------------------------------------------------------------------------------ create / enqueue
    @classmethod
    async def create(cls, db: AsyncSession, member: Any, kind: str, brand_id: Any, period_start: date | None = None,
                     period_end: date | None = None, recipients: list[Any] | None = None, title: str | None = None, *,
                     options: dict[str, Any] | None = None, enqueue: bool = True, use_ai: bool | None = None,
                     automation_run_id: UUID | None = None) -> Report:
        if kind not in REPORT_KINDS:
            raise validation(f"kind must be one of {', '.join(REPORT_KINDS)}")
        ws = member.workspace_id
        brand = await InsightService._brand(db, ws, brand_id)
        ps, pe = await cls._period(db, brand, kind, period_start, period_end)
        recips = []
        for r in recipients or []:
            n = normalize_recipient(r)
            if n is None:
                raise validation("Invalid recipient", [{"code": "invalid_recipient", "field": "recipients", "message": str(r)[:200]}])
            recips.append(n)
        now = datetime.now(UTC)
        title = (title or "").strip() or default_title(kind, brand.name, ps, pe)
        content: dict[str, Any] = {"status": "generating", "kind": kind, "period": {"start": ps.isoformat(), "end": pe.isoformat()},
                                   "summary": None, "sections": [], "data_pack_version": DATA_PACK_VERSION,
                                   "options": options or {}, "narrative_status": None, "requested_at": now.isoformat()}
        uid = getattr(getattr(member, "user", None), "id", None)
        report = Report(id=new_id(), workspace_id=ws, brand_id=brand.id, kind=kind, title=title[:300], period_start=ps,
                        period_end=pe, content=content, recipients=recips, created_by=uid, created_at=now,
                        automation_run_id=automation_run_id)
        db.add(report)
        await db.flush()
        want_ai = use_ai if use_ai is not None else True
        if want_ai and await ai_configured(db, ws, "balanced", "report"):
            try:
                opts = options or {}
                async with db.begin_nested():
                    run = await start_tool_run(db, member, agent="report", action="compose", brand_id=brand.id,
                                               message=f"Compose the {kind.replace('_', ' ')} report '{title}'",
                                               inputs={"report_id": str(report.id), "kind": kind, "brand_id": str(brand.id),
                                                       "period_start": ps.isoformat(), "period_end": pe.isoformat(),
                                                       "audience": opts.get("audience", "team"),
                                                       "length": opts.get("length", "standard"),
                                                       "instructions": opts.get("instructions")})
                report.ai_run_id = run.id
                report.content = {**report.content, "narrative_status": "pending"}
            except Exception as e:  # noqa: BLE001 - the deterministic report never depends on the AI narrative
                log.warning("report.ai_start_failed", report_id=str(report.id), error=str(e)[:200])
                report.content = {**report.content, "narrative_status": "unavailable"}
        await db.flush()
        await audit_safe(db, member, "report.create", "report", report.id,
                         after={"kind": kind, "brand_id": str(brand.id), "period": report.content["period"],
                                "recipients": len(recips), "ai_run_id": str(report.ai_run_id) if report.ai_run_id else None})
        if enqueue and await cls._defer(db, report):
            return report
        await cls.generate(db, report.id, workspace_id=ws)
        return report

    @classmethod
    async def _defer(cls, db: AsyncSession, report: Report) -> bool:
        try:
            from app.workers.queue import AlreadyEnqueued, defer_in_txn
        except ImportError:
            return False
        try:
            await defer_in_txn(db, "jobs.reports.generate", queue="analytics", queueing_lock=f"report:{report.id}",
                               args={"report_id": str(report.id), "workspace_id": str(report.workspace_id)})
            return True
        except AlreadyEnqueued:
            return True
        except Exception as e:  # noqa: BLE001 - no queue → generate inline
            log.warning("report.defer_failed", report_id=str(report.id), error=str(e)[:200])
            return False

    @classmethod
    async def _period(cls, db: AsyncSession, brand: Brand, kind: str, start: date | None, end: date | None) -> tuple[date, date]:
        tz = await brand_tz(db, brand.id)
        today = datetime.now(tz).date()
        if end is None:
            end = (start + timedelta(days=6 if kind == "weekly_performance" else 29)) if start else today
        if start is None:
            start = end - timedelta(days=6 if kind == "weekly_performance" else 29)
        if start > end:
            raise validation("period_start must be on or before period_end")
        if (end - start).days + 1 > MAX_PERIOD_DAYS:
            raise validation(f"The period can span at most {MAX_PERIOD_DAYS} days")
        return start, end

    # ------------------------------------------------------------------------------------------ generation (job)
    @classmethod
    async def generate(cls, db: AsyncSession, report_id: Any, *, workspace_id: UUID | None = None, force: bool = False
                       ) -> dict[str, Any]:
        """Build the data pack, render, store HTML, emit REPORT_GENERATED, deliver. Idempotent unless ``force``."""
        q = select(Report).where(Report.id == _uuid(report_id, "report_id"))
        if workspace_id is not None:
            q = q.where(Report.workspace_id == workspace_id)
        report = (await db.execute(q.with_for_update())).scalar_one_or_none()
        if report is None:
            return {"status": "missing", "report_id": str(report_id)}
        c = dict(report.content or {})
        if c.get("status") == "ready" and not force:
            return {"status": "ready", "report_id": str(report.id), "skipped": True}
        try:
            async with db.begin_nested():
                pack = await cls.build_pack(db, report.workspace_id, report.kind, report.brand_id, report.period_start,
                                            report.period_end, options=c.get("options"))
                rendered = R.compose(report.title, report.kind, pack, narrative=c.get("narrative"))
        except Exception as e:  # noqa: BLE001
            log.exception("report.generate_failed", report_id=str(report.id))
            c.update(status="failed", error=f"{type(e).__name__}: {str(e)[:400]}", failed_at=datetime.now(UTC).isoformat())
            report.content = c
            await db.flush()
            return {"status": "failed", "report_id": str(report.id), "error": c["error"]}
        key = await cls._store_html(report, rendered["html"])
        c.update(status="ready", error=None, summary=rendered["summary"], summary_deterministic=rendered["summary_deterministic"],
                 sections=rendered["sections"], data=pack, generated_at=datetime.now(UTC).isoformat(),
                 data_pack_version=DATA_PACK_VERSION)
        report.content = c
        if key:
            report.rendered_object_key = key
        await db.flush()
        await emit(db, "REPORT_GENERATED", {"report_id": str(report.id), "kind": report.kind, "title": report.title,
                                            "brand_id": str(report.brand_id) if report.brand_id else None,
                                            "narrative_pending": c.get("narrative_status") == "pending",
                                            "rendered_object_key": report.rendered_object_key},
                   workspace_id=report.workspace_id, actor={"type": "system"})
        delivery = await cls._deliver(db, report, rendered)
        report.content = {**c, "delivery": delivery}
        await db.flush()
        return {"status": "ready", "report_id": str(report.id), "delivery": delivery}

    @classmethod
    async def _store_html(cls, report: Report, html: str) -> str | None:
        key = f"{report.workspace_id}/reports/{report.id}.html"
        try:
            from app.integrations.storage.s3 import storage
            await storage.put(settings.s3_bucket_reports, key, html.encode("utf-8"), "text/html; charset=utf-8")
            return key
        except Exception as e:  # noqa: BLE001 - export re-renders when the object is missing
            log.warning("report.store_failed", report_id=str(report.id), error=str(e)[:200])
            return None

    @classmethod
    async def _deliver(cls, db: AsyncSession, report: Report, rendered: dict[str, Any]) -> list[dict[str, Any]]:
        """In-app notice to the creator + every recipient (email body = the rendered HTML)."""
        try:
            from app.services.notification_service import NotificationService
        except ImportError:
            return []
        link = f"/reports/{report.id}"
        title = f"Report ready: {report.title}"[:300]
        body = (rendered.get("summary") or "")[:900] or None
        results: list[dict[str, Any]] = []
        now = datetime.now(UTC).isoformat()

        async def notify(user_id: UUID | None, channels: list[str]) -> bool:
            try:
                async with db.begin_nested():
                    await NotificationService.notify(db, report.workspace_id, "report_generated", title, body, link,
                                                     user_id=user_id, channels=channels, payload={"report_id": str(report.id)})
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("report.notify_failed", report_id=str(report.id), error=str(e)[:200])
                return False

        async def email(to: list[str]) -> bool:
            if not to:
                return False
            return await NotificationService.send_email(to, f"[Botwok] {report.title}", rendered.get("markdown") or body or title,
                                                        html=rendered.get("html"))

        if report.created_by:
            await notify(report.created_by, ["in_app"])
        for r in report.recipients or []:
            n = normalize_recipient(r) or {}
            entry: dict[str, Any] = {"recipient": n or r, "at": now}
            try:
                if n.get("type") == "email":
                    entry.update(channel="email", status="sent" if await email([n["email"]]) else "failed")
                elif n.get("type") == "user":
                    uid = UUID(n["user_id"])
                    member = (await db.execute(select(User).join(WorkspaceMember, WorkspaceMember.user_id == User.id).where(
                        WorkspaceMember.workspace_id == report.workspace_id, User.id == uid))).scalar_one_or_none()
                    if member is None:
                        entry.update(channel="user", status="skipped", reason="not_a_member")
                    else:
                        ok_app = await notify(uid, ["in_app"])
                        ok_mail = await email([member.email]) if member.is_active else False
                        entry.update(channel="in_app+email", status="sent" if (ok_app or ok_mail) else "failed")
                elif n.get("type") == "channel" and n["channel"] == "email":
                    emails = list((await db.execute(select(User.email).join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                                                    .where(WorkspaceMember.workspace_id == report.workspace_id,
                                                           User.is_active.is_(True)))).scalars())
                    entry.update(channel="email", status="sent" if await email(emails) else "failed", count=len(emails))
                elif n.get("type") == "channel":
                    entry.update(channel=n["channel"], status="queued" if await notify(None, [n["channel"]]) else "failed")
                else:
                    entry.update(status="skipped", reason="invalid_recipient")
            except Exception as e:  # noqa: BLE001 - one bad recipient never blocks the others
                entry.update(status="failed", error=str(e)[:200])
            results.append(entry)
        return results

    # ------------------------------------------------------------------------------------------ data pack
    @classmethod
    async def weekly_performance_pack(cls, db: AsyncSession, brand_id: Any, week: date | datetime | str | None = None
                                      ) -> dict[str, Any]:
        """Data pack for the automation template: ``week`` = any date in the week, an ISO week ``'2026-W41'``, or None
        (= the last complete Monday–Sunday week in the brand's timezone)."""
        brand = await db.get(Brand, _uuid(brand_id, "brand_id"))
        if brand is None or brand.deleted_at is not None:
            raise not_found("Brand")
        tz = await brand_tz(db, brand.id)
        if week is None:
            d = datetime.now(tz).date() - timedelta(days=7)
        elif isinstance(week, datetime):
            d = week.astimezone(tz).date() if week.tzinfo else week.date()
        elif isinstance(week, date):
            d = week
        else:
            s = str(week).strip()
            if "W" in s.upper():
                y, w = s.upper().split("-W", 1)
                d = date.fromisocalendar(int(y), int(w[:2]), 1)
            else:
                d = date.fromisoformat(s[:10])
        start = d - timedelta(days=d.weekday())
        return await cls.build_pack(db, brand.workspace_id, "weekly_performance", brand.id, start, start + timedelta(days=6))

    @classmethod
    async def build_pack(cls, db: AsyncSession, workspace_id: UUID, kind: str, brand_id: UUID | None, period_start: date | None,
                         period_end: date | None, *, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        blocks = BLOCKS.get(kind, BLOCKS["custom"])
        brand = (await db.execute(select(Brand).where(Brand.id == brand_id, Brand.workspace_id == workspace_id))
                 ).scalar_one_or_none() if brand_id else None
        tz = await brand_tz(db, brand.id if brand else None)
        today = datetime.now(tz).date()
        pe = period_end or today
        ps = period_start or pe - timedelta(days=6)
        start = datetime.combine(ps, time.min, tz)
        end = datetime.combine(pe + timedelta(days=1), time.min, tz)
        span = end - start
        prev_start, prev_end = start - span, start
        now = datetime.now(UTC)
        pack: dict[str, Any] = {
            "version": DATA_PACK_VERSION, "kind": kind, "generated_at": now.isoformat(),
            "brand": {"id": str(brand.id), "name": brand.name, "timezone": brand.timezone} if brand else None,
            "period": {"start": ps.isoformat(), "end": pe.isoformat(), "days": span.days, "timezone": getattr(tz, "key", "UTC")},
            "previous_period": {"start": prev_start.date().isoformat(), "end": (prev_end - timedelta(days=1)).date().isoformat()},
            "data_notes": [], "options": options,
        }
        notes: list[str] = pack["data_notes"]
        bid = brand.id if brand else None
        until = end - timedelta(microseconds=1)
        rows: list[dict[str, Any]] = []
        if blocks & {"kpis", "top_posts", "trend"}:
            rows = await post_rows(db, workspace_id, brand_id=bid, since=start, until=until)
        if "kpis" in blocks:
            prev_rows = await post_rows(db, workspace_id, brand_id=bid, since=prev_start, until=prev_end - timedelta(microseconds=1))
            pack["kpis"] = compare(kpis(rows), kpis(prev_rows))
            pack["posts"] = {"count": len(rows), "previous_count": len(prev_rows),
                             "by_platform": dict(Counter(r["platform"] for r in rows))}
            for key in ("impressions", "views", "engagement_rate"):
                cov = (pack["kpis"].get(key) or {}).get("coverage", 0)
                if rows and cov < len(rows):
                    notes.append(f"{key.replace('_', ' ')} is available for {cov} of {len(rows)} post(s); the rest are n/a "
                                 "(platform does not report it or metrics are not synced yet), not zero.")
            if not rows:
                notes.append("No published posts in this period.")
        if "top_posts" in blocks:
            tp = S.top_posts(rows, "engagement_rate", k=5)
            if not tp["posts"] and rows:
                tp = S.top_posts(rows, "engagement", k=5)
            pack["top_posts"] = tp
        if "trend" in blocks:
            trend_rows = await post_rows(db, workspace_id, brand_id=bid, since=end - timedelta(days=max(56, span.days)), until=until)
            pack["trend"] = S.trend(trend_rows, "engagement_rate", granularity="week")
        if "accounts" in blocks and bid:
            pack["accounts"] = await cls._accounts(db, workspace_id, bid, ps, pe)
        if "snapshots" in blocks and bid:
            snaps = (await db.execute(select(AnalyticsSnapshot).where(
                AnalyticsSnapshot.workspace_id == workspace_id, AnalyticsSnapshot.brand_id == bid,
                AnalyticsSnapshot.scope == "brand", AnalyticsSnapshot.period == "week",
                AnalyticsSnapshot.period_start >= ps - timedelta(weeks=8), AnalyticsSnapshot.period_start <= pe)
                .order_by(AnalyticsSnapshot.period_start.asc()))).scalars().all()
            pack["snapshots"] = [{"period_start": s.period_start.isoformat(), "metrics": s.metrics,
                                  "computed_at": _iso(s.computed_at)} for s in snaps]
        if "insights" in blocks and bid:
            ins = await InsightService.insights_in_period(db, workspace_id, bid, ps, pe)
            pack["insights"] = [{"id": str(i.id), "statement": i.statement, "kind": i.kind, "confidence": i.confidence,
                                 "n": i.n, "effect_size": float(i.effect_size) if i.effect_size is not None else None,
                                 "status": i.status, "created_at": _iso(i.created_at)} for i in ins]
        if "recommendations" in blocks and bid:
            recs = (await db.execute(select(Recommendation).where(
                Recommendation.workspace_id == workspace_id, Recommendation.brand_id == bid,
                or_(Recommendation.status.in_(["proposed", "accepted"]),
                    and_(Recommendation.created_at >= start, Recommendation.created_at < end)))
                .order_by(Recommendation.created_at.desc()).limit(20))).scalars().all()
            pack["recommendations"] = [{"id": str(r.id), "action": r.action, "priority": r.priority, "status": r.status,
                                        "expected_impact": r.expected_impact, "target": r.target or {},
                                        "insight_id": str(r.insight_id) if r.insight_id else None} for r in recs]
        if "competitors" in blocks and bid:
            pack["competitors"] = await competitor_deltas(db, workspace_id, bid, start, end)
            if not pack["competitors"]:
                notes.append("No competitors are tracked for this brand.")
        if "competitor_analyses" in blocks and bid:
            pack["competitor_analyses"] = await cls._competitor_analyses(db, workspace_id, bid, end)
        if "upcoming" in blocks and bid:
            pack["upcoming"] = await cls._upcoming(db, workspace_id, bid, now)
        if "research" in blocks:
            pack["research"] = await cls._research(db, workspace_id, bid, start, end)
            if not pack["research"]:
                notes.append("No research runs in this period.")
        if "campaigns" in blocks and bid:
            pack["campaigns"] = await cls._campaigns(db, workspace_id, bid, ps, pe, start, until, options)
        return pack

    @classmethod
    async def _accounts(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, ps: date, pe: date) -> list[dict[str, Any]]:
        accounts = (await db.execute(select(SocialAccount).where(SocialAccount.workspace_id == workspace_id,
                                                                 SocialAccount.brand_id == brand_id))).scalars().unique().all()
        out = []
        for a in accounts:
            rows = (await db.execute(select(AccountMetric).where(AccountMetric.social_account_id == a.id,
                                                                 AccountMetric.date >= ps, AccountMetric.date <= pe)
                                     .order_by(AccountMetric.date.asc()))).scalars().all()
            base = (await db.execute(select(AccountMetric).where(AccountMetric.social_account_id == a.id, AccountMetric.date < ps,
                                                                 AccountMetric.followers.is_not(None))
                                     .order_by(AccountMetric.date.desc()).limit(1))).scalar_one_or_none()
            fvals = [r.followers for r in rows if r.followers is not None]
            f_end = fvals[-1] if fvals else None
            f_start = base.followers if base is not None else (fvals[0] if len(fvals) >= 2 else None)
            entry: dict[str, Any] = {"account_id": str(a.id), "platform": a.platform.value, "display_name": a.display_name,
                                     "handle": a.handle, "status": a.status.value, "days_with_data": len(rows),
                                     "followers": {"start": f_start, "end": f_end,
                                                   "delta": (f_end - f_start) if f_end is not None and f_start is not None else None}}
            for m in ("impressions", "reach", "views", "profile_views", "website_clicks", "engagement_total"):
                vals = [getattr(r, m) for r in rows if getattr(r, m) is not None]
                entry[m] = {"value": float(sum(vals)) if vals else None, "coverage_days": len(vals)}
            out.append(entry)
        return out

    @classmethod
    async def _upcoming(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, now: datetime) -> list[dict[str, Any]]:
        q = (select(ScheduledPost, ContentVariant, ContentItem, SocialAccount)
             .join(ContentVariant, ContentVariant.id == ScheduledPost.content_variant_id)
             .join(ContentItem, ContentItem.id == ContentVariant.content_item_id)
             .join(SocialAccount, SocialAccount.id == ScheduledPost.social_account_id)
             .where(ScheduledPost.workspace_id == workspace_id, ScheduledPost.brand_id == brand_id,
                    ScheduledPost.status.in_([ScheduleStatus.scheduled, ScheduleStatus.queued, ScheduleStatus.paused]),
                    ScheduledPost.scheduled_at >= now, ScheduledPost.scheduled_at < now + timedelta(days=7))
             .order_by(ScheduledPost.scheduled_at.asc()).limit(25))
        out = []
        for sp, v, item, acc in (await db.execute(q)).unique().all():
            out.append({"scheduled_post_id": str(sp.id), "scheduled_at": sp.scheduled_at.astimezone(UTC).isoformat(),
                        "timezone": sp.timezone, "status": sp.status.value, "platform": v.platform.value,
                        "format": v.format.value, "title": item.title, "account": acc.display_name})
        return out

    @classmethod
    async def _research(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID | None, start: datetime, end: datetime
                        ) -> list[dict[str, Any]]:
        q = select(ResearchRun).where(ResearchRun.workspace_id == workspace_id, ResearchRun.created_at >= start,
                                      ResearchRun.created_at < end)
        if brand_id:
            q = q.where(ResearchRun.brand_id == brand_id)
        runs = (await db.execute(q.order_by(ResearchRun.created_at.desc()).limit(10))).scalars().unique().all()
        out = []
        for r in runs:
            res = r.result or {}
            findings = [f for f in (res.get("findings") or res.get("key_findings") or []) if isinstance(f, dict)][:5]
            sources = []
            for rs in (r.run_sources or [])[:8]:
                s = rs.source
                sources.append({"source_id": str(s.id), "title": s.title, "domain": s.domain, "url": s.canonical_url,
                                "credibility": float(s.credibility_score) if s.credibility_score is not None else None,
                                "published_at": _iso(s.published_at), "relevance": float(rs.relevance_score)})
            out.append({"run_id": str(r.id), "query": r.query, "status": r.status, "created_at": _iso(r.created_at),
                        "summary": (res.get("summary") or None), "source_count": r.source_count,
                        "findings": [{"text": str(f.get("text") or "")[:600],
                                      "source_ids": [str(x) for x in (f.get("source_ids") or [])][:5]} for f in findings],
                        "sources": sources})
        return out

    @classmethod
    async def _campaigns(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, ps: date, pe: date, start: datetime,
                         until: datetime, options: dict[str, Any]) -> list[dict[str, Any]]:
        q = select(Campaign).where(Campaign.workspace_id == workspace_id, Campaign.brand_id == brand_id,
                                   or_(Campaign.starts_on.is_(None), Campaign.starts_on <= pe),
                                   or_(Campaign.ends_on.is_(None), Campaign.ends_on >= ps))
        ids = [_uuid(x, "campaign_id") for x in options.get("campaign_ids") or []]
        if ids:
            q = q.where(Campaign.id.in_(ids))
        out = []
        for c in (await db.execute(q.order_by(Campaign.created_at.desc()).limit(10))).scalars().all():
            rows = await post_rows(db, workspace_id, brand_id=brand_id, since=start, until=until, campaign_id=c.id)
            out.append({"id": str(c.id), "name": c.name, "goal": c.goal, "status": c.status, "starts_on": _iso(c.starts_on),
                        "ends_on": _iso(c.ends_on), "kpis": kpis(rows), "posts": len(rows)})
        return out

    @classmethod
    async def _competitor_analyses(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, end: datetime) -> list[dict[str, Any]]:
        reports = (await db.execute(select(CompetitorReport).where(
            CompetitorReport.workspace_id == workspace_id, CompetitorReport.brand_id == brand_id,
            CompetitorReport.created_at < end).order_by(CompetitorReport.created_at.desc()).limit(20))).scalars().all()
        names = {c.id: c.name for c in (await db.execute(select(Competitor).where(
            Competitor.workspace_id == workspace_id, Competitor.brand_id == brand_id))).scalars().unique().all()}
        out, seen = [], set()
        for r in reports:
            analysis = (r.content or {}).get("analysis") or ((r.content or {}).get("report") or {})
            if not isinstance(analysis, dict):
                continue
            cid = (r.competitor_ids or [None])[0]
            if cid in seen:
                continue
            seen.add(cid)
            out.append({"competitor_report_id": str(r.id), "competitor_id": str(cid) if cid else None,
                        "competitor_name": names.get(cid), "created_at": _iso(r.created_at),
                        "opportunities": list(analysis.get("opportunities") or [])[:8],
                        "strengths": list(analysis.get("strengths") or [])[:5],
                        "weaknesses": list(analysis.get("weaknesses") or [])[:5]})
        return out

    # ------------------------------------------------------------------------------------------ AI narrative
    @staticmethod
    def output_from_run(run: Any) -> dict[str, Any] | None:
        deliverables = ((run.result or {}).get("deliverables") or {}) if run is not None else {}
        for val in deliverables.values():
            if isinstance(val, dict) and ("sections" in val or "summary" in val) and "insights" not in val:
                return val
        return None

    @classmethod
    async def apply_agent_output(cls, db: AsyncSession, run: Any, output: dict[str, Any] | Any | None = None, *,
                                 report_id: Any = None) -> dict[str, Any]:
        """Merge a ``report`` agent output (title/summary/sections) into its ``reports`` row as the AI narrative (or into
        the ``competitor_reports`` row that requested it). Re-renders and re-uploads when the report is already ready."""
        if output is not None and hasattr(output, "model_dump"):
            output = output.model_dump(mode="json")
        output = output or cls.output_from_run(run)
        if not output:
            return {"applied": False, "reason": "no_output"}
        inputs = ((run.input or {}).get("inputs") or {}) if run is not None else {}
        ws = run.workspace_id if run is not None else None
        rid = report_id or inputs.get("report_id")
        narrative = {"title": output.get("title"), "summary": output.get("summary"),
                     "sections": [s for s in output.get("sections") or [] if isinstance(s, dict)][:12],
                     "confidence": output.get("confidence"), "sources": output.get("sources") or [],
                     "run_id": str(run.id) if run is not None else None, "applied_at": datetime.now(UTC).isoformat()}
        if rid:
            q = select(Report).where(Report.id == _uuid(rid, "report_id"))
            if ws is not None:
                q = q.where(Report.workspace_id == ws)
            report = (await db.execute(q.with_for_update())).scalar_one_or_none()
            if report is None:
                return {"applied": False, "reason": "report_missing"}
            c = dict(report.content or {})
            c.update(narrative=narrative, narrative_status="ready")
            if c.get("status") == "ready" and isinstance(c.get("data"), dict):
                rendered = R.compose(report.title, report.kind, c["data"], narrative=narrative)
                key = await cls._store_html(report, rendered["html"])
                c.update(summary=rendered["summary"], sections=rendered["sections"])
                if key:
                    report.rendered_object_key = key
                report.content = c
                await db.flush()
                await emit(db, "REPORT_GENERATED", {"report_id": str(report.id), "kind": report.kind, "title": report.title,
                                                    "brand_id": str(report.brand_id) if report.brand_id else None,
                                                    "narrative": True, "run_id": narrative["run_id"]},
                           workspace_id=report.workspace_id, actor={"type": "agent", "id": "report"})
            else:
                report.content = c
                await db.flush()
            return {"applied": True, "report_id": str(report.id)}
        crid = inputs.get("competitor_report_id")
        if crid:
            cr = (await db.execute(select(CompetitorReport).where(CompetitorReport.id == _uuid(crid, "competitor_report_id"),
                                                                  CompetitorReport.workspace_id == ws).with_for_update())
                  ).scalar_one_or_none()
            if cr is None:
                return {"applied": False, "reason": "competitor_report_missing"}
            title = str(output.get("title") or "Competitor report")
            sections = [R.section(str(s.get("heading") or "Section"), str(s.get("markdown") or ""),
                                  charts=s.get("charts") or [], sources=[str(x) for x in s.get("sources") or []], origin="ai")
                        for s in narrative["sections"]]
            meta = {"kind": "competitor", "period": {"start": _iso(cr.period_start), "end": _iso(cr.period_end)},
                    "generated_at": datetime.now(UTC).isoformat(), "data_pack_version": DATA_PACK_VERSION}
            md = R.render_markdown(title, narrative["summary"], sections, meta)
            key = None
            try:
                from app.integrations.storage.s3 import storage
                key = f"{cr.workspace_id}/competitor-reports/{cr.id}.html"
                await storage.put(settings.s3_bucket_reports, key,
                                  R.render_html(title, narrative["summary"], sections, meta).encode("utf-8"),
                                  "text/html; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                log.warning("competitor_report.store_failed", error=str(e)[:200])
                key = None
            cr.content = {**(cr.content or {}), "status": "ready", "report": {**narrative, "sections": sections},
                          "markdown": md}
            if key:
                cr.rendered_object_key = key
            await db.flush()
            await emit(db, "REPORT_GENERATED", {"competitor_report_id": str(cr.id), "kind": cr.kind, "title": title,
                                                "brand_id": str(cr.brand_id), "run_id": narrative["run_id"]},
                       workspace_id=cr.workspace_id, actor={"type": "agent", "id": "report"})
            return {"applied": True, "competitor_report_id": str(cr.id)}
        return {"applied": False, "reason": "no_target"}

    @classmethod
    async def narrative_failed(cls, db: AsyncSession, run: Any, error: str | None = None) -> dict[str, Any]:
        inputs = ((run.input or {}).get("inputs") or {}) if run is not None else {}
        if inputs.get("report_id"):
            report = (await db.execute(select(Report).where(Report.id == _uuid(inputs["report_id"], "report_id"),
                                                            Report.workspace_id == run.workspace_id).with_for_update())
                      ).scalar_one_or_none()
            if report is not None and (report.content or {}).get("narrative_status") != "ready":
                report.content = {**(report.content or {}), "narrative_status": "failed", "narrative_error": (error or "")[:300]}
                await db.flush()
                return {"applied": True}
        if inputs.get("competitor_report_id"):
            cr = (await db.execute(select(CompetitorReport).where(
                CompetitorReport.id == _uuid(inputs["competitor_report_id"], "competitor_report_id"),
                CompetitorReport.workspace_id == run.workspace_id).with_for_update())).scalar_one_or_none()
            if cr is not None and (cr.content or {}).get("status") != "ready":
                cr.content = {**(cr.content or {}), "status": "failed", "error": (error or "")[:300]}
                await db.flush()
                return {"applied": True}
        return {"applied": False}

    # ------------------------------------------------------------------------------------------ reads / export / delete
    @classmethod
    async def list(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, kind: str | None = None,
                   status: str | None = None, limit: int = 50, cursor: str | None = None) -> tuple[list[Report], str | None]:
        q = select(Report).where(Report.workspace_id == workspace_id)
        if brand_id:
            q = q.where(Report.brand_id == brand_id)
        if kind:
            q = q.where(Report.kind == kind)
        if status:
            if status not in REPORT_STATUSES:
                raise validation(f"status must be one of {', '.join(REPORT_STATUSES)}")
            q = q.where(Report.content["status"].astext == status)
        return await paginate(db, q, Report, limit, cursor)

    @classmethod
    async def get(cls, db: AsyncSession, workspace_id: UUID, report_id: Any) -> Report:
        report = (await db.execute(select(Report).where(Report.id == _uuid(report_id, "report_id"),
                                                        Report.workspace_id == workspace_id))).scalar_one_or_none()
        if report is None:
            raise not_found("Report")
        return report

    @classmethod
    def render(cls, report: Report) -> dict[str, str]:
        c = report.content or {}
        meta = {"kind": report.kind, "period": c.get("period") or {"start": _iso(report.period_start), "end": _iso(report.period_end)},
                "brand": ((c.get("data") or {}).get("brand") or {}).get("name"), "generated_at": c.get("generated_at"),
                "data_pack_version": c.get("data_pack_version") or DATA_PACK_VERSION}
        sections = c.get("sections") or []
        return {"markdown": R.render_markdown(report.title, c.get("summary"), sections, meta),
                "html": R.render_html(report.title, c.get("summary"), sections, meta)}

    @classmethod
    async def export(cls, db: AsyncSession, member: Any, report_id: Any, format: str = "markdown") -> tuple[bytes, str, str]:
        """→ (body, media_type, filename). PDF needs WeasyPrint (501 ``pdf_not_available`` otherwise)."""
        fmt = (format or "markdown").lower()
        if fmt in ("md",):
            fmt = "markdown"
        if fmt not in ("markdown", "html", "pdf"):
            raise validation("format must be markdown, html or pdf")
        report = await cls.get(db, member.workspace_id, report_id)
        if report_status(report) != "ready":
            raise conflict("report_not_ready", f"Report is {report_status(report)}")
        slug = "".join(ch if ch.isalnum() else "-" for ch in report.title.lower()).strip("-")[:60] or "report"
        slug = "-".join(x for x in slug.split("-") if x)
        if fmt == "markdown":
            return cls.render(report)["markdown"].encode("utf-8"), "text/markdown; charset=utf-8", f"{slug}.md"
        html = await cls._html(report)
        if fmt == "html":
            return html.encode("utf-8"), "text/html; charset=utf-8", f"{slug}.html"
        try:
            import weasyprint  # type: ignore[import-not-found]
        except ImportError as e:
            raise ProblemError(501, "pdf_not_available", "PDF export is not available",
                               "PDF rendering needs WeasyPrint, which is not installed; export as html or markdown.") from e
        pdf = weasyprint.HTML(string=html).write_pdf()  # pragma: no cover - optional dependency
        return pdf, "application/pdf", f"{slug}.pdf"  # pragma: no cover

    @classmethod
    async def _html(cls, report: Report) -> str:
        if report.rendered_object_key:
            try:
                from app.integrations.storage.s3 import storage
                return (await storage.get(settings.s3_bucket_reports, report.rendered_object_key)).decode("utf-8")
            except Exception as e:  # noqa: BLE001
                log.info("report.html_fetch_failed", report_id=str(report.id), error=str(e)[:200])
        return cls.render(report)["html"]

    @classmethod
    async def delete(cls, db: AsyncSession, member: Any, report_id: Any) -> None:
        report = await cls.get(db, member.workspace_id, report_id)
        key = report.rendered_object_key
        before = {"kind": report.kind, "title": report.title, "status": report_status(report)}
        await db.delete(report)
        await db.flush()
        await audit_safe(db, member, "report.delete", "report", report.id, before=before)
        if key:
            try:
                from app.integrations.storage.s3 import storage
                await storage.delete(settings.s3_bucket_reports, key)
            except Exception as e:  # noqa: BLE001
                log.info("report.object_delete_failed", report_id=str(report.id), error=str(e)[:200])


__all__ = ["ReportService", "REPORT_KINDS", "REPORT_STATUSES", "normalize_recipient", "default_title", "report_status"]
