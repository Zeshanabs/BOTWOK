"""Website/blog collector (class B, public web): bounded crawl (≤ 50 pages, depth 2) via SafeFetcher with robots.txt
honored, RSS discovery, and content-hash change detection (done by the service against stored competitor_posts)."""
from __future__ import annotations

from app.core.safe_fetch import SafeFetcher, get_fetcher
from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import Availability, ContentFormat
from app.research.collectors.base import CollectedItem, CollectorResult, has_link
from app.research.crawl import crawl_site
from app.research.injection import classify

MAX_PAGES = 50
MAX_DEPTH = 2
TEXT_CAP = 20_000


async def collect_website(competitor: Competitor, profile: CompetitorProfile, *, fetcher: SafeFetcher | None = None,
                          max_pages: int = MAX_PAGES, max_depth: int = MAX_DEPTH) -> CollectorResult:
    start = profile.url or competitor.website
    if not start:
        return CollectorResult(status="error", availability=Availability.public_web, reason="no website url")
    fetcher = fetcher or get_fetcher()
    cr = await crawl_site(fetcher, start, max_pages=min(MAX_PAGES, max_pages), max_depth=min(MAX_DEPTH, max_depth))
    items: list[CollectedItem] = []
    for p in cr.pages:
        text = classify(p.text).sanitized_text
        body = f"{p.title}\n\n{text}" if p.title else text
        items.append(CollectedItem(text=body[:TEXT_CAP], url=p.canonical_url, posted_at=p.published_at,
                                   format=ContentFormat.article, availability=Availability.public_web,
                                   meta={"title": p.title, "depth": p.depth, "page_hash": p.content_hash,
                                         "has_link": has_link(text), "language": p.language}))
    status = "ok" if items else ("error" if cr.errors and not cr.skipped_robots else "partial")
    reason = None
    if not items:
        reason = "no pages collected" + (f" ({cr.skipped_robots} disallowed by robots.txt)" if cr.skipped_robots else "")
    return CollectorResult(status=status, availability=Availability.public_web, items=items, feeds=cr.feeds, reason=reason,
                           snapshot={"raw": {"pages_crawled": len(cr.pages), "fetched": cr.fetched,
                                             "skipped_robots": cr.skipped_robots, "errors": cr.errors[:20],
                                             "feeds": cr.feeds}})
