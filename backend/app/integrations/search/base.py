"""Shared machinery for HTTP search providers (SearchProvider port)."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from dateutil import parser as dateparser

from app.core.ports.search_provider import SearchHit
from app.core.resilience import HostLimiterRegistry, ResilienceError, ResilientClient

SearchKind = Literal["web", "news"]

# Search APIs tolerate more than 1 req/s; they have their own quotas.
_API_LIMITERS = HostLimiterRegistry(rate_per_s=5.0, concurrency=4)
_REL_AGE_RE = re.compile(r"(\d+)\s*(minute|min|hour|hr|day|week|month|year)s?\s+ago", re.I)


class SearchProviderError(Exception):
    def __init__(self, provider: str, message: str, category: str = "transient"):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.category = category


def parse_date(value: Any) -> datetime | None:
    """ISO strings, RFC 2822, epoch seconds, or relative ages ("3 days ago")."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    m = _REL_AGE_RE.search(s)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {"minute": timedelta(minutes=n), "min": timedelta(minutes=n), "hour": timedelta(hours=n),
                 "hr": timedelta(hours=n), "day": timedelta(days=n), "week": timedelta(weeks=n),
                 "month": timedelta(days=30 * n), "year": timedelta(days=365 * n)}[unit]
        return datetime.now(UTC) - delta
    try:
        dt = dateparser.parse(s)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def recency_bucket(recency_days: int | None) -> str | None:
    """Map a day window onto the coarse day/week/month/year buckets most providers accept."""
    if not recency_days:
        return None
    if recency_days <= 1:
        return "day"
    if recency_days <= 7:
        return "week"
    if recency_days <= 31:
        return "month"
    return "year"


def with_site_operators(query: str, domains_allow: list[str] | None, domains_deny: list[str] | None) -> str:
    q = query
    if domains_allow:
        allow = " OR ".join(f"site:{d}" for d in domains_allow[:6])
        q = f"{q} ({allow})" if len(domains_allow) > 1 else f"{q} site:{domains_allow[0]}"
    for d in (domains_deny or [])[:6]:
        q = f"{q} -site:{d}"
    return q


class HTTPSearchProvider:
    """Base class: subclasses implement ``_search``; ``search`` normalizes errors and ranks."""

    name: str = "base"
    cost_per_query_usd: float = 0.0
    requires_key: bool = True

    def __init__(self, api_key: str | None = None, *, client: ResilientClient | None = None, base_url: str | None = None):
        self.api_key = api_key or ""
        self.base_url = base_url
        self._client = client

    @property
    def client(self) -> ResilientClient:
        if self._client is None:
            self._client = ResilientClient(limiters=_API_LIMITERS, attempts=3, read_timeout=20.0,
                                           headers={"User-Agent": "Botwok/0.1 (+https://botwok.dev/bot)"})
        return self._client

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or not self.requires_key

    async def search(self, query: str, *, kind: SearchKind = "web", recency_days: int | None = None, max_results: int = 10,
                     domains_allow: list[str] | None = None, domains_deny: list[str] | None = None) -> list[SearchHit]:
        if not self.configured:
            raise SearchProviderError(self.name, "not configured", "auth")
        try:
            hits = await self._search(query, kind=kind, recency_days=recency_days, max_results=max_results,
                                      domains_allow=domains_allow, domains_deny=domains_deny)
        except ResilienceError as e:
            raise SearchProviderError(self.name, e.message, e.category) from e
        except (ValueError, KeyError, TypeError) as e:  # malformed JSON / unexpected shape
            raise SearchProviderError(self.name, f"bad response: {e}", "permanent") from e
        out: list[SearchHit] = []
        for i, h in enumerate(hits[:max_results]):
            if not h.url or not h.url.startswith(("http://", "https://")):
                continue
            h.provider = self.name
            h.rank = i + 1
            out.append(h)
        return out

    async def _search(self, query: str, *, kind: SearchKind, recency_days: int | None, max_results: int,
                      domains_allow: list[str] | None, domains_deny: list[str] | None) -> list[SearchHit]:
        raise NotImplementedError

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
