"""RSS/Atom reading and polling (doc 07 §7.6 "RSS"): SafeFetcher + feedparser, conditional GET via ETag."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.resilience import ResilienceError
from app.core.safe_fetch import SafeFetcher, get_fetcher
from app.integrations.search.base import parse_date
from app.models.research import RssFeed
from app.research.dedupe import content_hash, simhash64, to_signed64
from app.research.enrich import heuristic_enrichment
from app.research.injection import classify, sanitize
from app.research.score import credibility
from app.research.store import SourceData, format_citation, upsert_source
from app.research.urls import domain_of, safe_canonicalize

log = get_logger("research.feeds")
FEED_CONTENT_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "text/html",
                      "text/plain", "application/json")
POLL_INTERVAL = timedelta(hours=1)


@dataclass
class FeedEntry:
    title: str
    url: str
    published_at: datetime | None
    summary: str
    author: str | None = None


@dataclass
class FeedRead:
    url: str
    title: str | None = None
    entries: list[FeedEntry] = field(default_factory=list)
    etag: str | None = None
    not_modified: bool = False


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def parse_feed(raw: bytes | str, url: str) -> FeedRead:
    import feedparser
    parsed = feedparser.parse(raw)
    out = FeedRead(url=url, title=sanitize(parsed.feed.get("title") or "") or None)
    for e in parsed.entries[:100]:
        link = e.get("link") or ""
        if not link.startswith(("http://", "https://")):
            continue
        summary = _strip_html(e.get("summary") or "")
        if not summary and e.get("content"):
            summary = _strip_html((e.get("content") or [{}])[0].get("value", ""))
        out.entries.append(FeedEntry(title=sanitize(e.get("title") or link), url=link,
                                     published_at=parse_date(e.get("published") or e.get("updated")),
                                     summary=sanitize(summary)[:4000], author=sanitize(e.get("author") or "") or None))
    return out


async def read_feed(url: str, *, fetcher: SafeFetcher | None = None, etag: str | None = None) -> FeedRead:
    fetcher = fetcher or get_fetcher()
    headers = {"If-None-Match": etag} if etag else None
    fr = await fetcher.fetch(url, mode="fetch", allowed_content_types=FEED_CONTENT_TYPES, headers=headers)
    if fr.status == 304:
        return FeedRead(url=url, etag=etag, not_modified=True)
    res = parse_feed(fr.content, fr.final_url)
    res.etag = fr.headers.get("etag")
    return res


async def store_entries(db: AsyncSession, workspace_id: UUID, entries: list[FeedEntry], *,
                        competitor_id: UUID | None = None) -> int:
    """Persist feed items as research_sources (kind rss) without fetching the article pages."""
    n = 0
    for e in entries:
        canon = safe_canonicalize(e.url)
        if not canon:
            continue
        text = f"{e.title}\n\n{e.summary}".strip()
        report = classify(text)
        enr = heuristic_enrichment(report.sanitized_text, url=canon, title=e.title)
        cred, comps = credibility(url=canon, domain=domain_of(canon), author=e.author, published_at=e.published_at,
                                  text=report.sanitized_text, injection_flag=report.flagged)
        _, created = await upsert_source(db, workspace_id, SourceData(
            canonical_url=canon, domain=domain_of(canon), final_url=e.url, title=e.title, author=e.author,
            source_kind="rss", published_at=e.published_at, summary=enr.summary or e.summary[:800], keywords=enr.keywords,
            topics=enr.topics, entities={**enr.entities_json(), "injection": report.to_dict()}, credibility_score=cred,
            credibility_components=comps, citation=format_citation(e.title, domain_of(canon), canon, e.author, e.published_at),
            content_hash=content_hash(text), simhash=to_signed64(simhash64(text)), word_count=len(text.split()),
            injection_flag=report.flagged, fetch_status="feed_item", competitor_id=competitor_id))
        n += int(created)
    return n


async def poll_feed(db: AsyncSession, feed: RssFeed, *, fetcher: SafeFetcher | None = None) -> dict[str, Any]:
    now = datetime.now(UTC)
    try:
        res = await read_feed(feed.url, fetcher=fetcher, etag=feed.last_etag)
    except ResilienceError as e:
        feed.last_polled_at = now
        feed.last_error = e.message[:500]
        if e.code in ("unsafe_url", "robots_disallowed") or e.status in (404, 410):
            feed.status = "error"
        return {"feed_id": str(feed.id), "new": 0, "error": e.message}
    feed.last_polled_at = now
    feed.last_error = None
    if res.not_modified:
        return {"feed_id": str(feed.id), "new": 0, "not_modified": True}
    if res.etag:
        feed.last_etag = res.etag
    if res.title and not feed.title:
        feed.title = res.title[:300]
    new = await store_entries(db, feed.workspace_id, res.entries, competitor_id=feed.competitor_id)
    return {"feed_id": str(feed.id), "new": new, "entries": len(res.entries)}


async def due_feeds(db: AsyncSession, *, workspace_id: UUID | None = None, brand_id: UUID | None = None,
                    limit: int = 50) -> list[RssFeed]:
    cutoff = datetime.now(UTC) - POLL_INTERVAL
    stmt = select(RssFeed).where(RssFeed.status == "active",
                                 or_(RssFeed.last_polled_at.is_(None), RssFeed.last_polled_at < cutoff))
    if workspace_id:
        stmt = stmt.where(RssFeed.workspace_id == workspace_id)
    if brand_id:
        stmt = stmt.where(or_(RssFeed.brand_id == brand_id, RssFeed.brand_id.is_(None)))
    return list((await db.execute(stmt.order_by(RssFeed.last_polled_at.nulls_first()).limit(limit))).scalars())
