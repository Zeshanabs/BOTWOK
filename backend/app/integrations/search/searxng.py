"""SearXNG (self-hosted metasearch; zero-key fallback): ``{base}/search?format=json``."""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.ports.search_provider import SearchHit
from app.integrations.search.base import (
    HTTPSearchProvider,
    SearchKind,
    parse_date,
    recency_bucket,
    with_site_operators,
)


class SearxngSearchProvider(HTTPSearchProvider):
    name = "searxng"
    cost_per_query_usd = 0.0
    requires_key = False

    def __init__(self, base_url: str | None = None, **kw: Any):
        super().__init__(api_key=None, base_url=(base_url or settings.searxng_base_url or "").rstrip("/"), **kw)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def _search(self, query: str, *, kind: SearchKind, recency_days: int | None, max_results: int,
                      domains_allow: list[str] | None, domains_deny: list[str] | None) -> list[SearchHit]:
        params: dict[str, Any] = {"q": with_site_operators(query, domains_allow, domains_deny), "format": "json",
                                  "categories": "news" if kind == "news" else "general", "pageno": 1, "safesearch": 1}
        bucket = recency_bucket(recency_days)
        if bucket:
            params["time_range"] = bucket
        # A local SearXNG that is down should fail fast: one attempt, no long retries.
        resp = await self.client.get(f"{self.base_url}/search", params=params, attempts=1,
                                     headers={"Accept": "application/json"})
        data = resp.json()
        hits = []
        for r in data.get("results", []) or []:
            hits.append(SearchHit(url=r.get("url", ""), title=r.get("title") or "", snippet=(r.get("content") or "")[:600],
                                  published_at=parse_date(r.get("publishedDate") or r.get("pubdate"))))
        return hits
