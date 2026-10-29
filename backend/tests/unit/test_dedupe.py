"""Exact (sha256) and near-duplicate (64-bit SimHash, Hamming ≤ 3) detection, canonical link honoring."""
from __future__ import annotations

from app.research.dedupe import (
    DedupeItem,
    canonical_from_html,
    content_hash,
    dedupe,
    hamming,
    is_near_duplicate,
    simhash64,
    to_signed64,
    to_unsigned64,
)

ARTICLE = (
    "The city council approved a new budget on Tuesday that increases spending on public transit by 12 percent. "
    "Officials said the plan adds three bus routes, extends evening service on the light rail line, and funds a pilot "
    "program for free fares for students. Critics argued the plan relies on optimistic revenue forecasts and could "
    "require cuts elsewhere if sales tax receipts fall short. The mayor is expected to sign the measure next week, "
    "and the first new routes would begin operating in the spring after a public comment period closes in March. "
    "Transit advocates welcomed the vote and said ridership has recovered to about ninety percent of earlier levels."
)


def test_content_hash_normalizes_case_whitespace_punctuation() -> None:
    assert content_hash("Hello,   World!\n") == content_hash("hello world")
    assert content_hash("hello world") != content_hash("hello worlds")
    assert len(content_hash("x")) == 64


def test_simhash_near_duplicate_small_edit() -> None:
    a = simhash64(ARTICLE)
    b = simhash64(ARTICLE.replace("Tuesday", "Wednesday"))
    assert 0 <= a < 2 ** 64
    assert hamming(a, b) <= 3
    assert is_near_duplicate(a, b)


def test_simhash_different_documents_are_far() -> None:
    other = ("Researchers released a new open dataset of coral reef images collected over a decade across the Pacific, "
             "with annotations for bleaching events, species counts and water temperature readings from sensor buoys. "
             "The team hopes the data will help marine biologists train models to monitor reef health remotely.")
    assert hamming(simhash64(ARTICLE), simhash64(other)) > 3


def test_signed_roundtrip_for_bigint_storage() -> None:
    for v in (0, 1, 2 ** 63 - 1, 2 ** 63, 2 ** 64 - 1, simhash64(ARTICLE)):
        s = to_signed64(v)
        assert -(2 ** 63) <= s < 2 ** 63
        assert to_unsigned64(s) == v
    a = simhash64(ARTICLE)
    assert hamming(to_signed64(a), a) == 0


def test_dedupe_drops_exact_and_links_near_to_most_credible() -> None:
    items = [
        DedupeItem(key="a", text=ARTICLE, credibility=0.4),
        DedupeItem(key="b", text=ARTICLE.upper(), credibility=0.3),                       # exact (normalized) dup of a
        DedupeItem(key="c", text=ARTICLE.replace("Tuesday", "Monday"), credibility=0.9),   # near dup, more credible
        DedupeItem(key="d", text="A completely different story about gardening tomatoes in raised beds.", credibility=0.5),
        DedupeItem(key="e", text="", credibility=0.1),                                    # nothing to compare: kept
    ]
    res = dedupe(items)
    kept = {i.key for i in res.kept}
    assert "c" in kept and "d" in kept and "e" in kept
    assert res.near_duplicates.get("a") == "c"
    assert "b" in res.exact_duplicates or "b" in res.near_duplicates
    assert "a" not in kept and "b" not in kept


def test_canonical_link_same_site_only() -> None:
    html = '<html><head><link rel="canonical" href="/story/123?utm_source=x"></head><body></body></html>'
    assert canonical_from_html(html, "https://www.news.test/amp/story/123") == "https://www.news.test/story/123"
    hostile = '<link rel="canonical" href="https://victim.example/article">'
    assert canonical_from_html(hostile, "https://spam.test/copy") is None
    assert canonical_from_html("<p>no canonical</p>", "https://a.test/") is None
