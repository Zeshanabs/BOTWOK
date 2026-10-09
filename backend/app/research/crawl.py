"""Bounded same-site crawler on top of SafeFetcher (robots honored, per-host politeness from ResilientClient)."""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.core.logging import get_logger
from app.core.resilience import ResilienceError
from app.core.safe_fetch import SafeFetcher
from app.integrations.extract.readability_fallback import discover_feeds, extract_links
from app.integrations.extract.registry import extract
from app.research.dedupe import canonical_from_html, content_hash
from app.research.urls import safe_canonicalize, same_site

log = get_logger("research.crawl")

SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|ico|css|js|mjs|zip|gz|tgz|rar|7z|mp3|mp4|mov|avi|webm|woff2?|ttf|eot|"
                      r"exe|dmg|apk|iso|csv|xlsx?|docx?|pptx?)$", re.I)
SKIP_PATH = re.compile(r"/(wp-admin|wp-login|login|signin|sign-in|signup|register|account|cart|checkout|my-account|search|"
                       r"tag|tags|author|feed|comments|share|print|cdn-cgi)(/|$)|[?&](replytocom|share|print|session|sid)=", re.I)
HARD_MAX_PAGES = 200
HARD_MAX_DEPTH = 2


@dataclass
class CrawledPage:
    url: str
    canonical_url: str
    final_url: str
    depth: int
    title: str | None
    text: str
    author: str | None
    published_at: datetime | None
    language: str | None
    content_hash: str
    content_type: str
    is_pdf: bool = False
    html: str | None = None


@dataclass
class CrawlResult:
    pages: list[CrawledPage] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    skipped_robots: int = 0
    fetched: int = 0


def _priority(url: str) -> int:
    u = url.lower()
    if re.search(r"/(blog|news|press|newsroom|articles?|insights|resources|posts?|stories|updates)(/|$)", u):
        return 0
    if re.search(r"/(about|product|products|pricing|features|solutions|services|customers|case-stud)", u):
        return 1
    return 2


async def crawl_site(fetcher: SafeFetcher, start_url: str, *, max_pages: int = 50, max_depth: int = 2,
                     keep_html: bool = False, allow_pdf: bool = False) -> CrawlResult:
    """Breadth-first crawl limited to ``start_url``'s site. Robots.txt is always honored (mode="crawl")."""
    max_pages = max(1, min(HARD_MAX_PAGES, max_pages))
    max_depth = max(0, min(HARD_MAX_DEPTH, max_depth))
    res = CrawlResult()
    start = safe_canonicalize(start_url)
    if not start:
        res.errors.append({"url": start_url, "error": "invalid url"})
        return res
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    seen: set[str] = {start}
    seen_hashes: set[str] = set()
    while queue and len(res.pages) < max_pages:
        url, depth = queue.popleft()
        try:
            fr = await fetcher.fetch(url, mode="crawl")
        except ResilienceError as e:
            if e.code == "robots_disallowed":
                res.skipped_robots += 1
            else:
                res.errors.append({"url": url, "error": e.message[:200], "category": e.category})
            continue
        res.fetched += 1
        if fr.is_pdf and not allow_pdf:
            continue
        html = fr.text if not fr.is_pdf else ""
        doc = extract(fr.content if fr.is_pdf else html, fr.final_url, fr.content_type)
        canon = (canonical_from_html(html, fr.final_url) if html else None) or safe_canonicalize(fr.final_url) or url
        if html and depth == 0:
            for f in discover_feeds(html, fr.final_url):
                if f not in res.feeds:
                    res.feeds.append(f)
        if doc and doc.text.strip():
            h = content_hash(doc.text)
            if h not in seen_hashes:
                seen_hashes.add(h)
                res.pages.append(CrawledPage(url=url, canonical_url=canon, final_url=fr.final_url, depth=depth, title=doc.title,
                                             text=doc.text, author=doc.author, published_at=doc.published_at,
                                             language=doc.language, content_hash=h, content_type=fr.content_type,
                                             is_pdf=fr.is_pdf, html=html if keep_html else None))
        if depth >= max_depth or not html:
            continue
        nxt: list[str] = []
        for link in extract_links(html, fr.final_url, limit=400):
            c = safe_canonicalize(link)
            if not c or c in seen or not same_site(c, start) or SKIP_EXT.search(c.split("?", 1)[0]) or SKIP_PATH.search(c):
                continue
            seen.add(c)
            nxt.append(c)
        nxt.sort(key=_priority)
        for c in nxt:
            queue.append((c, depth + 1))
    return res
