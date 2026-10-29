"""Exact + near-duplicate detection (pipeline stage ⑥).

* exact: sha256 of normalized text (NFKC, lowercase, punctuation-insensitive whitespace collapse)
* near: 64-bit SimHash over word 3-shingles, Hamming distance ≤ 3
* ``<link rel=canonical>`` is honored when it points at the same site (cross-site canonicals are ignored so a hostile page
  cannot claim another site's identity)
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.research.urls import safe_canonicalize, same_site

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_MASK64 = (1 << 64) - 1
NEAR_DUP_HAMMING = 3


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(_TOKEN_RE.findall(t))


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def simhash64(text: str, *, shingle: int = 3) -> int:
    """Unsigned 64-bit SimHash of word shingles (use ``to_signed64`` before storing in a Postgres bigint)."""
    tokens = normalize_text(text).split()
    if not tokens:
        return 0
    if len(tokens) < shingle:
        feats = [" ".join(tokens)]
    else:
        feats = [" ".join(tokens[i:i + shingle]) for i in range(len(tokens) - shingle + 1)]
    weights: dict[str, int] = {}
    for f in feats:
        weights[f] = weights.get(f, 0) + 1
    v = [0] * 64
    for f, w in weights.items():
        h = _h64(f)
        for bit in range(64):
            v[bit] += w if (h >> bit) & 1 else -w
    out = 0
    for bit in range(64):
        if v[bit] > 0:
            out |= 1 << bit
    return out


def to_signed64(v: int) -> int:
    v &= _MASK64
    return v - (1 << 64) if v >= (1 << 63) else v


def to_unsigned64(v: int) -> int:
    return v & _MASK64


def hamming(a: int, b: int) -> int:
    return bin(to_unsigned64(a) ^ to_unsigned64(b)).count("1")


def is_near_duplicate(a: int, b: int, threshold: int = NEAR_DUP_HAMMING) -> bool:
    return hamming(a, b) <= threshold


def canonical_from_html(html: str, page_url: str) -> str | None:
    """Return the page's declared canonical URL if it is same-site and well-formed."""
    if not html:
        return None
    try:
        from app.integrations.extract.readability_fallback import _parser
        tree = _parser(html[:500_000])
        href = None
        for node in tree.css("link[rel]"):
            rels = (node.attributes.get("rel") or "").lower().split()
            if "canonical" in rels:
                href = node.attributes.get("href")
                break
    except Exception:  # selectolax missing or unparseable markup
        m = re.search(r"<link[^>]+rel=[\"']?canonical[\"']?[^>]*href=[\"']([^\"']+)", html[:500_000], re.I)
        href = m.group(1) if m else None
    if not href:
        return None
    from urllib.parse import urljoin
    canon = safe_canonicalize(urljoin(page_url, href.strip()))
    if not canon or not same_site(canon, page_url):
        return None
    return canon


@dataclass
class DedupeItem:
    key: Any
    text: str
    credibility: float = 0.5
    content_hash: str = ""
    simhash: int = 0


@dataclass
class DedupeResult:
    kept: list[DedupeItem] = field(default_factory=list)
    exact_duplicates: dict[Any, Any] = field(default_factory=dict)   # dropped key → kept key
    near_duplicates: dict[Any, Any] = field(default_factory=dict)    # linked key → kept key


def dedupe(items: Iterable[DedupeItem], threshold: int = NEAR_DUP_HAMMING) -> DedupeResult:
    """Exact duplicates are dropped; near-duplicates keep the highest-credibility member and link the rest to it."""
    res = DedupeResult()
    by_hash: dict[str, DedupeItem] = {}
    ordered = sorted(items, key=lambda i: -i.credibility)
    for it in ordered:
        if not normalize_text(it.text):  # nothing to compare (e.g. snippet-only rows)
            res.kept.append(it)
            continue
        if not it.content_hash:
            it.content_hash = content_hash(it.text)
        if not it.simhash:
            it.simhash = simhash64(it.text)
        if it.content_hash in by_hash:
            res.exact_duplicates[it.key] = by_hash[it.content_hash].key
            continue
        winner = next((k for k in res.kept if is_near_duplicate(k.simhash, it.simhash, threshold)), None)
        if winner is not None:
            res.near_duplicates[it.key] = winner.key
            continue
        by_hash[it.content_hash] = it
        res.kept.append(it)
    return res
