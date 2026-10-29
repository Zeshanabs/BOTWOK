"""News/mentions collector (class C, search-engine data): news-kind search about a competitor, stored as research sources
linked via ``research_sources.competitor_id`` (snippet-level; pages are fetched later only if a research run needs them)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.search.registry import search_detailed
from app.models.competitor import Competitor
from app.research.dedupe import content_hash, simhash64, to_signed64
from app.research.enrich import heuristic_enrichment
from app.research.injection import classify
from app.research.score import credibility
from app.research.store import SourceData, format_citation, upsert_source
from app.research.urls import domain_of, matches_domain, safe_canonicalize


async def collect_news(db: AsyncSession, competitor: Competitor, *, providers: list[Any] | None = None,
                       recency_days: int = 30, max_results: int = 10) -> dict[str, Any]:
    own = [domain_of(competitor.website)] if competitor.website else []
    query = f"\"{competitor.name}\""
    out = await search_detailed(query, "news", providers=providers, db=None if providers else db,
                                workspace_id=competitor.workspace_id, recency_days=recency_days, max_results=max_results,
                                domains_deny=own or None)
    new = 0
    stored: list[str] = []
    for h in out.hits:
        canon = safe_canonicalize(h.url)
        if not canon or (own and matches_domain(canon, own)):
            continue
        text = f"{h.title}\n\n{h.content or h.snippet or ''}".strip()
        report = classify(text)
        enr = heuristic_enrichment(report.sanitized_text, url=canon, title=h.title)
        dom = domain_of(canon)
        cred, comps = credibility(url=canon, domain=dom, author=None, published_at=h.published_at,
                                  text=report.sanitized_text, injection_flag=report.flagged)
        src, created = await upsert_source(db, competitor.workspace_id, SourceData(
            canonical_url=canon, domain=dom, final_url=h.url, title=report.sanitized_text.split("\n", 1)[0][:500] or None,
            source_kind="news", published_at=h.published_at, summary=enr.summary, keywords=enr.keywords, topics=enr.topics,
            entities={**enr.entities_json(), "injection": report.to_dict(), "provider": h.provider},
            credibility_score=cred, credibility_components=comps,
            citation=format_citation(h.title, dom, canon, None, h.published_at), content_hash=content_hash(text),
            simhash=to_signed64(simhash64(text)), word_count=len(text.split()), injection_flag=report.flagged,
            fetch_status="not_fetched", competitor_id=competitor.id))
        new += int(created)
        stored.append(str(src.id))
    return {"query": query, "hits": len(out.hits), "new": new, "source_ids": stored, "provider": out.provider,
            "degraded": out.degraded, "cost_usd": out.cost_usd}
