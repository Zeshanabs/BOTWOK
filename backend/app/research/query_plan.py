"""Query planning (pipeline stage ①): 2–6 query variants per scope.

Cheap LLM when available; deterministic heuristics otherwise (original, quoted key phrase, "+ news", site: for competitor
domains, recency/intent variants).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.research.ai import CheapLLM
from app.research.text import STOPWORDS, words
from app.research.urls import domain_of

DEPTH_PRESETS: dict[str, dict[str, int]] = {
    # variants per scope, max hits fetched, crawl depth for competitor sites, max crawl pages
    "quick": {"variants": 2, "top_n": 8, "crawl_depth": 0, "crawl_pages": 0, "hits_per_query": 8},
    "standard": {"variants": 3, "top_n": 20, "crawl_depth": 1, "crawl_pages": 10, "hits_per_query": 10},
    "deep": {"variants": 6, "top_n": 50, "crawl_depth": 2, "crawl_pages": 30, "hits_per_query": 15},
}
SEARCH_SCOPES = ("web", "news", "competitor_sites")


@dataclass(frozen=True)
class QueryVariant:
    text: str
    kind: str          # web | news
    scope: str         # web | news | competitor_sites
    origin: str = "heuristic"


def preset(depth: str) -> dict[str, int]:
    return DEPTH_PRESETS.get(depth, DEPTH_PRESETS["standard"])


def key_phrase(query: str) -> str:
    """The longest run of consecutive non-stopword words (≥2 words), used for an exact-phrase variant."""
    ws = words(query)
    best: list[str] = []
    cur: list[str] = []
    for w in ws:
        if w.lower() in STOPWORDS or len(w) < 2:
            if len(cur) > len(best):
                best = cur
            cur = []
        else:
            cur.append(w)
    if len(cur) > len(best):
        best = cur
    return " ".join(best[:5]) if len(best) >= 2 else ""


def _strip_ops(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\b(site|inurl|intitle|filetype):\S+", "", q)).strip()


def heuristic_variants(query: str, scope: str, n: int, *, competitor_domains: list[str] | None = None,
                       recency_days: int | None = None) -> list[QueryVariant]:
    q = re.sub(r"\s+", " ", query).strip()
    base = _strip_ops(q) or q
    phrase = key_phrase(base)
    kind = "news" if scope == "news" else "web"
    cands: list[str] = []
    if scope == "competitor_sites":
        doms = [domain_of(d) for d in (competitor_domains or []) if d]
        for d in doms:
            cands.append(f"{base} site:{d}")
        for d in doms:
            cands.append(f"site:{d}")
            if phrase:
                cands.append(f"\"{phrase}\" site:{d}")
        if not doms:
            cands.append(base)
    elif scope == "news":
        cands += [base, f"{base} news"]
        if phrase:
            cands.append(f"\"{phrase}\"")
        cands += [f"{base} announcement", f"{base} report", f"{base} latest"]
    else:
        cands.append(base)
        if phrase and phrase.lower() != base.lower():
            cands.append(f"\"{phrase}\"")
        cands.append(f"{base} news")
        if recency_days and recency_days <= 31:
            cands.append(f"{base} this month")
        cands += [f"{base} statistics", f"{base} trends", f"{base} analysis", f"what is {base}" if len(base.split()) <= 4 else f"{base} guide"]
    seen: set[str] = set()
    out: list[QueryVariant] = []
    for c in cands:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(QueryVariant(text=c, kind=kind, scope=scope))
        if len(out) >= n:
            break
    return out


PLAN_PROMPT = (
    "You write web-search query variants for a research engine. Reply with one JSON object only: "
    "{\"variants\": [str]}. Rules: at most {n} variants; each under 12 words; keep the user's intent; vary angle "
    "(synonyms, exact phrase in quotes, entity names, data/statistics, recent developments); no explanations."
)


async def plan_queries(query: str, scopes: list[str], depth: str = "standard", *, competitor_domains: list[str] | None = None,
                       recency_days: int | None = None, llm: CheapLLM | None = None) -> list[QueryVariant]:
    n = max(2, min(6, preset(depth)["variants"]))
    out: list[QueryVariant] = []
    for scope in scopes:
        if scope not in SEARCH_SCOPES:
            continue
        heur = heuristic_variants(query, scope, n, competitor_domains=competitor_domains, recency_days=recency_days)
        if llm is not None and scope in ("web", "news"):
            data = await llm.complete_json(PLAN_PROMPT.replace("{n}", str(n)), f"Scope: {scope}\nQuestion: {query}",
                                           max_tokens=300)
            llm_vars = [v.strip() for v in (data or {}).get("variants", []) if isinstance(v, str) and 2 < len(v.strip()) < 200]
            if llm_vars:
                merged = [QueryVariant(text=query.strip(), kind=heur[0].kind, scope=scope)]
                seen = {query.strip().lower()}
                for v in llm_vars:
                    if v.lower() not in seen:
                        seen.add(v.lower())
                        merged.append(QueryVariant(text=v, kind=heur[0].kind, scope=scope, origin="llm"))
                for h in heur:  # top up with heuristics if the model returned too few
                    if len(merged) >= n:
                        break
                    if h.text.lower() not in seen:
                        seen.add(h.text.lower())
                        merged.append(h)
                heur = merged[:n]
        out.extend(heur[:n])
    return out
