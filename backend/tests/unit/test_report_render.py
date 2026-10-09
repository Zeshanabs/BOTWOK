"""Report rendering (doc 13 §13.6): data pack → Markdown sections → full Markdown + standalone HTML. Pure (no DB)."""
from __future__ import annotations

from typing import Any

from app.services import report_render as R
from app.services.report_service import normalize_recipient


def fixture_pack() -> dict[str, Any]:
    return {
        "version": 1, "kind": "weekly_performance", "generated_at": "2026-10-08T06:00:00+00:00",
        "brand": {"id": "b1", "name": "Pedal Co", "timezone": "Europe/Berlin"},
        "period": {"start": "2026-09-28", "end": "2026-10-04", "days": 7, "timezone": "Europe/Berlin"},
        "previous_period": {"start": "2026-09-21", "end": "2026-09-27"},
        "kpis": {
            "posts_published": {"value": 10, "coverage": 10, "basis": "count", "previous": 8, "delta_pct": 0.25},
            "impressions": {"value": 12345.0, "coverage": 7, "basis": "sum", "previous": 11000.0, "delta_pct": 0.1223},
            "reach": {"value": None, "coverage": 0, "basis": "sum", "previous": None, "delta_pct": None},
            "engagement": {"value": 420.0, "coverage": 9, "basis": "sum(likes+comments+shares+saves+clicks)",
                           "previous": 400.0, "delta_pct": 0.05},
            "engagement_rate": {"value": 0.0345, "coverage": 9, "basis": {"impressions": 7, "views": 2}, "median": 0.03,
                                "previous": 0.0391, "delta_pct": -0.1176},
        },
        "accounts": [{"platform": "linkedin", "display_name": "Pedal Co", "status": "active",
                      "followers": {"start": 1000, "end": 1040, "delta": 40}, "impressions": {"value": 9000.0},
                      "views": {"value": None}}],
        "trend": {"metric": "engagement_rate", "granularity": "week",
                  "points": [{"period": "2026-W39", "n": 4, "mean": 0.031}, {"period": "2026-W40", "n": 6, "mean": 0.0345}]},
        "top_posts": {"metric": "engagement_rate", "coverage": {"posts": 10, "with_metric": 9},
                      "posts": [{"published_post_id": "p1", "value": 0.081, "title": "<script>alert(1)</script> Battery tips",
                                 "format": "carousel", "platform": "linkedin", "url": "https://example.com/p1",
                                 "published_at": "2026-09-30T10:00:00+00:00"},
                                {"published_post_id": "p2", "value": 0.05, "title": None, "text": "Commute | hacks\nline 2",
                                 "format": "image", "platform": "instagram", "url": "javascript:alert(1)",
                                 "published_at": "2026-10-01T10:00:00+00:00"}]},
        "insights": [{"id": "i1", "statement": "Carousel posts performed 43% better than single-image posts on engagement "
                                              "rate (n=6 vs 9; early signal).", "kind": "format", "confidence": "low", "n": 15}],
        "recommendations": [{"id": "r1", "action": "Shift more posts to carousel posts.", "priority": "p3", "status": "proposed",
                             "expected_impact": "Up to +43% engagement rate", "target": {"format": "carousel"}}],
        "competitors": [{"competitor_id": "c1", "name": "Rival", "platform": "instagram", "snapshots": 3,
                         "posts_per_week": {"before": 3.0, "after": 7.0}, "followers": {"before": 1000, "after": 1100},
                         "availability": "official_api"},
                        {"competitor_id": "c2", "name": "Solo", "platform": "x", "snapshots": 1,
                         "posts_per_week": {"before": None, "after": 9.0}, "followers": {"before": None, "after": 500},
                         "availability": "official_api"}],
        "upcoming": [{"scheduled_at": "2026-10-09T14:00:00+00:00", "platform": "linkedin", "format": "carousel",
                      "title": "Winter battery care", "status": "scheduled"}],
        "data_notes": ["reach is available for 0 of 10 post(s); the rest are n/a, not zero."],
    }


def test_weekly_sections_and_numbers() -> None:
    pack = fixture_pack()
    sections = R.build_sections("weekly_performance", pack)
    assert [s["heading"] for s in sections] == ["Highlights", "Accounts", "Top posts", "Insights", "Recommendations",
                                                "Competitor activity", "Upcoming schedule", "Data notes"]
    hl = sections[0]["markdown"]
    assert "| Impressions | 12,345 | 11,000 | +12.2% | 7/10 posts | sum |" in hl
    assert "| Reach | n/a | n/a | n/a | 0/10 posts | sum |" in hl          # missing is n/a, never 0
    assert "| Engagement rate | 3.45% | 3.91% | −11.8% | 9/10 posts | impressions: 7, views: 2 |" in hl
    assert sections[0]["charts"][0]["type"] == "bar" and sections[0]["charts"][1]["type"] == "line"
    assert "2. **Commute | hacks** · Instagram · image" in sections[2]["markdown"]
    comp = next(s for s in sections if s["heading"] == "Competitor activity")["markdown"]
    assert "| Rival | Instagram | 3 | 7 | 1,000 | 1,100 | 3 | official_api |" in comp
    assert "| Solo | X | n/a | 9 | n/a | 500 | 1 | official_api |" in comp
    summary = R.build_summary("weekly_performance", pack)
    assert summary.startswith("Pedal Co published 10 post(s) in 2026-09-28 → 2026-10-04.")
    assert "Engagement rate averaged 3.45%, −11.8% vs the previous period (9 of 10 posts measured)." in summary
    assert "Impressions totalled 12,345 (+12.2%)." in summary and "1 post(s) are scheduled" in summary


def test_compose_markdown_and_html() -> None:
    out = R.compose("Weekly performance — Pedal Co", "weekly_performance", fixture_pack())
    md, html = out["markdown"], out["html"]
    assert md.startswith("# Weekly performance — Pedal Co\n")
    assert "## Summary" in md and "## Highlights" in md and "## Data notes" in md
    assert "_Weekly performance report · Pedal Co · 2026-09-28 → 2026-10-04 · generated 2026-10-08 06:00 UTC_" in md
    assert html.startswith("<!doctype html>") and "<title>Weekly performance — Pedal Co</title>" in html
    assert "<table style=" in html and "<th style=" in html and "<td style=" in html
    assert "<h2>Highlights</h2>" in html and "<ol>" in html and "<ul>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html                 # escaped
    assert "javascript:" not in html and "javascript:" not in md               # unsafe link dropped
    assert '<a href="https://example.com/p1"' in html
    assert "<strong>[P3]</strong>" in html
    assert "<link" not in html and "src=\"http" not in html                     # no external assets


def test_narrative_section_is_marked_and_summary_kept() -> None:
    narrative = {"summary": "A strong week driven by carousels.",
                 "sections": [{"heading": "What worked", "markdown": "- Carousels led engagement.", "sources": ["s1"]},
                              {"heading": "empty", "markdown": ""}]}
    out = R.compose("T", "weekly_performance", fixture_pack(), narrative=narrative)
    first = out["sections"][0]
    assert first["heading"] == "Narrative summary ✦" and first["origin"] == "ai" and first["sources"] == ["s1"]
    assert "### What worked" in first["markdown"] and "empty" not in first["markdown"]
    assert out["summary"] == "A strong week driven by carousels."
    assert out["summary_deterministic"].startswith("Pedal Co published 10 post(s)")
    assert 'class="section ai"' in out["html"] and "Sources: `s1`" in out["markdown"]


def test_research_brief_and_empty_packs() -> None:
    pack = {"period": {"start": "2026-09-01", "end": "2026-09-30"}, "brand": {"name": "Pedal Co"},
            "research": [{"query": "e-bike battery regulation", "status": "completed", "created_at": "2026-09-12T00:00:00",
                          "summary": "EU rules tighten.",
                          "findings": [{"text": "Swappable batteries required by 2027", "source_ids": ["s1"]}],
                          "sources": [{"source_id": "s1", "title": "EU battery regulation", "domain": "europa.eu",
                                       "url": "https://europa.eu/x", "credibility": 0.9}]}]}
    sections = R.build_sections("research_brief", pack)
    assert sections[0]["heading"] == "Research" and sections[0]["sources"] == ["s1"]
    assert "1. [EU battery regulation](https://europa.eu/x) · europa.eu · credibility 0.90" in sections[0]["markdown"]
    assert "- Swappable batteries required by 2027 [1]" in sections[0]["markdown"]
    assert R.build_summary("research_brief", pack) == "1 research run(s) in 2026-09-01 → 2026-09-30 with 1 cited source(s)."
    empty = R.build_sections("campaign", {"period": {}, "campaigns": [], "upcoming": []})
    assert [s["heading"] for s in empty] == ["Campaigns", "Upcoming schedule"]
    assert R.build_sections("custom", {}) == [R.section("Summary", "No data was available for this period.")]


def test_markdown_to_html_blocks() -> None:
    html = R.markdown_to_html("## Head\n\nPara with **bold**, _em_ and `code`.\n\n| a | b |\n|---|---|\n| 1 | x \\| y |\n\n"
                              "1. one\n2. two\n\n> quote\n\n---\n[mail](mailto:a@b.co) [bad](data:text/html,x)")
    assert "<h2>Head</h2>" in html and "<strong>bold</strong>" in html and "<em>em</em>" in html
    assert "<code style=" in html and "<td style" in html and ">x | y</td>" in html
    assert "<ol><li>one</li><li>two</li></ol>" in html and "<blockquote" in html and "<hr" in html
    assert 'href="mailto:a@b.co"' in html and "data:text" not in html
    assert "snake_case_word" in R.markdown_to_html("snake_case_word")             # no accidental italics


def test_recipient_normalization() -> None:
    assert normalize_recipient("a@b.co") == {"type": "email", "email": "a@b.co"}
    assert normalize_recipient("Slack") == {"type": "channel", "channel": "slack"}
    assert normalize_recipient({"user_id": "0192f1d2-0000-7000-8000-000000000001"})["type"] == "user"
    assert normalize_recipient({"channel": "webhook"}) == {"type": "channel", "channel": "webhook"}
    assert normalize_recipient("not an address") is None and normalize_recipient({}) is None
