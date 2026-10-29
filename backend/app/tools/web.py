"""Web tools for agents: ``web.search``, ``web.fetch``, ``web.crawl`` (EXTERNAL_READ, untrusted output).

Every fetch goes through SafeFetcher (SSRF guard, robots.txt, size/type caps); fetched text is persisted as an untrusted
research source and returned truncated — agents read more with ``research.read_source``.
"""
from __future__ import annotations

from typing import Literal

from app.core.resilience import ResilienceError
from app.research.injection import sanitize
from app.research.toolkit import SideEffect, ToolContext, ctx_actor, ctx_workspace, tool, tool_db

FETCH_TEXT_MAX = 6000


@tool("web.search", side_effect=SideEffect.EXTERNAL_READ, timeout_s=45, idempotent=True, untrusted_output=True,
      rate_limit_per_run=40)
async def web_search(ctx: ToolContext, query: str, kind: Literal["web", "news"] = "web", recency_days: int | None = None,
                     max_results: int = 10) -> dict:
    """Search the web or news. Returns ranked hits {url, title, snippet, published_at, provider}; snippets are untrusted."""
    from app.integrations.search.registry import search_detailed
    ws = ctx_workspace(ctx)
    max_results = max(1, min(20, int(max_results)))
    async with tool_db(ctx) as db:
        out = await search_detailed(query[:400], kind, db=db, workspace_id=ws, recency_days=recency_days,
                                    max_results=max_results)
    return {
        "query": query, "kind": kind, "provider": out.provider, "cached": out.cached, "degraded": out.degraded,
        "hits": [{"url": h.url, "title": sanitize(h.title)[:300], "snippet": sanitize(h.snippet)[:500],
                  "published_at": h.published_at.isoformat() if h.published_at else None, "provider": h.provider,
                  "rank": h.rank} for h in out.hits],
        "note": None if out.hits else "no results (search providers unavailable or nothing found)",
    }


@tool("web.fetch", side_effect=SideEffect.EXTERNAL_READ, timeout_s=60, idempotent=True, untrusted_output=True,
      rate_limit_per_run=30)
async def web_fetch(ctx: ToolContext, url: str) -> dict:
    """Fetch one public web page or PDF, extract its text and save it as a research source. Returns the source id, title,
    a snippet and up to 6,000 characters of text (use research.read_source for more)."""
    from app.research.pipeline import PipelineContext, ingest_url
    ws = ctx_workspace(ctx)
    try:
        async with tool_db(ctx) as db:
            c = await ingest_url(db, ws, url, ctx=PipelineContext(actor=ctx_actor(ctx), max_llm_enrich=1))
            src = c.source
            assert src is not None
            text = c.text or ""
            return {"source_id": str(src.id), "title": src.title, "url": src.canonical_url, "domain": src.domain,
                    "published_at": src.published_at.isoformat() if src.published_at else None,
                    "snippet": (src.summary or "")[:600], "text": text[:FETCH_TEXT_MAX], "truncated": len(text) > FETCH_TEXT_MAX,
                    "credibility": float(src.credibility_score) if src.credibility_score is not None else None,
                    "injection_flag": src.injection_flag, "reused": c.reused, "fetch_status": src.fetch_status}
    except ResilienceError as e:
        return {"error": e.message, "category": e.category, "code": e.code, "url": url}


@tool("web.crawl", side_effect=SideEffect.EXTERNAL_READ, timeout_s=180, idempotent=True, untrusted_output=True,
      rate_limit_per_run=5)
async def web_crawl(ctx: ToolContext, url: str, max_pages: int = 10, depth: int = 1) -> dict:
    """Crawl a site starting at ``url`` (same site only, robots.txt honored; max 20 pages, depth ≤ 2). Pages are saved as
    research sources; returns their ids, titles and snippets plus discovered RSS feeds."""
    from app.core.safe_fetch import get_fetcher
    from app.research.crawl import crawl_site
    from app.research.pipeline import Candidate, PipelineContext, _analyze, _persist
    from app.research.urls import domain_of
    ws = ctx_workspace(ctx)
    max_pages = max(1, min(20, int(max_pages)))
    depth = max(0, min(2, int(depth)))
    try:
        fetcher = get_fetcher()
        await fetcher.validate_url(url)
        cr = await crawl_site(fetcher, url, max_pages=max_pages, max_depth=depth)
    except ResilienceError as e:
        return {"error": e.message, "category": e.category, "url": url}
    pctx = PipelineContext(actor=ctx_actor(ctx), use_llm=False)
    pages = []
    async with tool_db(ctx) as db:
        from app.research.store import get_source_by_url
        cands = []
        for p in cr.pages:
            c = Candidate(url=p.final_url, canonical_url=p.canonical_url, domain=domain_of(p.canonical_url), title=p.title,
                          author=p.author, published_at=p.published_at, language=p.language, text=p.text,
                          final_url=p.final_url, extractor="crawl", is_pdf=p.is_pdf, fetch_status="ok")
            c.existing = await get_source_by_url(db, ws, c.canonical_url)
            cands.append(c)
        kept = await _analyze(cands, query=domain_of(url), ctx=pctx, llm=None, embedder=None, pillar_terms=set(),
                              domain_overrides={})
        for c in kept:
            if c.duplicate_of is not None:
                continue
            src, changed = await _persist(db, c, workspace_id=ws, embedder=None, ctx=pctx)
            if changed:
                from app.core.events import emit
                await emit(db, "SOURCE_SAVED", {"source_id": str(src.id), "injection_flag": src.injection_flag},
                           workspace_id=ws, actor=ctx_actor(ctx))
            pages.append({"source_id": str(src.id), "url": src.canonical_url, "title": src.title,
                          "snippet": (src.summary or "")[:300], "injection_flag": src.injection_flag})
        await db.flush()
    return {"start_url": url, "pages": pages, "feeds": cr.feeds, "skipped_by_robots": cr.skipped_robots,
            "errors": cr.errors[:10], "fetched": cr.fetched}
