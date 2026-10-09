"""Credibility (doc 07 §7.4), relevance, recency, ranking with domain diversity."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.research.domain_reputation import DEFAULT_PRIOR, domain_prior
from app.research.score import (
    CRED_WEIGHTS,
    corroboration,
    credibility,
    final_score,
    keyword_overlap,
    rank_with_diversity,
    recency_decay,
    relevance,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
LONG = ("Paragraph one about electric vehicle battery prices falling in 2026 according to analysts.\n\n" * 3 +
        " ".join(["Battery costs dropped again as lithium supply expanded and new factories opened."] * 40))


def test_weights_sum_to_one() -> None:
    assert sum(CRED_WEIGHTS.values()) == pytest.approx(1.0)


@pytest.mark.parametrize(("domain", "lo", "hi"), [
    ("www.cdc.gov", 0.85, 1.0), ("data.europa.eu", 0.85, 1.0), ("mit.edu", 0.8, 1.0), ("reuters.com", 0.9, 1.0),
    ("developers.facebook.com", 0.85, 1.0), ("ehow.com", 0.0, 0.3), ("ezinearticles.com", 0.0, 0.2),
    ("some-random-blog.net", DEFAULT_PRIOR, DEFAULT_PRIOR), ("news.bbc.co.uk", 0.85, 1.0), ("cheap-pills.click", 0.0, 0.3),
])
def test_domain_prior(domain: str, lo: float, hi: float) -> None:
    assert lo <= domain_prior(domain) <= hi


def test_domain_prior_workspace_override_wins() -> None:
    assert domain_prior("reuters.com", {"reuters.com": 0.1}) == 0.1
    assert domain_prior("https://blog.acme.io/x", {"acme.io": 0.95}) == 0.95


def test_credibility_formula_components() -> None:
    score, comps = credibility(url="https://www.reuters.com/x", domain="reuters.com", author="Jane Doe",
                               published_at=NOW, text=LONG, corroboration_score=0.5)
    expected = sum(CRED_WEIGHTS[k] * comps[k] for k in CRED_WEIGHTS)
    assert score == pytest.approx(round(expected, 3), abs=1e-3)
    assert comps["author_present"] == 1.0 and comps["date_present"] == 1.0 and comps["https_and_no_spam"] == 1.0
    weak, _ = credibility(url="http://ehow.com/x", domain="ehow.com", author=None, published_at=None, text="short")
    assert weak < score
    flagged, fcomps = credibility(url="https://www.reuters.com/x", domain="reuters.com", author="Jane Doe", published_at=NOW,
                                  text=LONG, corroboration_score=0.5, injection_flag=True)
    assert flagged < score and fcomps["injection_penalty"] is True


def test_recency_decay() -> None:
    assert recency_decay(NOW, now=NOW) == pytest.approx(1.0)
    assert recency_decay(NOW - timedelta(days=30), now=NOW) == pytest.approx(0.5, abs=1e-6)
    assert recency_decay(None, now=NOW) == 0.3
    assert recency_decay(NOW - timedelta(days=365), now=NOW) < 0.01


def test_relevance_and_overlap() -> None:
    assert keyword_overlap({"battery", "prices"}, title="Battery prices fall") == 1.0
    rel_hi, comps = relevance("electric vehicle battery prices", title="EV battery prices fall", text=LONG,
                              published_at=NOW, now=NOW)
    rel_lo, _ = relevance("electric vehicle battery prices", title="Gardening tips", text="Tomatoes need sun.",
                          published_at=NOW, now=NOW)
    assert rel_hi > rel_lo
    assert "embedding" not in comps
    rel_emb, ecomps = relevance("electric vehicle battery prices", title="EV battery prices fall", text=LONG,
                                published_at=NOW, embedding_similarity=0.9, now=NOW)
    assert ecomps["embedding"] == 0.9 and 0 <= rel_emb <= 1


def test_corroboration() -> None:
    own = {"Tesla", "BYD", "CATL"}
    others = [{"tesla", "byd"}, {"Apple"}, {"CATL", "BYD", "Ford"}]
    assert corroboration(own, others) == pytest.approx(2 / 3, abs=1e-3)
    assert corroboration(own, []) == 0.0


def test_final_score_weights() -> None:
    assert final_score(1.0, 1.0, 1.0) == pytest.approx(1.0)
    assert final_score(1.0, 0.0, 0.0) == pytest.approx(0.55)


def test_rank_with_diversity_caps_domain_in_top20() -> None:
    items = [{"d": "big.com", "s": 1.0 - i * 0.01} for i in range(10)] + [{"d": f"site{i}.com", "s": 0.5 - i * 0.01} for i in range(25)]
    ranked = rank_with_diversity(items, score=lambda x: x["s"], domain=lambda x: x["d"])
    assert len(ranked) == len(items)
    top20 = ranked[:20]
    assert sum(1 for x in top20 if x["d"] == "big.com") == 3
    assert [x["s"] for x in top20[:3]] == [1.0, 0.99, 0.98]
