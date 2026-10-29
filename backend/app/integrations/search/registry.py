"""Search provider registry + fallback chain + Redis result cache (doc 07 §7.2 ②, doc 28 "Search failure").

Order: configured keyed providers (Tavily → Brave → Exa; workspace keys from provider_secrets first, then env settings),
then SearXNG as the zero-key fallback. ``search_with_fallback`` tries providers in order until one returns hits, caches
results for 24 h (news: 1 h) keyed by normalized query + provider + kind, and never raises: when everything is down it
returns ``[]`` and logs a warning.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.ports.search_provider import SearchHit
from app.integrations.search.base import HTTPSearchProvider, SearchKind, SearchProviderError, parse_date
from app.integrations.search.brave import BraveSearchProvider
from app.integrations.search.exa import ExaSearchProvider
from app.integrations.search.searxng import SearxngSearchProvider
from app.integrations.search.tavily import TavilySearchProvider

log = get_logger("search")

PROVIDER_CLASSES: dict[str, type[HTTPSearchProvider]] = {
    "tavily": TavilySearchProvider, "brave": BraveSearchProvider, "exa": ExaSearchProvider,
}
KEYED_ORDER = ("tavily", "brave", "exa")
CACHE_TTL_S = {"web": 24 * 3600, "news": 3600}
CACHE_PREFIX = "search:v1:"


async def _workspace_key(db: AsyncSession | None, workspace_id: UUID | None, provider: str) -> str | None:
    if db is None or workspace_id is None:
        return None
    try:
        from app.services import ai_settings_service as svc  # type: ignore[attr-defined]
    except ImportError:
        return None
    try:
        fn = getattr(svc, "get_provider_key", None)
        if fn is None and hasattr(svc, "AISettingsService"):
            fn = svc.AISettingsService().get_provider_key
        if fn is None:
            return None
        res = fn(db, workspace_id, provider)
        if inspect.isawaitable(res):
            res = await res
        return res or None
    except Exception as e:  # missing secret, decryption error, schema not ready
        log.debug("search.workspace_key_unavailable", provider=provider, error=str(e)[:200])
        return None


def _env_key(provider: str) -> str:
    return {"tavily": settings.tavily_api_key, "brave": settings.brave_api_key, "exa": settings.exa_api_key}.get(provider, "")


async def get_search_providers(db: AsyncSession | None = None, workspace_id: UUID | None = None, *,
                               include_searxng: bool = True) -> list[HTTPSearchProvider]:
    providers: list[HTTPSearchProvider] = []
    for name in KEYED_ORDER:
        key = await _workspace_key(db, workspace_id, name) or _env_key(name)
        if key:
            providers.append(PROVIDER_CLASSES[name](api_key=key))
    if include_searxng and settings.searxng_base_url:
        providers.append(SearxngSearchProvider())
    return providers


def normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def cache_key(query: str, provider: str, kind: str, *, recency_days: int | None = None, max_results: int = 10,
              domains_allow: list[str] | None = None, domains_deny: list[str] | None = None) -> str:
    raw = json.dumps([normalize_query(query), provider, kind, recency_days, max_results, sorted(domains_allow or []),
                      sorted(domains_deny or [])])
    return CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:40]


def _hit_to_json(h: SearchHit) -> dict[str, Any]:
    d = asdict(h)
    d["published_at"] = h.published_at.isoformat() if h.published_at else None
    if d.get("content"):
        d["content"] = d["content"][:4000]
    return d


def _hit_from_json(d: dict[str, Any]) -> SearchHit:
    return SearchHit(url=d.get("url", ""), title=d.get("title", ""), snippet=d.get("snippet", ""),
                     published_at=parse_date(d.get("published_at")), provider=d.get("provider", ""), rank=d.get("rank", 0),
                     content=d.get("content"))


async def _cache_get(key: str) -> list[SearchHit] | None:
    try:
        from app.core.redis import get_redis
        raw = await get_redis().get(key)
    except Exception:  # Redis down → no cache
        return None
    if not raw:
        return None
    try:
        return [_hit_from_json(d) for d in json.loads(raw)]
    except (ValueError, TypeError):
        return None


async def _cache_set(key: str, hits: list[SearchHit], ttl: int) -> None:
    try:
        from app.core.redis import get_redis
        await get_redis().set(key, json.dumps([_hit_to_json(h) for h in hits]), ex=ttl)
    except Exception:
        return


@dataclass
class SearchOutcome:
    hits: list[SearchHit] = field(default_factory=list)
    provider: str | None = None
    cached: bool = False
    degraded: bool = False
    cost_usd: float = 0.0
    errors: list[dict[str, str]] = field(default_factory=list)
    at: datetime | None = None


async def search_detailed(query: str, kind: SearchKind = "web", *, providers: list[Any] | None = None,
                          db: AsyncSession | None = None, workspace_id: UUID | None = None, recency_days: int | None = None,
                          max_results: int = 10, domains_allow: list[str] | None = None,
                          domains_deny: list[str] | None = None, use_cache: bool = True,
                          max_providers: int = 3) -> SearchOutcome:
    if providers is None:
        providers = await get_search_providers(db, workspace_id)
    out = SearchOutcome()
    if not providers:
        log.warning("search.no_providers", query=query[:80])
        out.degraded = True
        return out
    tried = 0
    for idx, p in enumerate(providers):
        if tried >= max_providers:
            break
        name = getattr(p, "name", type(p).__name__)
        key = cache_key(query, name, kind, recency_days=recency_days, max_results=max_results,
                        domains_allow=domains_allow, domains_deny=domains_deny)
        if use_cache:
            cached = await _cache_get(key)
            if cached:
                out.hits, out.provider, out.cached = cached, name, True
                out.degraded = idx > 0
                return out
        tried += 1
        try:
            hits = await p.search(query, kind=kind, recency_days=recency_days, max_results=max_results,
                                  domains_allow=domains_allow, domains_deny=domains_deny)
        except SearchProviderError as e:
            out.errors.append({"provider": name, "error": str(e)[:300], "category": e.category})
            log.warning("search.provider_failed", provider=name, error=str(e)[:200])
            continue
        except Exception as e:  # never let one provider break research
            out.errors.append({"provider": name, "error": f"{type(e).__name__}: {e}"[:300], "category": "transient"})
            log.warning("search.provider_crashed", provider=name, error=str(e)[:200])
            continue
        out.cost_usd += float(getattr(p, "cost_per_query_usd", 0.0) or 0.0)
        if hits:
            out.hits, out.provider = hits, name
            out.degraded = idx > 0
            if use_cache:
                await _cache_set(key, hits, CACHE_TTL_S.get(kind, CACHE_TTL_S["web"]))
            return out
    out.degraded = True
    if out.errors:
        log.warning("search.all_failed", query=query[:80], errors=len(out.errors))
    return out


async def search_with_fallback(query: str, kind: SearchKind = "web", *, providers: list[Any] | None = None,
                               db: AsyncSession | None = None, workspace_id: UUID | None = None,
                               recency_days: int | None = None, max_results: int = 10,
                               domains_allow: list[str] | None = None, domains_deny: list[str] | None = None,
                               use_cache: bool = True) -> list[SearchHit]:
    """Try providers in order; return the first non-empty result list (cached). Never raises."""
    res = await search_detailed(query, kind, providers=providers, db=db, workspace_id=workspace_id,
                                recency_days=recency_days, max_results=max_results, domains_allow=domains_allow,
                                domains_deny=domains_deny, use_cache=use_cache)
    return res.hits
