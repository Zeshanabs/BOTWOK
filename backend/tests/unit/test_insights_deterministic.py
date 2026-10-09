"""Deterministic insight rules (doc 13 §13.5): evidence pack → insights/recommendations with min-n labelling, effect
thresholds and "missing ≠ zero". Pure functions only (no DB)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.analytics.normalize import POST_METRIC_KEYS
from app.services.insight_service import (
    confidence_for_n,
    derive_insights,
    evidence_pack_from_rows,
    infer_kind,
    normalize_agent_insight,
    normalize_agent_recommendation,
    parse_effect,
)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
_seq = iter(range(10_000))


def row(fmt: str, er: float | None, *, platform: str = "linkedin", pillar: str | None = None, hour: int = 10,
        days_ago: int = 10, basis: str = "impressions") -> dict[str, Any]:
    i = next(_seq)
    published = (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=0)
    metrics: dict[str, Any] = {k: None for k in POST_METRIC_KEYS}
    avail: dict[str, str] = {k: "not_available" for k in POST_METRIC_KEYS}
    if er is not None:
        metrics.update(impressions=1000.0, likes=er * 1000)
        avail.update(impressions="available", likes="available")
    return {"published_post_id": f"post-{i}", "external_id": f"x{i}", "external_url": None, "published_at": published,
            "platform": platform, "social_account_id": "acc-1", "account_name": "Acme", "content_variant_id": None,
            "content_item_id": None, "title": f"Post {i}", "text": f"text {i}", "format": fmt, "pillar_id": pillar,
            "campaign_id": None, "content_type": None, "captured_at": published, "metrics": metrics, "availability": avail,
            "engagement_rate": er, "engagement_rate_basis": basis if er is not None else None, "segments": []}


def pack_for(rows: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return evidence_pack_from_rows(rows, now=NOW, period={"start": "2026-09-08", "end": "2026-10-08", "days": 30}, **kw)


def by_kind(insights: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [i for i in insights if i["kind"] == kind]


def test_confidence_thresholds() -> None:
    assert [confidence_for_n(n) for n in (None, 0, 7, 8, 19, 20, 200)] == ["low", "low", "low", "medium", "medium", "high", "high"]


def test_format_insight_early_signal_and_recommendation() -> None:
    rows = [row("carousel", 0.05) for _ in range(6)] + [row("image", 0.035) for _ in range(9)]
    pack = pack_for(rows)
    assert pack["coverage"] == {"posts": 15, "mature_posts": 15, "with_metric": 15}
    insights, recs = derive_insights(pack)
    fmt = by_kind(insights, "format")
    assert len(fmt) == 1
    ins = fmt[0]
    assert ins["statement"] == ("Carousel posts performed 43% better than single-image posts on engagement rate "
                                "(n=6 vs 9; early signal).")
    assert ins["confidence"] == "low" and ins["early_signal"] is True
    assert ins["n"] == 15 and abs(ins["effect_size"] - 0.4286) < 1e-4
    assert ins["evidence"]["source"] == "deterministic" and len(ins["evidence"]["post_ids"]) == 15
    # single platform / no pillar / one posting hour → no other comparisons
    assert {i["kind"] for i in insights} == {"format"}
    assert len(recs) == 1 and recs[0]["insight_index"] == 0
    assert recs[0]["target"] == {"format": "carousel"} and recs[0]["priority"] == "p3"
    assert "early signal" in recs[0]["expected_impact"]


def test_large_n_significant_effect_is_high_confidence() -> None:
    rows = [row("carousel", 0.05 + i * 0.0001) for i in range(20)] + [row("image", 0.03 + i * 0.0001) for i in range(25)]
    insights, recs = derive_insights(pack_for(rows))
    ins = by_kind(insights, "format")[0]
    assert ins["confidence"] == "high" and not ins["early_signal"]
    assert "early signal" not in ins["statement"] and "(n=20 vs 25)" in ins["statement"]
    assert recs[0]["priority"] == "p1"


def test_effect_thresholds() -> None:
    tiny = [row("carousel", 0.036) for _ in range(8)] + [row("image", 0.035) for _ in range(8)]
    insights, recs = derive_insights(pack_for(tiny))
    assert insights == [] and recs == []           # 2.9% < 10%: not an insight
    modest = [row("carousel", 0.0392) for _ in range(8)] + [row("image", 0.035) for _ in range(8)]
    insights, recs = derive_insights(pack_for(modest))
    assert len(insights) == 1 and "12% better" in insights[0]["statement"]
    assert recs == []                               # 12% < 15%: no recommendation
    big = [row("carousel", 0.08) for _ in range(8)] + [row("image", 0.035) for _ in range(8)]
    insights, _ = derive_insights(pack_for(big))
    assert "achieved 2.3× the engagement rate of single-image posts" in insights[0]["statement"]


def test_minimum_group_n_and_minimum_coverage() -> None:
    # carousel has only 2 posts → never compared; one eligible group left → no format insight
    rows = [row("carousel", 0.09) for _ in range(2)] + [row("image", 0.035) for _ in range(9)]
    insights, _ = derive_insights(pack_for(rows))
    assert by_kind(insights, "format") == []
    # fewer than 6 posts with the metric overall → no comparisons and a data note
    few = [row("carousel", 0.09) for _ in range(3)] + [row("image", 0.03) for _ in range(2)]
    pack = pack_for(few)
    assert derive_insights(pack) == ([], [])
    assert any("at least 6 are needed" in n for n in pack["data_notes"])


def test_missing_metrics_are_not_zero() -> None:
    measured = [row("carousel", 0.05) for _ in range(6)] + [row("image", 0.035) for _ in range(9)]
    # TikTok video posts without engagement metrics + carousel posts whose metrics are missing
    missing = [row("video", None, platform="tiktok") for _ in range(5)] + [row("carousel", None) for _ in range(3)]
    pack = pack_for(measured + missing)
    assert pack["coverage"] == {"posts": 23, "mature_posts": 23, "with_metric": 15}
    groups = {g["key"]: g for g in pack["compare_groups"]["format"]["groups"]}
    assert "video" not in groups                    # no metric → not a group with mean 0
    assert groups["carousel"]["n"] == 6 and groups["carousel"]["mean"] == 0.05   # missing ones don't drag the mean down
    assert any("8 of 23 post(s) have no engagement rate" in n and "not counted as zero" in n for n in pack["data_notes"])
    insights, _ = derive_insights(pack)
    statements = " ".join(i["statement"] for i in insights)
    assert "video" not in statements.lower() and "TikTok" not in statements
    fmt = by_kind(insights, "format")[0]
    assert "(n=6 vs 9; early signal)" in fmt["statement"]
    # KPIs keep missing sums as None (n/a), not 0
    assert pack["kpis"]["impressions"]["coverage"] == 15


def test_immature_posts_are_excluded() -> None:
    rows = [row("carousel", 0.05) for _ in range(6)] + [row("image", 0.035) for _ in range(9)]
    rows += [row("image", 0.5, days_ago=1) for _ in range(4)]      # < 72 h old: would flip the result if counted
    pack = pack_for(rows)
    assert pack["coverage"]["mature_posts"] == 15
    assert any("last 72 h" in n for n in pack["data_notes"])
    assert by_kind(derive_insights(pack)[0], "format")[0]["statement"].startswith("Carousel posts performed 43% better")


def test_timing_insight_uses_two_hour_windows() -> None:
    rows = ([row("image", 0.06, hour=10) for _ in range(5)] + [row("image", 0.03, hour=15) for _ in range(5)]
            + [row("image", 0.03, hour=18) for _ in range(4)])
    insights, recs = derive_insights(pack_for(rows))
    t = by_kind(insights, "timing")
    assert len(t) == 1
    assert t[0]["statement"] == ("Posts published 10:00–12:00 (UTC) performed best: engagement rate 47% above the average "
                                 "across all posts (n=5; early signal).")
    assert t[0]["confidence"] == "low"
    rec = next(r for r in recs if r["insight_index"] == insights.index(t[0]))
    assert rec["target"] == {"time_slot": "10:00-12:00", "timezone": "UTC"}


def test_platform_insight_labels_different_bases() -> None:
    rows = ([row("image", 0.07, platform="tiktok", basis="views") for _ in range(10)]
            + [row("image", 0.03, platform="linkedin", basis="impressions") for _ in range(10)])
    pack = pack_for(rows)
    assert any("different denominators" in n for n in pack["data_notes"])
    p = by_kind(derive_insights(pack)[0], "platform")[0]
    assert "TikTok posts achieved 2.3× the engagement rate of LinkedIn posts" in p["statement"]
    assert "different bases: views vs impressions" in p["statement"] and p["confidence"] == "low"


def test_pillar_insight_uses_labels_and_skips_unassigned() -> None:
    rows = ([row("image", 0.05, pillar="p-1") for _ in range(8)] + [row("image", 0.03, pillar="p-2") for _ in range(8)]
            + [row("image", 0.001) for _ in range(8)])            # no pillar: never compared
    pack = pack_for(rows, labels={"pillar": {"p-1": "Battery care", "p-2": "Commuting"}})
    p = by_kind(derive_insights(pack)[0], "pillar")[0]
    assert p["statement"].startswith("Posts in the 'Battery care' pillar performed 67% better than posts in the "
                                     "'Commuting' pillar")
    assert p["confidence"] in ("medium", "low")


def test_competitor_deltas_need_two_snapshots() -> None:
    comps = [{"competitor_id": "c1", "name": "Rival", "platform": "instagram", "snapshots": 3, "posts_last_30d": 24,
              "first_captured_at": "2026-09-10T00:00:00+00:00", "last_captured_at": "2026-10-07T00:00:00+00:00",
              "posts_per_week": {"before": 3.0, "after": 7.0}, "followers": {"before": 1000, "after": 1050}},
             {"competitor_id": "c2", "name": "Solo", "platform": "x", "snapshots": 1, "posts_last_30d": 10,
              "posts_per_week": {"before": None, "after": 9.0}, "followers": {"before": None, "after": 500}}]
    pack = pack_for([], competitor_deltas=comps)
    insights, recs = derive_insights(pack)
    assert len(insights) == 1
    assert insights[0]["statement"].startswith("Competitor Rival increased posting frequency on Instagram from 3 to 7 posts/week")
    assert insights[0]["confidence"] == "high" and insights[0]["kind"] == "competitor"
    assert recs[0]["target"] == {"competitor_id": "c1", "platform": "instagram"}


def test_agent_output_normalization() -> None:
    ins = normalize_agent_insight({"statement": "Reels beat single images", "effect": "+34% engagement rate", "n": 5,
                                   "confidence": 0.9, "evidence_ids": ["post-1"]})
    assert ins is not None
    assert ins["kind"] == "format" and ins["effect_size"] == 0.34 and ins["confidence"] == "low"
    assert ins["statement"].endswith("(early signal).") and ins["evidence"]["evidence_ids"] == ["post-1"]
    big = normalize_agent_insight({"statement": "Posts at 10:00 performed best", "n": 40, "confidence": 0.8})
    assert big is not None and big["kind"] == "timing" and big["confidence"] == "high"
    assert normalize_agent_insight({"statement": "  "}) is None
    assert parse_effect("2.1× the average") == 1.1 and parse_effect("−12% reach") == -0.12 and parse_effect(None) is None
    assert infer_kind("Competitor X doubled cadence") == "competitor" and infer_kind("something else") == "topic"
    rec = normalize_agent_recommendation({"action": "Post more carousels", "rationale": "r", "priority": "high",
                                          "links_to": "format", "target": "carousel"})
    assert rec is not None and rec["priority"] == "p1" and rec["target"] == {"format": "carousel", "links_to": "format"}
