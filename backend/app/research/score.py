"""Credibility, relevance and final ranking (doc 07 §7.4–7.5). Deterministic and explainable: every score returns its
components so the UI can answer "why 0.82"."""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from app.research.domain_reputation import domain_prior
from app.research.text import sentences, term_set, word_count

T = TypeVar("T")

CRED_WEIGHTS = {"domain_prior": 0.35, "author_present": 0.15, "date_present": 0.15, "corroboration": 0.15,
                "https_and_no_spam": 0.10, "content_quality": 0.10}
RANK_WEIGHTS = {"relevance": 0.55, "credibility": 0.30, "recency": 0.15}
MAX_PER_DOMAIN_TOP = 3
DIVERSITY_WINDOW = 20
_SPAM_RE = re.compile(r"(!!!|\$\$\$|100% free|act now|limited time offer|click here|buy now|casino|viagra|crypto giveaway|"
                      r"make money fast|work from home and earn)", re.I)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class ScoredSource:
    key: Any
    domain: str
    relevance: float
    credibility: float
    recency: float
    final: float = 0.0
    components: dict[str, Any] = field(default_factory=dict)


def recency_decay(published_at: datetime | None, *, now: datetime | None = None, half_life_days: float = 30.0,
                  unknown: float = 0.3) -> float:
    """1.0 for today, 0.5 after one half-life; ``unknown`` when the date is missing."""
    if published_at is None:
        return unknown
    now = now or datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - published_at).total_seconds() / 86400)
    return clamp(math.pow(0.5, age_days / half_life_days))


def content_quality(text: str, *, boilerplate_ratio: float | None = None) -> float:
    """Length ≥ 300 words, readable structure (paragraphs, sentence length) and low boilerplate."""
    wc = word_count(text)
    length = clamp(wc / 300.0)
    paras = [p for p in re.split(r"\n\s*\n|\n", text or "") if len(p.split()) >= 8]
    structure = clamp(len(paras) / 4.0)
    sents = sentences(text)
    if sents:
        avg = sum(len(s.split()) for s in sents) / len(sents)
        readability = 1.0 if 8 <= avg <= 35 else 0.5
    else:
        readability = 0.0
    boiler = 1.0 - clamp(boilerplate_ratio) if boilerplate_ratio is not None else 0.8
    return round(clamp(0.5 * length + 0.2 * structure + 0.15 * readability + 0.15 * boiler), 4)


def spam_free(url: str, text: str, *, injection_flag: bool = False) -> float:
    https = 1.0 if url.lower().startswith("https://") else 0.0
    spam_hits = len(_SPAM_RE.findall(text or ""))
    clean = 0.0 if injection_flag else clamp(1.0 - 0.25 * spam_hits)
    return round(0.5 * https + 0.5 * clean, 4)


def corroboration(own: set[str], others: Sequence[set[str]], *, min_shared: int = 2) -> float:
    """Fraction of the run's other sources sharing ≥ ``min_shared`` named entities/claims with this one."""
    if not others:
        return 0.0
    own_l = {o.lower() for o in own}
    hits = sum(1 for o in others if len(own_l & {x.lower() for x in o}) >= min_shared)
    return round(hits / len(others), 4)


def credibility(*, url: str, domain: str, author: str | None, published_at: datetime | None, text: str,
                corroboration_score: float = 0.0, injection_flag: bool = False, boilerplate_ratio: float | None = None,
                domain_overrides: Mapping[str, float] | None = None) -> tuple[float, dict[str, Any]]:
    comps = {
        "domain_prior": domain_prior(domain or url, domain_overrides),
        "author_present": 1.0 if (author or "").strip() else 0.0,
        "date_present": 1.0 if published_at else 0.0,
        "corroboration": clamp(corroboration_score),
        "https_and_no_spam": spam_free(url, text, injection_flag=injection_flag),
        "content_quality": content_quality(text, boilerplate_ratio=boilerplate_ratio),
    }
    score = sum(CRED_WEIGHTS[k] * float(v) for k, v in comps.items())
    if injection_flag:
        score *= 0.8
    score = round(clamp(score), 3)
    return score, {**comps, "weights": CRED_WEIGHTS, "injection_penalty": injection_flag, "score": score}


def keyword_overlap(query_terms: set[str], *, title: str = "", body_terms: set[str] | None = None,
                    keywords: Iterable[str] = ()) -> float:
    """Share of query terms present in the document (title hits count 1.0, body/keyword hits 0.7)."""
    if not query_terms:
        return 0.0
    title_terms = term_set(title)
    kw_terms: set[str] = set()
    for k in keywords:
        kw_terms |= term_set(k)
    body = (body_terms or set()) | kw_terms
    total = 0.0
    for q in query_terms:
        if q in title_terms:
            total += 1.0
        elif q in body or any(b.startswith(q) or q.startswith(b) for b in body if len(b) > 4 and len(q) > 4):
            total += 0.7
    return round(clamp(total / len(query_terms)), 4)


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def relevance(query: str, *, title: str, text: str, keywords: Iterable[str] = (), published_at: datetime | None = None,
              embedding_similarity: float | None = None, pillar_terms: set[str] | None = None,
              now: datetime | None = None) -> tuple[float, dict[str, Any]]:
    """Relevance = keyword overlap + recency (+ embedding cosine when available, + brand-pillar overlap when given)."""
    q_terms = term_set(query)
    body_terms = term_set(text[:20000])
    overlap = keyword_overlap(q_terms, title=title, body_terms=body_terms, keywords=keywords)
    rec = recency_decay(published_at, now=now)
    pillar = None
    if pillar_terms:
        pillar = round(len(pillar_terms & (body_terms | term_set(title))) / max(1, min(len(pillar_terms), 10)), 4)
        pillar = clamp(pillar)
    if embedding_similarity is not None:
        emb = clamp(embedding_similarity)
        weights = {"embedding": 0.5, "keyword_overlap": 0.35, "recency": 0.15}
        parts = {"embedding": emb, "keyword_overlap": overlap, "recency": rec}
    else:
        weights = {"keyword_overlap": 0.8, "recency": 0.2}
        parts = {"keyword_overlap": overlap, "recency": rec}
    score = sum(weights[k] * parts[k] for k in weights)
    if pillar is not None:
        score = 0.9 * score + 0.1 * pillar
        parts["pillar_overlap"] = pillar
    score = round(clamp(score), 3)
    return score, {**parts, "weights": weights, "score": score}


def final_score(relevance_score: float, credibility_score: float, recency: float) -> float:
    return round(RANK_WEIGHTS["relevance"] * relevance_score + RANK_WEIGHTS["credibility"] * credibility_score
                 + RANK_WEIGHTS["recency"] * recency, 4)


def rank_with_diversity[T](items: Sequence[T], *, score: Callable[[T], float], domain: Callable[[T], str],
                        max_per_domain: int = MAX_PER_DOMAIN_TOP, window: int = DIVERSITY_WINDOW) -> list[T]:
    """Sort by score desc while allowing at most ``max_per_domain`` items per domain inside the first ``window``
    positions; overflow items are not dropped, they move below the window (still in score order)."""
    ordered = sorted(items, key=lambda i: -score(i))
    top: list[T] = []
    overflow: list[T] = []
    per_domain: dict[str, int] = {}
    for it in ordered:
        d = domain(it)
        if len(top) < window and per_domain.get(d, 0) < max_per_domain:
            top.append(it)
            per_domain[d] = per_domain.get(d, 0) + 1
        else:
            overflow.append(it)
    return top + overflow
