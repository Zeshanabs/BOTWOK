"""Brave Search API (web + news)."""
from __future__ import annotations

from typing import Any

from app.core.ports.search_provider import SearchHit
from app.integrations.search.base import HTTPSearchProvider, SearchKind, parse_date, with_site_operators

BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"


def _freshness(recency_days: int | None) -> str | None:
    if not recency_days:
        return None
    if recency_days <= 1:
        return "pd"
    if recency_days <= 7:
        return "pw"
    if recency_days <= 31:
        return "pm"
    return "py"


class BraveSearchProvider(HTTPSearchProvider):
    name = "brave"
    cost_per_query_usd = 0.005

    async def _search(self, query: str, *, kind: SearchKind, recency_days: int | None, max_results: int,
                      domains_allow: list[str] | None, domains_deny: list[str] | None) -> list[SearchHit]:
        params: dict[str, Any] = {"q": with_site_operators(query, domains_allow, domains_deny)[:400],
                                  "count": max(1, min(20, max_results)), "safesearch": "moderate"}
        fresh = _freshness(recency_days)
        if fresh:
            params["freshness"] = fresh
        url = BRAVE_NEWS_URL if kind == "news" else BRAVE_WEB_URL
        resp = await self.client.get(url, params=params, headers={"X-Subscription-Token": self.api_key,
                                                                  "Accept": "application/json"})
        data = resp.json()
        rows = (data.get("results") if kind == "news" else (data.get("web") or {}).get("results")) or []
        hits = []
        for r in rows:
            hits.append(SearchHit(url=r.get("url", ""), title=r.get("title") or "", snippet=(r.get("description") or "")[:600],
                                  published_at=parse_date(r.get("page_age") or r.get("age"))))
        return hits
