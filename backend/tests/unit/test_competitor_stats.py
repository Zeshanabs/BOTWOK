"""Deterministic competitor stats (stats.describe) and keyword clustering."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.models.enums import ContentFormat
from app.research.competitor_stats import cluster_by_jaccard, describe_posts, snapshot_fields

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@dataclass
class P:
    posted_at: datetime | None
    format: ContentFormat | None = ContentFormat.image
    text: str | None = ""
    hashtags: list[str] = field(default_factory=list)
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    view_count: int | None = None
    url: str | None = None


def sample() -> list[P]:
    posts = []
    for i in range(12):  # 12 posts over the last 60 days, every 5 days at 09:00 UTC
        posts.append(P(posted_at=NOW - timedelta(days=5 * i, hours=3), format=ContentFormat.carousel if i % 3 == 0 else ContentFormat.image,
                       text=f"New drop #{i} 🔥 shop now https://acme.test/p{i}" if i % 2 == 0 else "Behind the scenes at the studio",
                       hashtags=["acme", "style"] if i % 2 == 0 else ["acme"], like_count=100 + i, comment_count=10))
    posts.append(P(posted_at=None, text="undated"))
    return posts


def test_counts_and_cadence() -> None:
    s = describe_posts(sample(), now=NOW)
    assert s["counts"]["7d"] == 2           # day 0 and day 5
    assert s["counts"]["30d"] == 6          # days 0,5,...,25
    assert s["counts"]["90d"] == 12
    assert s["counts"]["undated"] == 1 and s["counts"]["total"] == 13
    assert s["cadence"]["per_week_30d"] == round(6 / (30 / 7), 2)


def test_distributions() -> None:
    s = describe_posts(sample(), now=NOW)
    assert s["posting_hours"] == {"9": 12}
    assert sum(s["posting_days"].values()) == 12
    assert set(s["format_mix"]) == {"carousel", "image"}
    assert abs(sum(s["format_mix"].values()) - 1.0) < 0.01
    assert s["hashtags"]["top"][0] == ["acme", 12]
    assert s["emoji_share"] == 0.5 and s["cta_share"] == 0.5 and s["link_share"] == 0.5
    assert s["caption_length"]["min"] > 0


def test_engagement_only_when_counts_exist() -> None:
    s = describe_posts(sample(), now=NOW, followers=1000)
    assert s["engagement"]["available"] is True
    assert s["engagement"]["avg_rate"] is not None
    no_counts = [P(posted_at=NOW - timedelta(days=1)), P(posted_at=NOW - timedelta(days=2))]
    s2 = describe_posts(no_counts, now=NOW)
    assert s2["engagement"] == {"available": False, "reason": "not available"}
    s3 = describe_posts(sample(), now=NOW, allow_derived=False)
    assert s3["engagement"]["available"] is False and "policy" in s3["engagement"]["reason"]


def test_changes_vs_previous_snapshot_and_alerts() -> None:
    prev = {"posts_last_7d": 1, "posts_last_30d": 2, "followers_count": 900, "format_mix": {"image": 1.0}}
    s = describe_posts(sample(), now=NOW, followers=1000, previous=prev)
    assert s["changes"]["posts_last_30d_delta"] == 4
    assert s["changes"]["posts_last_30d_pct"] == 200.0
    assert s["changes"]["followers_delta"] == 100
    assert any("posting frequency" in a for a in s["alerts"])
    assert any("carousel" in a for a in s["alerts"])


def test_snapshot_fields_and_determinism() -> None:
    a = describe_posts(sample(), now=NOW)
    b = describe_posts(sample(), now=NOW)
    assert a == b
    f = snapshot_fields(a)
    assert f["posts_last_7d"] == 2 and f["posts_last_30d"] == 6 and f["top_hashtags"]["acme"] == 12


def test_empty_posts() -> None:
    s = describe_posts([], now=NOW)
    assert s["counts"]["total"] == 0 and s["format_mix"] == {} and s["caption_length"] is None


def test_cluster_by_jaccard() -> None:
    docs = [("a", {"vegan", "recipes", "protein"}), ("b", {"vegan", "protein", "snacks"}),
            ("c", {"marathon", "training", "running"}), ("d", {"running", "marathon", "shoes"}), ("e", set())]
    groups = cluster_by_jaccard(docs, threshold=0.2)
    as_sets = [set(g) for g in groups]
    assert {0, 1} in as_sets and {2, 3} in as_sets
