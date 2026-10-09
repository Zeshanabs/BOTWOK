"""Normalizer tests: missing → NULL + not_available (never 0), deprecated names flagged, engagement basis selection."""
from __future__ import annotations

from app.analytics.normalize import (
    POST_METRIC_KEYS,
    compute_engagement_rate,
    normalize_account_metrics,
    normalize_post_metrics,
)
from app.analytics.stats import bootstrap_ci, mann_whitney_u


def test_missing_metrics_are_null_and_not_available():
    out = normalize_post_metrics("gbp", {})
    assert set(out["metrics"]) == set(POST_METRIC_KEYS)
    assert all(v is None for v in out["metrics"].values())
    assert all(v == "not_available" for v in out["availability"].values())
    assert out["engagement_rate"] is None and out["engagement_rate_basis"] is None


def test_instagram_views_replaces_impressions_and_basis_reach():
    out = normalize_post_metrics("instagram", {"insights": {"views": 1000, "reach": 800, "likes": 50, "comments": 5, "saved": 10, "shares": 2}})
    m, a = out["metrics"], out["availability"]
    assert m["views"] == 1000 and a["views"] == "available"
    assert m["impressions"] is None and a["impressions"] == "deprecated"
    assert m["saves"] == 10 and a["saves"] == "available"
    assert a["clicks"] == "not_available" and m["clicks"] is None
    # impressions deprecated → reach is the basis: (50+5+10+2)/800
    assert out["engagement_rate_basis"] == "reach" and abs(out["engagement_rate"] - 67 / 800) < 1e-6


def test_x_public_metrics_basis_impressions_and_private_window():
    raw = {"public_metrics": {"impression_count": 2000, "like_count": 20, "reply_count": 4, "retweet_count": 6, "quote_count": 1, "bookmark_count": 3},
           "private_metrics_window_closed": True}
    out = normalize_post_metrics("x", raw)
    m, a = out["metrics"], out["availability"]
    assert m["impressions"] == 2000 and m["likes"] == 20 and m["replies"] == 4 and m["saves"] == 3
    assert m["shares"] == 7 and a["shares"] == "derived"
    assert m["link_clicks"] is None and a["link_clicks"] == "not_available"
    assert out["engagement_rate_basis"] == "impressions"
    assert abs(out["engagement_rate"] - (20 + 4 + 7 + 3) / 2000) < 1e-6


def test_basis_falls_back_to_views_then_followers():
    out = normalize_post_metrics("tiktok", {"video": {"view_count": 500, "like_count": 50, "comment_count": 0, "share_count": 5}})
    assert out["engagement_rate_basis"] == "views" and abs(out["engagement_rate"] - 55 / 500) < 1e-9
    m = {"likes": 10, "comments": 0, "shares": None, "saves": None, "clicks": None, "impressions": None, "reach": None, "views": None}
    a = {"likes": "available", "comments": "available", "shares": "not_available", "saves": "not_available", "clicks": "not_available",
         "impressions": "not_available", "reach": "not_available", "views": "not_available"}
    rate, basis = compute_engagement_rate(m, a, followers=1000)
    assert basis == "followers" and abs(rate - 0.01) < 1e-9
    rate, basis = compute_engagement_rate(m, a, followers=None)
    assert rate is None and basis is None


def test_facebook_deprecated_unique_metrics_and_youtube_bytes():
    out = normalize_post_metrics("facebook", {"insights": {"post_media_view": 100, "post_total_media_view_unique": 80, "post_impressions_unique": 70,
                                                           "post_clicks": 9}, "likes": 4, "comments": 1, "shares": 2})
    assert out["metrics"]["views"] == 100 and out["metrics"]["reach"] == 80
    assert out["availability"]["impressions"] == "deprecated" and out["metrics"]["impressions"] is None
    assert out["engagement_rate_basis"] == "reach"
    yt = normalize_post_metrics("youtube", {"statistics": {"viewCount": "1500", "likeCount": "30", "commentCount": "2"},
                                            "analytics": {"estimatedMinutesWatched": 10, "averageViewDuration": 40, "averageViewPercentage": 55}})
    assert yt["metrics"]["views"] == 1500 and yt["metrics"]["watch_time_s"] == 600
    assert yt["metrics"]["completion_rate"] == 0.55 and yt["availability"]["completion_rate"] == "derived"
    assert yt["availability"]["impressions"] == "not_available"


def test_account_metrics_and_linkedin_member_without_scope():
    acc = normalize_account_metrics("x", {"public_metrics": {"followers_count": 10, "following_count": 5, "tweet_count": 100}})
    assert acc["metrics"]["followers"] == 10 and acc["availability"]["reach"] == "not_available" and acc["metrics"]["reach"] is None
    li = normalize_post_metrics("linkedin", {"flavor": "member", "member_stats": None})
    assert all(v is None for v in li["metrics"].values())
    org = normalize_post_metrics("linkedin", {"flavor": "organization", "org_stats": {"impressionCount": 300, "likeCount": 3, "commentCount": 0, "shareCount": 1, "clickCount": 2}})
    assert org["engagement_rate_basis"] == "impressions" and abs(org["engagement_rate"] - 6 / 300) < 1e-9


def test_mann_whitney_and_bootstrap_sanity():
    a = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7]
    b = [3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7]
    r = mann_whitney_u(a, b)
    assert r["p_value"] < 0.01
    same = mann_whitney_u(a, a)
    assert same["p_value"] > 0.5
    lo, hi = bootstrap_ci(a)
    assert lo is not None and lo < sum(a) / len(a) < hi
