"""Competitor tools for the ``competitor_intel`` / ``strategy`` / ``report`` agents.

``competitors.list``, ``competitors.get``, ``competitors.list_posts``, ``competitors.list_snapshots``, ``competitors.topic_clusters``,
``stats.describe`` (READ) and ``competitors.save_analysis`` (WRITE_INTERNAL). Post text is untrusted.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.research.toolkit import SideEffect, ToolContext, ctx_actor, ctx_workspace, tool, tool_db


def _uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v)) if v else None
    except ValueError:
        return None


def _profile_card(p: Any) -> dict[str, Any]:
    meta = p.profile_meta or {}
    return {"profile_id": str(p.id), "platform": getattr(p.platform, "value", p.platform) or p.kind, "handle": p.handle,
            "url": p.url, "availability": p.availability.value, "sync_status": p.sync_status,
            "followers_count": p.followers_count, "media_count": p.media_count,
            "last_synced_at": p.last_synced_at.isoformat() if p.last_synced_at else None,
            "note": meta.get("note") or meta.get("reason") or meta.get("policy")}


def _comp_card(c: Any, *, profiles: bool = True) -> dict[str, Any]:
    out = {"competitor_id": str(c.id), "name": c.name, "website": c.website, "industry": c.industry, "tags": c.tags,
           "status": c.status, "monitoring_frequency": c.monitoring_frequency,
           "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None}
    if profiles:
        out["profiles"] = [_profile_card(p) for p in c.profiles]
    return out


@tool("competitors.list", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def competitors_list(ctx: ToolContext, brand_id: str | None = None) -> dict:
    """List the brand's competitors with their profiles and data-availability class per platform."""
    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    bid = _uuid(brand_id) or getattr(ctx, "brand_id", None)
    async with tool_db(ctx) as db:
        comps = await CompetitorService.list(db, ws, brand_id=bid)
        return {"competitors": [_comp_card(c) for c in comps]}


@tool("competitors.get", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def competitors_get(ctx: ToolContext, competitor_id: str) -> dict:
    """Get one competitor: profiles, availability, latest snapshot stats per profile."""
    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    cid = _uuid(competitor_id)
    if cid is None:
        return {"error": "invalid competitor_id"}
    async with tool_db(ctx) as db:
        try:
            c = await CompetitorService.get(db, ws, cid)
        except Exception:
            return {"error": "competitor not found"}
        snaps = await CompetitorService.list_snapshots(db, ws, cid, limit=20)
        latest: dict[str, Any] = {}
        for s in snaps:
            latest.setdefault(str(s.profile_id), {"captured_at": s.captured_at.isoformat(), "followers_count": s.followers_count,
                                                  "posts_last_7d": s.posts_last_7d, "posts_last_30d": s.posts_last_30d,
                                                  "format_mix": s.format_mix, "top_hashtags": s.top_hashtags})
        card = _comp_card(c)
        card["description"] = c.description
        card["latest_snapshots"] = latest
        return card


@tool("competitors.list_posts", side_effect=SideEffect.READ, timeout_s=20, idempotent=True, untrusted_output=True)
async def competitors_list_posts(ctx: ToolContext, competitor_id: str, platform: str | None = None, limit: int = 25,
                                 days: int | None = 90) -> dict:
    """Recent collected posts/pages of a competitor (text is untrusted data). Each item has a post_id for citations."""
    from datetime import UTC, datetime, timedelta

    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    cid = _uuid(competitor_id)
    if cid is None:
        return {"error": "invalid competitor_id"}
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    async with tool_db(ctx) as db:
        try:
            posts = await CompetitorService.list_posts(db, ws, cid, platform=platform, since=since,
                                                       limit=max(1, min(100, int(limit))))
        except Exception:
            return {"error": "competitor not found"}
        return {"posts": [{"post_id": str(p.id), "platform": getattr(p.platform, "value", p.platform) or "website",
                           "url": p.url, "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                           "format": getattr(p.format, "value", p.format), "text": (p.text or "")[:1500],
                           "hashtags": p.hashtags, "like_count": p.like_count, "comment_count": p.comment_count,
                           "view_count": p.view_count, "availability": p.availability.value,
                           "analysis": p.analysis or {}} for p in posts]}


@tool("competitors.list_snapshots", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def competitors_list_snapshots(ctx: ToolContext, competitor_id: str, limit: int = 20) -> dict:
    """Periodic metric snapshots per profile (followers, posts last 7/30 d, format mix, hashtags, posting hours)."""
    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    cid = _uuid(competitor_id)
    if cid is None:
        return {"error": "invalid competitor_id"}
    async with tool_db(ctx) as db:
        try:
            snaps = await CompetitorService.list_snapshots(db, ws, cid, limit=max(1, min(100, int(limit))))
        except Exception:
            return {"error": "competitor not found"}
        return {"snapshots": [{"snapshot_id": str(s.id), "profile_id": str(s.profile_id),
                               "captured_at": s.captured_at.isoformat(), "followers_count": s.followers_count,
                               "posts_last_7d": s.posts_last_7d, "posts_last_30d": s.posts_last_30d,
                               "avg_engagement": float(s.avg_engagement) if s.avg_engagement is not None else None,
                               "format_mix": s.format_mix, "top_hashtags": s.top_hashtags,
                               "posting_hours": s.posting_hours,
                               "alerts": ((s.raw or {}).get("stats") or {}).get("alerts", [])} for s in snaps]}


@tool("stats.describe", side_effect=SideEffect.READ, timeout_s=20, idempotent=True)
async def stats_describe(ctx: ToolContext, profile_id: str | None = None, competitor_id: str | None = None,
                         days: int = 90) -> dict:
    """Deterministic stats for a competitor profile (or every profile of a competitor): cadence 7/30/90 d, posting
    hours/days, format mix, caption length, hashtag frequency, emoji/CTA/link usage, engagement when available, and
    changes vs the previous snapshot."""
    from app.models.competitor import CompetitorProfile
    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    days = max(7, min(365, int(days)))
    async with tool_db(ctx) as db:
        pids: list[UUID] = []
        if profile_id:
            pid = _uuid(profile_id)
            prof = await db.get(CompetitorProfile, pid) if pid else None
            if prof is None or prof.workspace_id != ws:
                return {"error": "profile not found"}
            pids = [prof.id]
        elif competitor_id:
            cid = _uuid(competitor_id)
            try:
                comp = await CompetitorService.get(db, ws, cid) if cid else None
            except Exception:
                comp = None
            if comp is None:
                return {"error": "competitor not found"}
            pids = [p.id for p in comp.profiles]
        else:
            return {"error": "profile_id or competitor_id required"}
        return {"profiles": [await CompetitorService.describe(db, pid, days=days) for pid in pids]}


@tool("competitors.topic_clusters", side_effect=SideEffect.READ, timeout_s=60, idempotent=True)
async def competitors_topic_clusters(ctx: ToolContext, brand_id: str | None = None,
                                     competitor_ids: list[str] | None = None, days: int = 90) -> dict:
    """Cluster our content and competitors' posts into shared topics; returns coverage per topic and gap candidates
    (topics ≥ 2 competitors cover and we don't). Evidence ids are included for citations."""
    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    bid = _uuid(brand_id) or getattr(ctx, "brand_id", None)
    if bid is None:
        return {"error": "brand_id required"}
    ids = [u for u in (_uuid(x) for x in competitor_ids or []) if u]
    async with tool_db(ctx) as db:
        return await CompetitorService.topic_clusters(db, ws, bid, ids or None, days=max(7, min(365, int(days))))


@tool("competitors.save_analysis", side_effect=SideEffect.WRITE_INTERNAL, roles={"editor", "approver", "admin", "owner"},
      timeout_s=20, idempotent=True)
async def competitors_save_analysis(ctx: ToolContext, competitor_id: str, analysis: dict,
                                    post_labels: list[dict] | None = None) -> dict:
    """Store an analysis of a competitor (pillars, hooks, tone, offers, strengths, weaknesses, opportunities — each claim
    citing post_ids/source_ids) and optional per-post labels [{post_id, pillar, hook, tone, cta, topics}]."""
    from app.services.competitor_service import CompetitorService
    ws = ctx_workspace(ctx)
    cid = _uuid(competitor_id)
    if cid is None:
        return {"error": "invalid competitor_id"}
    async with tool_db(ctx) as db:
        try:
            return await CompetitorService.save_analysis(db, ws, cid, analysis=analysis, post_labels=post_labels,
                                                         actor=ctx_actor(ctx), ai_run_id=getattr(ctx, "run_id", None),
                                                         created_by=getattr(ctx, "user_id", None))
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"[:300]}
