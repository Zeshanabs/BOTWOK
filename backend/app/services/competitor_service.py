"""CompetitorService — competitor CRUD, availability classification, profile sync, snapshots, comparison, topic gaps,
reports, retention (doc 08)."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import any_, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, conflict, not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.safe_fetch import SafeFetcher
from app.models.brand import Brand
from app.models.competitor import (
    Competitor,
    CompetitorPost,
    CompetitorProfile,
    CompetitorReport,
    CompetitorSnapshot,
)
from app.models.enums import AccountStatus, Availability, Platform
from app.models.platform import UsageLedger
from app.models.research import ResearchSource, RssFeed
from app.models.social import SocialAccount
from app.research.competitor_stats import cluster_by_jaccard, describe_posts, snapshot_fields
from app.research.text import top_terms
from app.research.urls import safe_canonicalize
from app.schemas.competitors import CompetitorCreate, CompetitorUpdate, ProfileIn, ReportCreate

log = get_logger("competitors.service")
WEB_KINDS = ("website", "blog", "rss", "other")
YOUTUBE_RETENTION = timedelta(days=30)
RAW_RETENTION = timedelta(days=30)
POST_RETENTION = timedelta(days=365)


def _actor(member: Any) -> dict[str, Any]:
    user = getattr(member, "user", None)
    return {"type": "user", "id": str(user.id)} if user is not None else {"type": "system"}


async def _audit(db: AsyncSession, member: Any, action: str, target_type: str, target_id: Any,
                 before: Any = None, after: Any = None) -> None:
    if member is None:
        return
    try:
        from app.services.audit_service import audit
    except ImportError:
        return
    try:
        await audit(db, member, action, target_type, target_id, before=before, after=after)
    except Exception as e:
        log.warning("audit.failed", action=action, error=str(e)[:200])


def _platform_value(p: Any) -> str | None:
    return getattr(p, "value", p) if p is not None else None


class CompetitorService:
    """Classmethods throughout: ``CompetitorService.x(db, …)`` and ``CompetitorService().x(db, …)`` both work."""

    # ------------------------------------------------------------------------------------------ availability (doc 08 §8.1/8.3)
    @classmethod
    async def classify_profile(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, platform: str
                               ) -> tuple[Availability, str, dict[str, Any]]:
        """→ (availability class, initial sync_status, profile_meta notes)."""
        if platform in WEB_KINDS:
            return Availability.public_web, "pending", {"class": "B", "method": "public web crawl (robots.txt honored)"}
        if platform == "instagram":
            acct = (await db.execute(select(SocialAccount.id).where(
                SocialAccount.workspace_id == workspace_id, SocialAccount.brand_id == brand_id,
                SocialAccount.platform == Platform.instagram, SocialAccount.auth_flavor == "facebook_login",
                SocialAccount.status == AccountStatus.active, SocialAccount.disconnected_at.is_(None)).limit(1))
            ).scalar_one_or_none()
            if acct is None:
                return Availability.not_collected, "not_collected", {
                    "class": "E", "reason": "Instagram competitor data needs Business Discovery through a connected Instagram "
                                            "account using Facebook Login; connect one to enable it"}
            return Availability.official_api, "pending", {"class": "A", "method": "Business Discovery", "via_account": str(acct)}
        if platform == "youtube":
            return Availability.official_api, "pending", {
                "class": "A", "method": "YouTube Data API", "policy": "other channels' statistics kept 30 days; raw counts only"}
        if platform == "x":
            return Availability.official_api, "pending", {"class": "A", "method": "X API v2", "metered": True,
                                                          "note": "reads are pay-per-use and counted against the budget"}
        if platform == "threads":
            return Availability.official_api, "needs_approval", {
                "class": "A", "method": "Threads profile lookup / keyword search",
                "note": "needs Meta approval (threads_profile_discovery) for non-own data"}
        if platform == "linkedin":
            return Availability.official_api, "pending", {"class": "A (minimal) + E", "method": "organization networkSizes",
                                                          "posts": "not_collected",
                                                          "note": "followers only; other organizations' posts are not readable"}
        reasons = {"tiktok": "no commercial API for other accounts", "pinterest": "other accounts are not exposed",
                   "gbp": "other businesses' profiles are not exposed", "facebook": "requires Page Public Content Access approval"}
        return Availability.not_collected, "not_collected", {"class": "E", "reason": reasons.get(platform, "not available")}

    @classmethod
    async def _make_profile(cls, db: AsyncSession, comp: Competitor, p: ProfileIn) -> CompetitorProfile:
        avail, status, meta = await cls.classify_profile(db, comp.workspace_id, comp.brand_id, p.platform)
        url = safe_canonicalize(p.url) if p.url else None
        if p.url and not url:
            raise validation(f"invalid url for {p.platform} profile")
        is_web = p.platform in WEB_KINDS
        prof = CompetitorProfile(id=new_id(), workspace_id=comp.workspace_id, competitor_id=comp.id,
                                 platform=None if is_web else Platform(p.platform), kind=p.platform if is_web else "social",
                                 handle=p.handle, url=url, availability=avail, sync_status=status, profile_meta=meta)
        db.add(prof)
        return prof

    # ------------------------------------------------------------------------------------------ CRUD
    @classmethod
    async def create(cls, db: AsyncSession, member: Any, data: CompetitorCreate) -> Competitor:
        ws = member.workspace_id
        brand = (await db.execute(select(Brand.id).where(Brand.id == data.brand_id, Brand.workspace_id == ws,
                                                         Brand.deleted_at.is_(None)))).scalar_one_or_none()
        if brand is None:
            raise validation("brand_id does not belong to this workspace")
        dup = (await db.execute(select(Competitor.id).where(Competitor.brand_id == data.brand_id,
                                                            Competitor.name == data.name))).scalar_one_or_none()
        if dup is not None:
            raise conflict("conflict", f"competitor '{data.name}' already exists for this brand")
        website = safe_canonicalize(data.website) if data.website else None
        if data.website and not website:
            raise validation("invalid website url")
        user = getattr(member, "user", None)
        comp = Competitor(id=new_id(), workspace_id=ws, brand_id=data.brand_id, name=data.name.strip(), website=website,
                          description=data.description, industry=data.industry, tags=[t.strip() for t in data.tags if t.strip()],
                          monitoring_frequency=data.monitoring_frequency, status="active",
                          created_by=getattr(user, "id", None) or getattr(member, "user_id", None))
        db.add(comp)
        await db.flush()
        profiles_in = list(data.profiles)
        if website and not any(p.platform == "website" for p in profiles_in):
            profiles_in.insert(0, ProfileIn(platform="website", url=website))
        for p in profiles_in:
            await cls._make_profile(db, comp, p)
        await db.flush()
        await db.refresh(comp, attribute_names=["profiles"])
        await emit(db, "COMPETITOR_ADDED", {"competitor_id": str(comp.id), "brand_id": str(comp.brand_id), "name": comp.name,
                                            "profiles": [{"profile_id": str(p.id), "platform": _platform_value(p.platform) or p.kind,
                                                          "availability": p.availability.value} for p in comp.profiles]},
                   workspace_id=ws, actor=_actor(member))
        await _audit(db, member, "competitor.create", "competitor", comp.id, after={"name": comp.name, "website": website})
        return comp

    @classmethod
    async def list(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None,
                   status: str | None = None) -> list[Competitor]:
        stmt = select(Competitor).where(Competitor.workspace_id == workspace_id)
        if brand_id:
            stmt = stmt.where(Competitor.brand_id == brand_id)
        if status:
            stmt = stmt.where(Competitor.status == status)
        return list((await db.execute(stmt.order_by(Competitor.name))).scalars())

    @classmethod
    async def get(cls, db: AsyncSession, workspace_id: UUID, competitor_id: UUID) -> Competitor:
        comp = (await db.execute(select(Competitor).where(Competitor.id == competitor_id,
                                                          Competitor.workspace_id == workspace_id))).scalar_one_or_none()
        if comp is None:
            raise not_found("Competitor")
        return comp

    @classmethod
    async def update(cls, db: AsyncSession, member: Any, competitor_id: UUID, data: CompetitorUpdate) -> Competitor:
        comp = await cls.get(db, member.workspace_id, competitor_id)
        before = {"name": comp.name, "website": comp.website, "status": comp.status,
                  "monitoring_frequency": comp.monitoring_frequency, "tags": list(comp.tags or [])}
        changes = data.model_dump(exclude_unset=True, exclude={"add_profiles", "remove_profile_ids"})
        if "website" in changes and changes["website"]:
            w = safe_canonicalize(changes["website"])
            if not w:
                raise validation("invalid website url")
            changes["website"] = w
        if "name" in changes and changes["name"] != comp.name:
            dup = (await db.execute(select(Competitor.id).where(Competitor.brand_id == comp.brand_id,
                                                                Competitor.name == changes["name"],
                                                                Competitor.id != comp.id))).scalar_one_or_none()
            if dup is not None:
                raise conflict("conflict", "another competitor of this brand has that name")
        for k, v in changes.items():
            setattr(comp, k, v)
        for pid in data.remove_profile_ids:
            prof = next((p for p in comp.profiles if p.id == pid), None)
            if prof is not None:
                comp.profiles.remove(prof)
                await db.delete(prof)
        for p in data.add_profiles:
            await cls._make_profile(db, comp, p)
        await db.flush()
        await db.refresh(comp)
        await db.refresh(comp, attribute_names=["profiles"])
        after = {"name": comp.name, "website": comp.website, "status": comp.status,
                 "monitoring_frequency": comp.monitoring_frequency, "tags": list(comp.tags or [])}
        await emit(db, "COMPETITOR_UPDATED", {"competitor_id": str(comp.id), "changes": sorted(changes) +
                                              (["profiles"] if data.add_profiles or data.remove_profile_ids else [])},
                   workspace_id=member.workspace_id, actor=_actor(member))
        await _audit(db, member, "competitor.update", "competitor", comp.id, before=before, after=after)
        return comp

    @classmethod
    async def delete(cls, db: AsyncSession, member: Any, competitor_id: UUID) -> None:
        comp = await cls.get(db, member.workspace_id, competitor_id)
        await _audit(db, member, "competitor.delete", "competitor", comp.id, before={"name": comp.name})
        await db.delete(comp)
        await db.flush()

    # ------------------------------------------------------------------------------------------ sync
    @classmethod
    def collectible(cls, profile: CompetitorProfile) -> bool:
        return profile.availability != Availability.not_collected

    @classmethod
    async def request_sync(cls, db: AsyncSession, workspace_id: UUID, competitor_id: UUID, *,
                           profile_ids: list[UUID] | None = None) -> tuple[list[int | None], list[UUID]]:
        comp = await cls.get(db, workspace_id, competitor_id)
        targets = [p for p in comp.profiles if cls.collectible(p) and (not profile_ids or p.id in profile_ids)]
        if not targets:
            return [], []
        from app.research.queue import defer
        job_ids: list[int | None] = []
        await db.commit()
        from app.core.db import set_workspace
        await set_workspace(db, workspace_id)
        for p in targets:
            try:
                job_ids.append(await defer("jobs.competitors.sync_profile", queue="research",
                                           lock=f"competitor_sync:{p.id}", profile_id=str(p.id),
                                           workspace_id=str(workspace_id)))
            except Exception as e:
                log.warning("competitors.enqueue_failed", profile_id=str(p.id), error=str(e)[:200])
                job_ids.append(None)
            p.sync_status = "queued"
        await db.flush()
        return job_ids, [p.id for p in targets]

    @classmethod
    async def sync_profile(cls, db: AsyncSession, profile_id: UUID, *, fetcher: SafeFetcher | None = None,
                           news: bool = True, news_providers: list[Any] | None = None) -> dict[str, Any]:
        from app.research.collectors import collect
        prof = await db.get(CompetitorProfile, profile_id)
        if prof is None:
            raise not_found("Competitor profile")
        comp = await db.get(Competitor, prof.competitor_id)
        if comp is None:
            raise not_found("Competitor")
        now = datetime.now(UTC)
        platform = _platform_value(prof.platform)
        if not cls.collectible(prof):
            prof.sync_status = "not_collected"
            prof.last_synced_at = now
            await db.flush()
            return {"profile_id": str(prof.id), "status": "not_collected", "reason": (prof.profile_meta or {}).get("reason")}
        prof.sync_status = "running"
        await db.flush()
        try:
            result = await collect(db, comp, prof, fetcher=fetcher)
        except Exception as e:  # collectors map known failures themselves; anything else is recorded, not raised
            log.warning("competitors.collect_crashed", profile_id=str(prof.id), error=str(e)[:300])
            from app.research.collectors import CollectorResult
            result = CollectorResult(status="error", availability=prof.availability, reason=f"{type(e).__name__}: {e}"[:300])
        stored = await cls._store_items(db, comp, prof, result.items, now=now)
        if result.feeds:
            await cls._register_feeds(db, comp, result.feeds)
        for k, v in result.profile_updates.items():
            if v is not None and hasattr(prof, k) and k != "display_name":
                setattr(prof, k, v)
        if result.snapshot.get("bio"):
            prof.bio = str(result.snapshot["bio"])[:2000]
        meta = dict(prof.profile_meta or {})
        meta["last_result"] = {"status": result.status, "reason": result.reason, "items": len(result.items),
                               "new": stored["new"], "changed": stored["changed"], "at": now.isoformat(), **result.meta}
        if result.profile_updates.get("display_name"):
            meta["display_name"] = result.profile_updates["display_name"]
        prof.profile_meta = meta
        prof.sync_status = result.status
        prof.last_synced_at = now
        prof.last_error = result.reason if result.status not in ("ok",) else None
        snapshot_id = None
        stats = None
        if result.status in ("ok", "partial"):
            stats = await cls.describe(db, prof.id, followers=result.snapshot.get("followers_count") or prof.followers_count)
            snap = CompetitorSnapshot(id=new_id(), workspace_id=prof.workspace_id, profile_id=prof.id, captured_at=now,
                                      **snapshot_fields(stats))
            if platform == "youtube":  # policy: raw counts only, no derived metrics
                snap.avg_engagement = None
            snap.raw = {"stats": stats, "collector": result.snapshot.get("raw"), "new_items": stored["new"],
                        "changed_items": stored["changed"]}
            db.add(snap)
            snapshot_id = snap.id
        if result.quota_used or result.cost_usd:
            db.add(UsageLedger(workspace_id=prof.workspace_id, kind="platform_reads", provider=platform or "web",
                               platform=prof.platform, quantity=result.quota_used, cost_usd=result.cost_usd,
                               ref_type="competitor_profile", ref_id=prof.id))
        news_res = None
        if news and prof.kind == "website":
            try:
                from app.research.collectors.news import collect_news
                news_res = await collect_news(db, comp, providers=news_providers)
            except Exception as e:  # news is best-effort
                news_res = {"error": f"{type(e).__name__}: {e}"[:200]}
        comp.last_synced_at = now
        await db.flush()
        if snapshot_id is not None and stats is not None:
            await emit(db, "COMPETITOR_SNAPSHOT_TAKEN", {
                "competitor_id": str(comp.id), "profile_id": str(prof.id), "snapshot_id": str(snapshot_id),
                "platform": platform or prof.kind, "deltas": stats.get("changes") or {}, "alerts": stats.get("alerts") or [],
                "new_items": stored["new"], "changed_items": stored["changed"]}, workspace_id=prof.workspace_id)
        return {"profile_id": str(prof.id), "status": result.status, "reason": result.reason, "items": len(result.items),
                "new": stored["new"], "changed": stored["changed"], "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "feeds": result.feeds, "news": news_res}

    @classmethod
    async def _store_items(cls, db: AsyncSession, comp: Competitor, prof: CompetitorProfile, items: list[Any], *,
                           now: datetime) -> dict[str, int]:
        new = changed = 0
        if not items:
            return {"new": 0, "changed": 0}
        latest_by_url: dict[str, tuple[UUID, str]] = {}
        if prof.platform is None:
            rows = (await db.execute(select(CompetitorPost.id, CompetitorPost.url, CompetitorPost.content_hash)
                                     .where(CompetitorPost.profile_id == prof.id)
                                     .order_by(CompetitorPost.retrieved_at))).all()
            for pid, url, h in rows:
                if url:
                    latest_by_url[url] = (pid, h)
        for it in items:
            h = it.content_hash
            analysis: dict[str, Any] = dict(it.meta or {})
            prev = latest_by_url.get(it.url or "") if prof.platform is None else None
            if prev is not None and prev[1] == h:
                await db.execute(update(CompetitorPost).where(CompetitorPost.id == prev[0]).values(retrieved_at=now))
                continue
            if prof.platform is None:
                analysis["change"] = "updated" if prev is not None else "new"
                if prev is not None:
                    analysis["previous_post_id"] = str(prev[0])
            retention = now + timedelta(days=it.retention_days) if it.retention_days else None
            values = dict(id=new_id(), workspace_id=prof.workspace_id, profile_id=prof.id, platform=prof.platform,
                          external_id=it.external_id, url=it.url, posted_at=it.posted_at, format=it.format,
                          text=it.text, hashtags=it.hashtags, mentions=it.mentions, media_urls=it.media_urls,
                          like_count=it.like_count, comment_count=it.comment_count, share_count=it.share_count,
                          view_count=it.view_count, availability=it.availability, content_hash=h, analysis=analysis,
                          retention_until=retention, retrieved_at=now)
            stmt = pg_insert(CompetitorPost).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["profile_id", "content_hash"],
                set_={"like_count": stmt.excluded.like_count, "comment_count": stmt.excluded.comment_count,
                      "share_count": stmt.excluded.share_count, "view_count": stmt.excluded.view_count,
                      "retrieved_at": stmt.excluded.retrieved_at, "retention_until": stmt.excluded.retention_until},
            ).returning(CompetitorPost.id, CompetitorPost.retrieved_at)
            row = (await db.execute(stmt)).first()
            inserted = row is not None and row[0] == values["id"]
            if inserted:
                if analysis.get("change") == "updated":
                    changed += 1
                else:
                    new += 1
        return {"new": new, "changed": changed}

    @classmethod
    async def _register_feeds(cls, db: AsyncSession, comp: Competitor, feeds: list[str]) -> None:
        for f in feeds[:5]:
            canon = safe_canonicalize(f)
            if not canon:
                continue
            exists = (await db.execute(select(RssFeed.id).where(RssFeed.workspace_id == comp.workspace_id,
                                                                RssFeed.url == canon))).scalar_one_or_none()
            if exists is None:
                db.add(RssFeed(id=new_id(), workspace_id=comp.workspace_id, brand_id=comp.brand_id, competitor_id=comp.id,
                               url=canon, status="active", title=f"{comp.name} feed"))
        await db.flush()

    # ------------------------------------------------------------------------------------------ stats
    @classmethod
    async def describe(cls, db: AsyncSession, profile_id: UUID, *, days: int = 90, followers: int | None = None
                       ) -> dict[str, Any]:
        prof = await db.get(CompetitorProfile, profile_id)
        if prof is None:
            raise not_found("Competitor profile")
        since = datetime.now(UTC) - timedelta(days=days)
        posts = list((await db.execute(select(CompetitorPost).where(
            CompetitorPost.profile_id == profile_id,
            or_(CompetitorPost.posted_at >= since, CompetitorPost.posted_at.is_(None))).order_by(
            CompetitorPost.posted_at.desc().nulls_last()).limit(2000))).scalars())
        prev = (await db.execute(select(CompetitorSnapshot).where(CompetitorSnapshot.profile_id == profile_id)
                                 .order_by(CompetitorSnapshot.captured_at.desc()).limit(1))).scalar_one_or_none()
        previous = None
        if prev is not None:
            previous = {"posts_last_7d": prev.posts_last_7d, "posts_last_30d": prev.posts_last_30d,
                        "followers_count": prev.followers_count, "format_mix": prev.format_mix}
        stats = describe_posts(posts, followers=followers if followers is not None else prof.followers_count,
                               previous=previous, allow_derived=_platform_value(prof.platform) != "youtube")
        stats["profile_id"] = str(profile_id)
        stats["platform"] = _platform_value(prof.platform) or prof.kind
        stats["availability"] = prof.availability.value
        if _platform_value(prof.platform) == "youtube":
            stats["policy_label"] = "last 30 days, raw counts"
        return stats

    @classmethod
    async def list_posts(cls, db: AsyncSession, workspace_id: UUID, competitor_id: UUID, *, profile_id: UUID | None = None,
                         platform: str | None = None, since: datetime | None = None, limit: int = 50,
                         offset: int = 0) -> list[CompetitorPost]:
        comp = await cls.get(db, workspace_id, competitor_id)
        pids = [p.id for p in comp.profiles if (profile_id is None or p.id == profile_id)
                and (platform is None or (_platform_value(p.platform) or p.kind) == platform)]
        if not pids:
            return []
        stmt = select(CompetitorPost).where(CompetitorPost.workspace_id == workspace_id, CompetitorPost.profile_id.in_(pids))
        if since:
            stmt = stmt.where(CompetitorPost.posted_at >= since)
        stmt = stmt.order_by(CompetitorPost.posted_at.desc().nulls_last(), CompetitorPost.retrieved_at.desc())
        return list((await db.execute(stmt.offset(offset).limit(limit))).scalars())

    @classmethod
    async def list_snapshots(cls, db: AsyncSession, workspace_id: UUID, competitor_id: UUID, *,
                             profile_id: UUID | None = None, limit: int = 50) -> list[CompetitorSnapshot]:
        comp = await cls.get(db, workspace_id, competitor_id)
        pids = [p.id for p in comp.profiles if profile_id is None or p.id == profile_id]
        if not pids:
            return []
        return list((await db.execute(select(CompetitorSnapshot).where(
            CompetitorSnapshot.workspace_id == workspace_id, CompetitorSnapshot.profile_id.in_(pids))
            .order_by(CompetitorSnapshot.captured_at.desc()).limit(limit))).scalars())

    # ------------------------------------------------------------------------------------------ comparison
    @classmethod
    async def compare(cls, db: AsyncSession, workspace_id: UUID, competitor_ids: list[UUID], *, period_days: int = 90
                      ) -> dict[str, Any]:
        if not competitor_ids:
            raise validation("ids required")
        comps = list((await db.execute(select(Competitor).where(Competitor.workspace_id == workspace_id,
                                                                Competitor.id.in_(competitor_ids)))).scalars())
        if len(comps) != len(set(competitor_ids)):
            raise not_found("Competitor")
        comps.sort(key=lambda c: competitor_ids.index(c.id))
        since = datetime.now(UTC) - timedelta(days=period_days)
        weeks = period_days / 7
        brand_ids = {c.brand_id for c in comps}
        columns: list[dict[str, Any]] = []
        metrics: dict[str, list[Any]] = {k: [] for k in ("posts_per_week", "posts_in_period", "blog_pages_in_period",
                                                         "followers_total", "top_format", "format_mix", "top_hashtags",
                                                         "avg_engagement", "cta_share", "link_share", "news_mentions",
                                                         "platforms_tracked")}
        avail: dict[str, list[str]] = {k: [] for k in metrics}

        if len(brand_ids) == 1:
            brand_id = next(iter(brand_ids))
            brand = await db.get(Brand, brand_id)
            columns.append({"kind": "brand", "id": str(brand_id), "name": brand.name if brand else "Our brand"})
            bstats = await cls._brand_stats(db, workspace_id, brand_id, since)
            for k in metrics:
                metrics[k].append(bstats.get(k))
                avail[k].append(bstats.get("_avail", {}).get(k, "internal" if bstats.get(k) is not None else "not_available"))

        for c in comps:
            columns.append({"kind": "competitor", "id": str(c.id), "name": c.name})
            social = [p for p in c.profiles if p.platform is not None]
            web = [p for p in c.profiles if p.platform is None]
            pids = [p.id for p in c.profiles]
            posts = list((await db.execute(select(CompetitorPost).where(CompetitorPost.profile_id.in_(pids),
                                                                        CompetitorPost.posted_at >= since))).scalars()) if pids else []
            social_ids = {p.id for p in social}
            sposts = [p for p in posts if p.profile_id in social_ids]
            wposts = [p for p in posts if p.profile_id not in social_ids]
            derived_ok = [p for p in sposts if _platform_value(p.platform) != "youtube"]
            st = describe_posts(sposts, followers=None, allow_derived=True) if sposts else None
            st_eng = describe_posts(derived_ok, allow_derived=True) if derived_ok else None
            followers = [p.followers_count for p in social if p.followers_count is not None]
            news = (await db.execute(select(func.count()).select_from(ResearchSource).where(
                ResearchSource.workspace_id == workspace_id, ResearchSource.competitor_id == c.id,
                ResearchSource.source_kind == "news", ResearchSource.retrieved_at >= since))).scalar_one()
            social_avail = "official_api" if any(p.availability == Availability.official_api for p in social) else "not_collected"
            vals = {
                "posts_per_week": round(len(sposts) / weeks, 2) if social_avail != "not_collected" else None,
                "posts_in_period": len(sposts) if social_avail != "not_collected" else None,
                "blog_pages_in_period": len(wposts) if web else None,
                "followers_total": sum(followers) if followers else None,
                "top_format": next(iter(st["format_mix"]), None) if st else None,
                "format_mix": st["format_mix"] if st else None,
                "top_hashtags": [t for t, _ in st["hashtags"]["top"][:5]] if st else None,
                "avg_engagement": st_eng["engagement"].get("avg_interactions") if st_eng and st_eng["engagement"].get("available") else None,
                "cta_share": st["cta_share"] if st else None,
                "link_share": st["link_share"] if st else None,
                "news_mentions": int(news),
                "platforms_tracked": sorted({_platform_value(p.platform) or p.kind for p in c.profiles}),
            }
            for k, v in vals.items():
                metrics[k].append(v)
                if k in ("blog_pages_in_period",):
                    avail[k].append("public_web" if web else "not_collected")
                elif k == "news_mentions":
                    avail[k].append("search")
                elif k == "platforms_tracked":
                    avail[k].append("internal")
                else:
                    avail[k].append(social_avail if v is not None else ("not_available" if social_avail != "not_collected"
                                                                        else "not_collected"))
        rows = [{"metric": k, "values": metrics[k], "availability": avail[k]} for k in metrics]
        notes = []
        if any(_platform_value(p.platform) == "youtube" for c in comps for p in c.profiles):
            notes.append("YouTube: last 30 days, raw counts (no derived metrics per YouTube API Services policy)")
        return {"period_days": period_days, "columns": columns, "rows": rows, "notes": notes}

    @classmethod
    async def _brand_stats(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, since: datetime) -> dict[str, Any]:
        try:
            from app.models.content import ContentVariant
            from app.models.scheduling import PublishedPost
            rows = (await db.execute(select(PublishedPost.platform, PublishedPost.published_at, ContentVariant.format,
                                            ContentVariant.text, ContentVariant.hashtags)
                                     .outerjoin(ContentVariant, ContentVariant.id == PublishedPost.content_variant_id)
                                     .where(PublishedPost.workspace_id == workspace_id, PublishedPost.brand_id == brand_id,
                                            PublishedPost.published_at >= since, PublishedPost.deleted_at.is_(None)))).all()
            accounts = (await db.execute(select(SocialAccount.platform).where(
                SocialAccount.workspace_id == workspace_id, SocialAccount.brand_id == brand_id,
                SocialAccount.disconnected_at.is_(None)))).scalars().all()
        except Exception as e:
            log.info("competitors.brand_stats_unavailable", error=str(e)[:200])
            return {}
        posts = [{"posted_at": r[1], "format": r[2], "text": r[3], "hashtags": r[4] or []} for r in rows]
        weeks = max(1e-9, (datetime.now(UTC) - since).days / 7)
        st = describe_posts(posts) if posts else None
        return {"posts_per_week": round(len(posts) / weeks, 2), "posts_in_period": len(posts),
                "top_format": next(iter(st["format_mix"]), None) if st else None,
                "format_mix": st["format_mix"] if st else None,
                "top_hashtags": [t for t, _ in st["hashtags"]["top"][:5]] if st else None,
                "cta_share": st["cta_share"] if st else None, "link_share": st["link_share"] if st else None,
                "platforms_tracked": sorted({_platform_value(a) for a in accounts}),
                "_avail": {"avg_engagement": "see analytics", "followers_total": "see analytics", "news_mentions": "not_applicable",
                           "blog_pages_in_period": "not_applicable"}}

    # ------------------------------------------------------------------------------------------ topic gaps (doc 08 §8.6)
    @classmethod
    async def topic_clusters(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID,
                             competitor_ids: list[UUID] | None = None, *, days: int = 90) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = select(Competitor).where(Competitor.workspace_id == workspace_id, Competitor.brand_id == brand_id)
        if competitor_ids:
            stmt = stmt.where(Competitor.id.in_(competitor_ids))
        comps = list((await db.execute(stmt)).scalars())
        docs: list[tuple[dict[str, Any], set[str]]] = []
        try:
            from app.models.content import ContentItem
            items = (await db.execute(select(ContentItem.id, ContentItem.title, ContentItem.body).where(
                ContentItem.workspace_id == workspace_id, ContentItem.brand_id == brand_id,
                ContentItem.created_at >= since).limit(500))).all()
        except Exception:
            items = []
        for cid, title, body in items:
            body = body or {}
            txt = " ".join(str(body.get(k) or "") for k in ("hook", "body_md", "cta")) + f" {title or ''}"
            docs.append(({"owner": "brand", "id": str(cid), "text": txt}, set(top_terms(txt, 8, with_bigrams=False))))
        prof_owner: dict[UUID, UUID] = {p.id: c.id for c in comps for p in c.profiles}
        if prof_owner:
            posts = (await db.execute(select(CompetitorPost.id, CompetitorPost.profile_id, CompetitorPost.text,
                                             CompetitorPost.hashtags, CompetitorPost.like_count, CompetitorPost.comment_count)
                                      .where(CompetitorPost.profile_id.in_(list(prof_owner)),
                                             or_(CompetitorPost.posted_at >= since, CompetitorPost.posted_at.is_(None)))
                                      .limit(3000))).all()
            for pid, profile_id, txt, tags, likes, comments in posts:
                t = f"{txt or ''} {' '.join(tags or [])}"
                docs.append(({"owner": str(prof_owner[profile_id]), "id": str(pid), "text": t,
                              "engagement": (likes or 0) + (comments or 0) if likes is not None or comments is not None else None},
                             set(top_terms(t[:5000], 8, with_bigrams=False))))
        method = "keyword_jaccard"
        groups: list[list[int]] | None = None
        try:
            from app.research.ai import get_embedder
            embedder = await get_embedder(db, workspace_id)
        except Exception:
            embedder = None
        if embedder is not None and docs:
            vecs = await embedder.embed([d[0]["text"][:2000] or " " for d in docs])
            if vecs:
                groups = _cluster_vectors(vecs, threshold=0.78)
                method = "embedding_cosine"
        if groups is None:
            groups = cluster_by_jaccard([(d[0], d[1]) for d in docs], threshold=0.2)
        comp_names = {str(c.id): c.name for c in comps}
        clusters = []
        for gi, members in enumerate(groups):
            if not members:
                continue
            terms = Counter(t for m in members for t in docs[m][1])
            label_terms = [t for t, _ in terms.most_common(3)]
            ours = sum(1 for m in members if docs[m][0]["owner"] == "brand")
            theirs: Counter[str] = Counter(docs[m][0]["owner"] for m in members if docs[m][0]["owner"] != "brand")
            eng = [docs[m][0].get("engagement") for m in members if docs[m][0].get("engagement") is not None]
            n_comp = len(theirs)
            gap = (n_comp >= 2 and ours == 0) or (len(comps) == 1 and n_comp == 1 and ours == 0 and sum(theirs.values()) >= 2)
            clusters.append({
                "id": f"c{gi}", "label": " / ".join(label_terms), "terms": [t for t, _ in terms.most_common(10)],
                "size": len(members), "coverage": {"ours": ours, "competitors": {comp_names.get(k, k): v for k, v in theirs.items()}},
                "competitor_count": n_comp, "gap": gap,
                "audience_interest": round(sum(eng) / len(eng), 2) if eng else None,
                "evidence": {"competitor_post_ids": [docs[m][0]["id"] for m in members if docs[m][0]["owner"] != "brand"][:10],
                             "content_item_ids": [docs[m][0]["id"] for m in members if docs[m][0]["owner"] == "brand"][:10]},
            })
        clusters.sort(key=lambda c: (-int(c["gap"]), -c["competitor_count"], -c["size"]))
        return {"brand_id": str(brand_id), "window_days": days, "method": method, "clusters": clusters[:60],
                "gaps": [c for c in clusters if c["gap"]][:20], "documents": len(docs)}

    # ------------------------------------------------------------------------------------------ analysis & reports
    @classmethod
    async def save_analysis(cls, db: AsyncSession, workspace_id: UUID, competitor_id: UUID, *, analysis: dict[str, Any],
                            post_labels: list[dict[str, Any]] | None = None, actor: dict[str, Any] | None = None,
                            ai_run_id: UUID | None = None, created_by: UUID | None = None) -> dict[str, Any]:
        comp = await cls.get(db, workspace_id, competitor_id)
        pids = {p.id for p in comp.profiles}
        labeled = 0
        for lab in post_labels or []:
            try:
                pid = UUID(str(lab.get("post_id")))
            except (TypeError, ValueError):
                continue
            post = await db.get(CompetitorPost, pid)
            if post is None or post.profile_id not in pids:
                continue
            labels = {k: v for k, v in lab.items() if k != "post_id"}
            post.analysis = {**(post.analysis or {}), "labels": labels, "labeled_at": datetime.now(UTC).isoformat()}
            labeled += 1
        report = CompetitorReport(id=new_id(), workspace_id=workspace_id, brand_id=comp.brand_id, competitor_ids=[comp.id],
                                  kind="single", content={"analysis": analysis, "source": "competitor_intel",
                                                          "actor": actor or {"type": "system"}},
                                  ai_run_id=ai_run_id, created_by=created_by, period_end=datetime.now(UTC).date())
        db.add(report)
        await db.flush()
        await emit(db, "COMPETITOR_UPDATED", {"competitor_id": str(comp.id), "changes": ["analysis"],
                                              "report_id": str(report.id)}, workspace_id=workspace_id, actor=actor)
        return {"report_id": str(report.id), "posts_labeled": labeled}

    @classmethod
    async def list_reports(cls, db: AsyncSession, workspace_id: UUID, competitor_id: UUID) -> list[CompetitorReport]:
        await cls.get(db, workspace_id, competitor_id)
        return list((await db.execute(select(CompetitorReport).where(
            CompetitorReport.workspace_id == workspace_id, literal(competitor_id) == any_(CompetitorReport.competitor_ids))
            .order_by(CompetitorReport.created_at.desc()).limit(100))).scalars())

    @classmethod
    async def create_report(cls, db: AsyncSession, member: Any, competitor_id: UUID, data: ReportCreate) -> CompetitorReport:
        comp = await cls.get(db, member.workspace_id, competitor_id)
        try:
            from app.agents.orchestrator.service import AIService  # type: ignore[import-not-found]
        except ImportError as e:
            raise ProblemError(501, "not_implemented", "Not implemented",
                               "AI reports are not available yet (AI service not installed)") from e
        ids = [comp.id] + [i for i in data.competitor_ids if i != comp.id]
        if len(ids) > 1:
            found = set((await db.execute(select(Competitor.id).where(Competitor.workspace_id == member.workspace_id,
                                                                      Competitor.id.in_(ids)))).scalars())
            if found != set(ids):
                raise not_found("Competitor")
        today = datetime.now(UTC).date()
        kind = data.kind if len(ids) == 1 or data.kind != "single" else "comparison"
        report = CompetitorReport(id=new_id(), workspace_id=member.workspace_id, brand_id=comp.brand_id, competitor_ids=ids,
                                  kind=kind, period_start=today - timedelta(days=data.period_days), period_end=today,
                                  content={"status": "pending"}, created_by=getattr(getattr(member, "user", None), "id", None))
        db.add(report)
        await db.flush()
        inputs = {"kind": "competitor" if kind == "single" else kind, "competitor_ids": [str(i) for i in ids],
                  "period_days": data.period_days, "instructions": data.instructions,
                  "competitor_report_id": str(report.id)}
        run = await AIService().create_run(db, member, message=f"Compose a {kind} competitor report for {comp.name} "
                                                               f"covering the last {data.period_days} days.",
                                           brand_id=comp.brand_id, mode="tool", agent="report", action="compose",
                                           inputs=inputs)
        report.ai_run_id = getattr(run, "id", None)
        report.content = {"status": "pending", "inputs": inputs}
        await db.flush()
        await _audit(db, member, "competitor.report_requested", "competitor_report", report.id, after=inputs)
        return report

    # ------------------------------------------------------------------------------------------ retention (doc 08 §8.7)
    @classmethod
    async def enforce_retention(cls, db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(UTC)
        r1 = await db.execute(delete(CompetitorPost).where(CompetitorPost.retention_until.is_not(None),
                                                           CompetitorPost.retention_until < now))
        yt_profiles = select(CompetitorProfile.id).where(CompetitorProfile.platform == Platform.youtube)
        r2 = await db.execute(delete(CompetitorSnapshot).where(CompetitorSnapshot.profile_id.in_(yt_profiles),
                                                               CompetitorSnapshot.captured_at < now - YOUTUBE_RETENTION))
        r3 = await db.execute(update(CompetitorSnapshot).where(CompetitorSnapshot.raw.is_not(None),
                                                               CompetitorSnapshot.captured_at < now - RAW_RETENTION)
                              .values(raw=None))
        r4 = await db.execute(delete(CompetitorPost).where(CompetitorPost.retrieved_at < now - POST_RETENTION,
                                                           CompetitorPost.retention_until.is_(None)))
        return {"expired_posts": r1.rowcount or 0, "youtube_snapshots": r2.rowcount or 0, "raw_cleared": r3.rowcount or 0,
                "old_posts": r4.rowcount or 0}


def _cluster_vectors(vecs: list[list[float]], *, threshold: float = 0.78) -> list[list[int]]:
    import numpy as np
    m = np.asarray(vecs, dtype=float)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    m = m / norms
    centroids: list[Any] = []
    groups: list[list[int]] = []
    for i, v in enumerate(m):
        if centroids:
            sims = np.asarray([float(c @ v) for c in centroids])
            j = int(sims.argmax())
            if sims[j] >= threshold:
                groups[j].append(i)
                c = m[groups[j]].mean(axis=0)
                centroids[j] = c / (np.linalg.norm(c) or 1.0)
                continue
        centroids.append(v)
        groups.append([i])
    return groups


async def enqueue_due_syncs(db: AsyncSession, *, now: datetime | None = None, limit: int = 100) -> int:
    """Scheduler hook: enqueue ``jobs.competitors.sync_profile`` for profiles whose competitor's monitoring_frequency is
    due (daily ≥ 24 h, weekly ≥ 7 d since the last sync). Queueing locks make it safe to call every tick."""
    now = now or datetime.now(UTC)
    from app.research.queue import defer
    rows = (await db.execute(select(CompetitorProfile, Competitor.monitoring_frequency).join(
        Competitor, Competitor.id == CompetitorProfile.competitor_id).where(
        Competitor.status == "active", Competitor.monitoring_frequency.in_(("daily", "weekly")),
        CompetitorProfile.availability != Availability.not_collected,
        or_(CompetitorProfile.sync_status.is_(None), CompetitorProfile.sync_status.notin_(("queued", "running")),
            CompetitorProfile.updated_at < now - timedelta(hours=2)))  # recover profiles stuck in queued/running
        .limit(limit * 4))).all()
    n = 0
    for prof, freq in rows:
        interval = timedelta(days=1) if freq == "daily" else timedelta(days=7)
        last = prof.last_synced_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last is not None and now - last < interval:
            continue
        try:
            await defer("jobs.competitors.sync_profile", queue="research", lock=f"competitor_sync:{prof.id}",
                        profile_id=str(prof.id), workspace_id=str(prof.workspace_id))
            prof.sync_status = "queued"
            n += 1
        except Exception as e:
            log.warning("competitors.enqueue_due_failed", profile_id=str(prof.id), error=str(e)[:200])
            break
        if n >= limit:
            break
    await db.flush()
    return n
