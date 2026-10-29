"""``rss.read`` — read an RSS/Atom feed through SafeFetcher (EXTERNAL_READ, untrusted output)."""
from __future__ import annotations

from app.core.resilience import ResilienceError
from app.research.toolkit import SideEffect, ToolContext, tool


@tool("rss.read", side_effect=SideEffect.EXTERNAL_READ, timeout_s=40, idempotent=True, untrusted_output=True,
      rate_limit_per_run=20)
async def rss_read(ctx: ToolContext, url: str, limit: int = 20) -> dict:
    """Read an RSS or Atom feed and return its latest entries {title, url, published_at, summary}."""
    from app.research.feeds import read_feed
    limit = max(1, min(50, int(limit)))
    try:
        res = await read_feed(url)
    except ResilienceError as e:
        return {"error": e.message, "category": e.category, "url": url}
    return {"url": url, "title": res.title, "entries": [
        {"title": e.title[:300], "url": e.url, "published_at": e.published_at.isoformat() if e.published_at else None,
         "summary": e.summary[:500], "author": e.author} for e in res.entries[:limit]]}
