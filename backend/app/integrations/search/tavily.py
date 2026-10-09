"""Tavily search (POST https://api.tavily.com/search)."""
from __future__ import annotations

from typing import Any

from app.core.ports.search_provider import SearchHit
from app.integrations.search.base import HTTPSearchProvider, SearchKind, parse_date, recency_bucket

TAVILY_URL = "https://api.tavily.com/search"


class TavilySearchProvider(HTTPSearchProvider):
    name = "tavily"
    cost_per_query_usd = 0.008   # 1 credit (basic depth)

    async def _search(self, query: str, *, kind: SearchKind, recency_days: int | None, max_results: int,
                      domains_allow: list[str] | None, domains_deny: list[str] | None) -> list[SearchHit]:
        body: dict[str, Any] = {"query": query, "topic": "news" if kind == "news" else "general",
                                "search_depth": "basic", "max_results": max(1, min(20, max_results)),
                                "include_answer": False, "include_raw_content": False, "include_images": False}
        if recency_days:
            if kind == "news":
                body["days"] = int(recency_days)
            else:
                body["time_range"] = recency_bucket(recency_days)
        if domains_allow:
            body["include_domains"] = domains_allow[:20]
        if domains_deny:
            body["exclude_domains"] = domains_deny[:20]
        resp = await self.client.post(TAVILY_URL, json=body, retry=True,
                                      headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        data = resp.json()
        hits = []
        for r in data.get("results", []) or []:
            hits.append(SearchHit(url=r.get("url", ""), title=r.get("title") or "", snippet=(r.get("content") or "")[:600],
                                  published_at=parse_date(r.get("published_date")), content=r.get("raw_content") or None))
        return hits
