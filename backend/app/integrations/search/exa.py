"""Exa search (POST https://api.exa.ai/search)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.ports.search_provider import SearchHit
from app.integrations.search.base import HTTPSearchProvider, SearchKind, parse_date

EXA_URL = "https://api.exa.ai/search"


class ExaSearchProvider(HTTPSearchProvider):
    name = "exa"
    cost_per_query_usd = 0.006   # search + short text contents

    async def _search(self, query: str, *, kind: SearchKind, recency_days: int | None, max_results: int,
                      domains_allow: list[str] | None, domains_deny: list[str] | None) -> list[SearchHit]:
        body: dict[str, Any] = {"query": query, "numResults": max(1, min(25, max_results)), "type": "auto",
                                "contents": {"text": {"maxCharacters": 1200}}}
        if kind == "news":
            body["category"] = "news"
        if recency_days:
            body["startPublishedDate"] = (datetime.now(UTC) - timedelta(days=recency_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if domains_allow:
            body["includeDomains"] = domains_allow[:20]
        if domains_deny:
            body["excludeDomains"] = domains_deny[:20]
        resp = await self.client.post(EXA_URL, json=body, retry=True,
                                      headers={"x-api-key": self.api_key, "Content-Type": "application/json"})
        data = resp.json()
        hits = []
        for r in data.get("results", []) or []:
            text = r.get("text") or ""
            hits.append(SearchHit(url=r.get("url", ""), title=r.get("title") or "", snippet=text[:600],
                                  published_at=parse_date(r.get("publishedDate")), content=text or None))
        return hits
