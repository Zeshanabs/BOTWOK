"""InsightService (doc 13 §13.5): the performance learning loop.

``analyze`` builds a deterministic **evidence pack** from the normalized metric tables with the same stats functions the
``stats.*`` tools expose (compare_groups by format/pillar/platform, hourly windows, time_of_day, trend, top_posts) plus
competitor snapshot deltas. Then:

* an AI provider key is configured for the ``performance_analyst`` tier → ``AIService.create_run(mode="tool",
  agent="performance_analyst", action="analyze", inputs={evidence_pack, ...})``; the agent's ``Insights`` output is
  persisted by the ``insights.save`` / ``recommendations.save`` tools or, at the latest, by ``apply_agent_output`` (the
  ``AI_RUN_COMPLETED`` consumer in ``app/events/consumers_insights.py``);
* no key → **deterministic insights** templated from the numbers (``derive_insights``), one recommendation per insight
  whose effect is ≥ 15 %.

Rules honoured everywhere: missing ≠ zero (posts without the metric are excluded and reported in ``coverage``), groups
with fewer than ``MIN_GROUP_N`` posts are never compared, statements with n < 8 are labelled "early signal", confidence
comes from n (n < 8 low, < 20 medium, else high; capped at medium without significance).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import stats as S
from app.analytics.queries import brand_tz, group_key, kpis, labels_for, metric_value, post_rows
from app.core.errors import ProblemError, conflict, not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.models.brand import Brand
from app.models.competitor import Competitor, CompetitorSnapshot
from app.models.enums import MemberRole
from app.models.identity import WorkspaceMember
from app.models.scheduling import Insight, Recommendation

log = get_logger("insights.service")

PACK_VERSION = 1
DEFAULT_METRIC = "engagement_rate"
MIN_GROUP_N = 3                 # a group needs this many posts *with the metric* to be compared at all
MIN_COVERAGE = 6                # posts with the metric needed before any group comparison
EARLY_SIGNAL_N = 8              # doc 06: statements based on fewer than 8 posts are "early signal"
MEDIUM_N, HIGH_N = 8, 20        # confidence thresholds on n
MIN_INSIGHT_EFFECT = 0.10       # smaller differences are not reported as insights
MIN_RECOMMENDATION_EFFECT = 0.15
SIGNIFICANCE_P = 0.05
MATURE_AFTER_H = 72             # doc 13 §13.5: compare posts with ≥ 72 h of metrics
INSIGHT_KINDS = ("format", "pillar", "timing", "topic", "platform", "competitor", "audience")
INSIGHT_STATUSES = ("new", "acknowledged", "dismissed")
RECOMMENDATION_STATUSES = ("proposed", "accepted", "rejected", "applied")
PRIORITY_BY_CONFIDENCE = {"high": "p1", "medium": "p2", "low": "p3"}
AI_PRIORITY = {"high": "p1", "medium": "p2", "low": "p3"}

METRIC_LABELS = {"engagement_rate": "engagement rate", "engagement": "total engagement", "impressions": "impressions",
                 "reach": "reach", "views": "views", "clicks": "clicks", "link_clicks": "link clicks", "saves": "saves",
                 "shares": "shares", "comments": "comments", "likes": "likes"}
FORMAT_LABELS = {"text": "text-only posts", "image": "single-image posts", "carousel": "carousel posts",
                 "video": "video posts", "short_video": "short-video posts", "story": "stories", "article": "articles",
                 "poll": "polls", "document": "document posts", "link": "link posts"}
PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram", "threads": "Threads", "linkedin": "LinkedIn",
                   "x": "X", "tiktok": "TikTok", "youtube": "YouTube", "pinterest": "Pinterest",
                   "gbp": "Google Business Profile"}


# ================================================================================================ pure helpers
def confidence_for_n(n: int | None) -> str:
    """n < 8 → low, n < 20 → medium, else high."""
    if n is None or n < MEDIUM_N:
        return "low"
    if n < HIGH_N:
        return "medium"
    return "high"


def _cap(conf: str, cap: str) -> str:
    order = ("low", "medium", "high")
    return order[min(order.index(conf), order.index(cap))]


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


def group_label(by: str, key: str, labels: dict[str, str] | None = None) -> str:
    if by == "format":
        return FORMAT_LABELS.get(key, f"{key.replace('_', ' ')} posts")
    if by == "platform":
        return f"{PLATFORM_LABELS.get(key, key)} posts"
    if by == "pillar":
        name = (labels or {}).get(key, key)
        return f"posts in the '{name}' pillar"
    return (labels or {}).get(key, key)


def _pct(effect: float) -> str:
    return f"{round(effect * 100):d}%"


def _effect_phrase(effect: float) -> str:
    """0.42 → '42% better than'; 1.1 → '2.1× the … of'."""
    if effect >= 1.0:
        return f"{effect + 1:.1f}×"
    return _pct(effect)


def _sentence_case(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _n_note(*ns: int, early: bool, extra: str | None = None) -> str:
    core = "n=" + " vs ".join(str(n) for n in ns)
    parts = [core]
    if early:
        parts.append("early signal")
    if extra:
        parts.append(extra)
    return "(" + "; ".join(parts) + ")"


def _dominant(counter: dict[str, int] | None) -> str | None:
    if not counter:
        return None
    return max(counter.items(), key=lambda kv: kv[1])[0]


def evidence_pack_from_rows(rows: list[dict[str, Any]], *, metric: str = DEFAULT_METRIC, tz: ZoneInfo | None = None,
                            labels: dict[str, dict[str, str]] | None = None, period: dict[str, Any] | None = None,
                            competitor_deltas: list[dict[str, Any]] | None = None, brand: dict[str, Any] | None = None,
                            now: datetime | None = None, mature_after_h: int = MATURE_AFTER_H) -> dict[str, Any]:
    """Deterministic evidence pack (JSON-safe) from ``analytics.queries.post_rows`` dicts. Pure: no DB, no clock unless
    ``now`` is omitted. Posts younger than ``mature_after_h`` are excluded from comparisons (metrics still maturing)."""
    tz = tz or ZoneInfo("UTC")
    now = now or datetime.now(UTC)
    labels = labels or {}
    cutoff = now - timedelta(hours=mature_after_h)
    mature = [r for r in rows if r["published_at"] <= cutoff]
    with_metric = [r for r in mature if metric_value(r, metric) is not None]
    notes: list[str] = []
    immature = len(rows) - len(mature)
    if immature:
        notes.append(f"{immature} post(s) published in the last {mature_after_h} h are excluded from comparisons "
                     "(metrics still maturing).")
    missing = len(mature) - len(with_metric)
    if missing:
        by_platform = Counter(r["platform"] for r in mature if metric_value(r, metric) is None)
        detail = ", ".join(f"{PLATFORM_LABELS.get(p, p)}: {n}" for p, n in sorted(by_platform.items()))
        notes.append(f"{missing} of {len(mature)} post(s) have no {metric_label(metric)} ({detail}); they are excluded, "
                     "not counted as zero.")
    if len(with_metric) < MIN_COVERAGE:
        notes.append(f"Only {len(with_metric)} post(s) carry {metric_label(metric)}; at least {MIN_COVERAGE} are needed "
                     "before formats, pillars, platforms or posting times are compared.")
    bases: dict[str, dict[str, Counter]] = {"platform": defaultdict(Counter), "format": defaultdict(Counter)}
    group_posts: dict[str, dict[str, list[str]]] = {"format": defaultdict(list), "pillar": defaultdict(list),
                                                     "platform": defaultdict(list)}
    for r in with_metric:
        basis = r.get("engagement_rate_basis") if metric == "engagement_rate" else None
        for by in ("format", "pillar", "platform"):
            k = group_key(r, by, tz) or "(none)"
            if len(group_posts[by][k]) < 25:
                group_posts[by][k].append(r["published_post_id"])
            if basis and by in bases:
                bases[by][k][basis] += 1
    all_bases = Counter(r.get("engagement_rate_basis") for r in with_metric if r.get("engagement_rate_basis"))
    if metric == "engagement_rate" and len(all_bases) > 1:
        notes.append("Engagement rate uses different denominators across posts ("
                     + ", ".join(f"{b}: {n}" for b, n in sorted(all_bases.items()))
                     + "); comparisons across those bases are labelled.")
    compare = {by: S.compare_groups(mature, metric, by, tz=tz, labels=labels.get(by)) for by in ("format", "pillar", "platform")}
    hourly = S.compare_groups(mature, metric, "hour", tz=tz)
    return {
        "version": PACK_VERSION, "metric": metric, "metric_label": metric_label(metric), "brand": brand, "period": period,
        "timezone": getattr(tz, "key", "UTC"), "generated_at": now.isoformat(),
        "coverage": {"posts": len(rows), "mature_posts": len(mature), "with_metric": len(with_metric)},
        "kpis": kpis(rows),
        "compare_groups": compare,
        "hourly": hourly,
        "time_of_day": S.time_of_day(mature, metric, tz=tz),
        "trend": S.trend(rows, metric, granularity="week"),
        "top_posts": S.top_posts(rows, metric, k=5),
        "basis_by_group": {by: {k: dict(c) for k, c in v.items()} for by, v in bases.items()},
        "group_posts": {by: dict(v) for by, v in group_posts.items()},
        "labels": {k: dict(v) for k, v in labels.items()},
        "competitors": competitor_deltas or [],
        "data_notes": notes,
        "thresholds": {"min_group_n": MIN_GROUP_N, "min_coverage": MIN_COVERAGE, "early_signal_n": EARLY_SIGNAL_N,
                       "min_insight_effect": MIN_INSIGHT_EFFECT, "min_recommendation_effect": MIN_RECOMMENDATION_EFFECT},
    }


def _eligible(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in groups if g.get("key") not in (None, "(none)") and (g.get("n") or 0) >= MIN_GROUP_N
            and g.get("mean") is not None]


def _pair_insight(pack: dict[str, Any], by: str) -> dict[str, Any] | None:
    cg = (pack.get("compare_groups") or {}).get(by) or {}
    if (cg.get("n") or 0) < MIN_COVERAGE:
        return None
    groups = _eligible(cg.get("groups") or [])
    if len(groups) < 2:
        return None
    best = max(groups, key=lambda g: g["mean"])
    worst = min(groups, key=lambda g: g["mean"])
    if worst["mean"] <= 0 or best is worst:
        return None
    effect = best["mean"] / worst["mean"] - 1
    if effect < MIN_INSIGHT_EFFECT:
        return None
    labels = (pack.get("labels") or {}).get(by) or {}
    metric = pack.get("metric", DEFAULT_METRIC)
    n_small = min(best["n"], worst["n"])
    early = n_small < EARLY_SIGNAL_N
    conf = confidence_for_n(n_small)
    p = best.get("p_value")
    if p is None or p >= SIGNIFICANCE_P:
        conf = _cap(conf, "medium")
    extra = None
    if by == "platform" and metric == "engagement_rate":
        bb = (pack.get("basis_by_group") or {}).get("platform") or {}
        b1, b2 = _dominant(bb.get(best["key"])), _dominant(bb.get(worst["key"]))
        if b1 and b2 and b1 != b2:
            extra = f"different bases: {b1} vs {b2}"
            conf = "low"
    best_l, worst_l = group_label(by, best["key"], labels), group_label(by, worst["key"], labels)
    if effect >= 1.0:
        body = f"{best_l} achieved {_effect_phrase(effect)} the {metric_label(metric)} of {worst_l}"
    else:
        body = f"{best_l} performed {_pct(effect)} better than {worst_l} on {metric_label(metric)}"
    statement = f"{_sentence_case(body)} {_n_note(best['n'], worst['n'], early=early, extra=extra)}."
    gp = (pack.get("group_posts") or {}).get(by) or {}
    evidence = {"source": "deterministic", "pack_version": pack.get("version"), "metric": metric, "group_by": by,
                "compared": [best, worst], "overall_mean": cg.get("overall_mean"), "coverage": cg.get("coverage"),
                "p_value_best_vs_rest": p, "post_ids": (gp.get(best["key"], [])[:10] + gp.get(worst["key"], [])[:10]),
                "early_signal": early, "basis_note": extra}
    return {"kind": by, "statement": statement, "metric": metric, "effect_size": round(effect, 4),
            "n": best["n"] + worst["n"], "n_min": n_small, "confidence": conf, "early_signal": early, "evidence": evidence,
            "_best": best, "_worst": worst, "_best_label": best_l, "_worst_label": worst_l}


def _timing_insight(pack: dict[str, Any]) -> dict[str, Any] | None:
    hourly = pack.get("hourly") or {}
    overall = hourly.get("overall_mean")
    if not overall or (hourly.get("n") or 0) < MIN_COVERAGE:
        return None
    windows: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for g in hourly.get("groups") or []:
        try:
            h = int(g["key"])
        except (TypeError, ValueError):
            continue
        if g.get("mean") is None or not g.get("n"):
            continue
        windows[(h // 2) * 2].append((int(g["n"]), float(g["mean"])))
    agg = []
    for start, parts in windows.items():
        n = sum(p[0] for p in parts)
        mean = sum(p[0] * p[1] for p in parts) / n
        agg.append({"start": start, "n": n, "mean": round(mean, 5)})
    eligible = [w for w in agg if w["n"] >= MIN_GROUP_N]
    if len(eligible) < 2:
        return None
    best = max(eligible, key=lambda w: w["mean"])
    effect = best["mean"] / overall - 1
    if effect < MIN_INSIGHT_EFFECT:
        return None
    metric = pack.get("metric", DEFAULT_METRIC)
    slot = f"{best['start']:02d}:00–{(best['start'] + 2) % 24:02d}:00"
    tzname = pack.get("timezone") or "UTC"
    early = best["n"] < EARLY_SIGNAL_N
    conf = _cap(confidence_for_n(best["n"]), "medium")   # no significance test on windows
    statement = (f"Posts published {slot} ({tzname}) performed best: {metric_label(metric)} {_pct(effect)} above the "
                 f"average across all posts {_n_note(best['n'], early=early)}.")
    evidence = {"source": "deterministic", "pack_version": pack.get("version"), "metric": metric, "group_by": "hour",
                "window": {"start_hour": best["start"], "end_hour": (best["start"] + 2) % 24, "timezone": tzname},
                "windows": sorted(agg, key=lambda w: w["start"]), "overall_mean": overall, "coverage": hourly.get("coverage"),
                "early_signal": early}
    return {"kind": "timing", "statement": statement, "metric": metric, "effect_size": round(effect, 4), "n": best["n"],
            "n_min": best["n"], "confidence": conf, "early_signal": early, "evidence": evidence,
            "_slot": slot, "_slot_key": f"{best['start']:02d}:00-{(best['start'] + 2) % 24:02d}:00", "_tz": tzname}


def _competitor_insights(pack: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in pack.get("competitors") or []:
        ppw = c.get("posts_per_week") or {}
        before, after = ppw.get("before"), ppw.get("after")
        platform = PLATFORM_LABELS.get(c.get("platform") or "", c.get("platform") or "their channels")
        name = c.get("name") or "A competitor"
        evidence = {"source": "deterministic", "pack_version": pack.get("version"), "competitor_id": c.get("competitor_id"),
                    "profile_id": c.get("profile_id"), "snapshot_ids": c.get("snapshot_ids", []),
                    "snapshots": c.get("snapshots"), "posts_per_week": ppw, "followers": c.get("followers")}
        if before is not None and after is not None and before > 0 and abs(after - before) >= 2:
            effect = after / before - 1
            if abs(effect) >= MIN_INSIGHT_EFFECT:
                n = c.get("posts_last_30d")
                verb = "increased" if effect > 0 else "decreased"
                statement = (f"Competitor {name} {verb} posting frequency on {platform} from {before:g} to {after:g} "
                             f"posts/week (snapshots {str(c.get('first_captured_at') or '?')[:10]} → "
                             f"{str(c.get('last_captured_at') or '?')[:10]}).")
                out.append({"kind": "competitor", "statement": statement, "metric": "posts_per_week",
                            "effect_size": round(effect, 4), "n": n, "n_min": n, "confidence": confidence_for_n(n),
                            "early_signal": (n or 0) < EARLY_SIGNAL_N, "evidence": evidence, "_competitor": c})
        fol = c.get("followers") or {}
        fb, fa = fol.get("before"), fol.get("after")
        if fb and fa is not None and fb > 0:
            growth = fa / fb - 1
            if abs(growth) >= MIN_INSIGHT_EFFECT:
                verb = "grew" if growth > 0 else "lost"
                statement = (f"Competitor {name} {verb} {platform} followers by {_pct(abs(growth))} "
                             f"({fb:,} → {fa:,}) over the period.")
                snaps = int(c.get("snapshots") or 0)
                out.append({"kind": "competitor", "statement": statement, "metric": "followers",
                            "effect_size": round(growth, 4), "n": snaps, "n_min": snaps,
                            "confidence": "medium" if snaps >= 3 else "low", "early_signal": False,
                            "evidence": evidence, "_competitor": c})
    return out


def _recommendation_for(ins: dict[str, Any]) -> dict[str, Any] | None:
    effect = ins.get("effect_size")
    if effect is None or abs(effect) < MIN_RECOMMENDATION_EFFECT:
        return None
    kind, conf = ins["kind"], ins["confidence"]
    metric = metric_label(ins.get("metric") or DEFAULT_METRIC)
    hedge = "early signal" if ins.get("early_signal") else f"{conf} confidence"
    priority = PRIORITY_BY_CONFIDENCE.get(conf, "p2")
    if kind in ("format", "pillar", "platform"):
        best, worst = ins["_best"], ins["_worst"]
        bl, wl = ins["_best_label"], ins["_worst_label"]
        if kind == "format":
            action = f"Shift more of next week's posts to {bl}: plan at least two and compare them with {wl}."
            target = {"format": best["key"]}
        elif kind == "pillar":
            action = f"Give {bl} a larger share of next week's content mix."
            target = {"pillar_id": best["key"]}
        else:
            action = f"Prioritize {bl.removesuffix(' posts')} for upcoming posts and review what underperforms on " \
                     f"{wl.removesuffix(' posts')}."
            target = {"platform": best["key"]}
        impact = f"Up to +{_pct(effect)} {metric} on shifted posts if the pattern holds ({hedge}; n={best['n']} vs {worst['n']})."
    elif kind == "timing":
        action = f"Schedule upcoming posts between {ins['_slot']} ({ins['_tz']})."
        target = {"time_slot": ins["_slot_key"], "timezone": ins["_tz"]}
        impact = f"Up to +{_pct(effect)} {metric} vs the average slot ({hedge}; n={ins['n']})."
    elif kind == "competitor":
        c = ins["_competitor"]
        platform = PLATFORM_LABELS.get(c.get("platform") or "", c.get("platform") or "their channels")
        action = f"Review {c.get('name')}'s recent {platform} content and decide whether to respond to the change."
        target = {"competitor_id": c.get("competitor_id"), "platform": c.get("platform")}
        impact = "Competitive awareness; no direct metric impact estimated."
        priority = "p3" if conf == "low" else "p2"
    else:
        return None
    return {"action": action, "rationale": ins["statement"], "expected_impact": impact, "priority": priority,
            "target": target}


def derive_insights(pack: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic insights + recommendations from an evidence pack. Each recommendation carries ``insight_index``."""
    insights: list[dict[str, Any]] = []
    for by in ("format", "pillar", "platform"):
        ins = _pair_insight(pack, by)
        if ins:
            insights.append(ins)
    t = _timing_insight(pack)
    if t:
        insights.append(t)
    insights.extend(_competitor_insights(pack))
    recs: list[dict[str, Any]] = []
    for i, ins in enumerate(insights):
        rec = _recommendation_for(ins)
        if rec:
            rec["insight_index"] = i
            recs.append(rec)
    return insights, recs


def public_insight(ins: dict[str, Any]) -> dict[str, Any]:
    """Strip the private ``_`` helpers before persisting/serializing."""
    return {k: v for k, v in ins.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------------------------- AI output mapping
_KIND_HINTS = (
    ("competitor", ("competitor",)),
    ("timing", ("time of day", "posting time", "published between", "weekday", "o'clock", ":00", "hour", "morning",
                "evening", "afternoon", "timing")),
    ("format", ("carousel", "reel", "video", "image", "format", "text-only", "story", "stories", "poll", "document")),
    ("pillar", ("pillar",)),
    ("platform", tuple(v.lower() for v in PLATFORM_LABELS.values()) + ("platform",)),
    ("audience", ("audience", "follower demographic", "followers aged")),
)
_LINKS_TO_KIND = {"pillar": "pillar", "format": "format", "time": "timing", "timing": "timing", "topic": "topic",
                  "platform": "platform", "competitor": "competitor", "audience": "audience"}


def infer_kind(statement: str, metric: str | None = None, links_to: str | None = None) -> str:
    if links_to and _LINKS_TO_KIND.get(links_to.lower()):
        return _LINKS_TO_KIND[links_to.lower()]
    text = f"{statement} {metric or ''}".lower()
    for kind, hints in _KIND_HINTS:
        if any(re.search(r"\b" + re.escape(h), text) for h in hints):
            return kind
    return "topic"


def parse_effect(effect: Any) -> float | None:
    """'+34% engagement rate' → 0.34; '2.1× average' → 1.1; '-12%' → -0.12; numbers pass through."""
    if effect is None:
        return None
    if isinstance(effect, int | float):
        return float(effect)
    s = str(effect)
    m = re.search(r"([-+−]?\d+(?:\.\d+)?)\s*%", s)
    if m:
        return round(float(m.group(1).replace("−", "-")) / 100, 4)
    m = re.search(r"(\d+(?:\.\d+)?)\s*[×x]", s)
    if m:
        return round(float(m.group(1)) - 1, 4)
    return None


def confidence_label(value: Any, n: int | None) -> str:
    """Agent confidence (0–1 float or label) → low|medium|high, never above what n supports."""
    if isinstance(value, str) and value.lower() in ("low", "medium", "high"):
        label = value.lower()
    elif isinstance(value, int | float):
        label = "low" if value < 0.4 else ("medium" if value < 0.7 else "high")
    else:
        label = "medium"
    return _cap(label, confidence_for_n(n)) if n is not None else _cap(label, "medium")


def normalize_agent_insight(item: dict[str, Any]) -> dict[str, Any] | None:
    statement = str(item.get("statement") or "").strip()
    if not statement:
        return None
    n = item.get("n")
    try:
        n = int(n) if n is not None else None
    except (TypeError, ValueError):
        n = None
    early = bool(item.get("early_signal")) or (n is not None and n < EARLY_SIGNAL_N)
    if early and "early signal" not in statement.lower():
        statement = statement.rstrip(".") + " (early signal)."
    kind = item.get("kind") if item.get("kind") in INSIGHT_KINDS else infer_kind(statement, item.get("metric"))
    effect = item.get("effect_size")
    effect = parse_effect(effect if effect is not None else item.get("effect"))
    evidence = {"source": "ai", "evidence_ids": [str(x) for x in (item.get("evidence_ids") or [])][:50],
                "effect_text": item.get("effect"), "platforms": list(item.get("platforms") or []), "early_signal": early}
    return {"kind": kind, "statement": statement[:1000], "metric": item.get("metric"),
            "effect_size": effect if effect is None or abs(effect) < 1e5 else None, "n": n,
            "confidence": confidence_label(item.get("confidence"), n), "early_signal": early, "evidence": evidence}


def normalize_agent_recommendation(item: dict[str, Any]) -> dict[str, Any] | None:
    action = str(item.get("action") or "").strip()
    if not action:
        return None
    pr = str(item.get("priority") or "medium").lower()
    priority = pr if pr in ("p0", "p1", "p2", "p3") else AI_PRIORITY.get(pr, "p2")
    links_to = item.get("links_to")
    target: dict[str, Any] = {}
    if isinstance(item.get("target"), dict):
        target.update(item["target"])
    elif item.get("target") is not None:
        key = {"pillar": "pillar_id", "time": "time_slot", "timing": "time_slot"}.get(str(links_to or ""), str(links_to or "target"))
        target[key] = item["target"]
    if links_to:
        target.setdefault("links_to", links_to)
    return {"action": action[:1000], "rationale": (item.get("rationale") or None), "expected_impact": item.get("expected_impact"),
            "priority": priority, "target": target, "insight_id": item.get("insight_id"),
            "insight_index": item.get("insight_index"), "kind": infer_kind(action, None, links_to)}


# ================================================================================================ DB helpers
def _uuid(v: Any, field: str = "id") -> UUID:
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except (TypeError, ValueError) as e:
        raise validation(f"Invalid {field}", [{"code": "invalid_uuid", "field": field, "message": str(v)}]) from e


def _user_id(member: Any) -> UUID | None:
    return getattr(getattr(member, "user", None), "id", None)


def _actor(member: Any) -> dict[str, Any]:
    uid = _user_id(member)
    return {"type": "user", "id": str(uid)} if uid else {"type": "system"}


async def audit_safe(db: AsyncSession, member: Any, action: str, target_type: str, target_id: Any,
                     before: Any = None, after: Any = None) -> None:
    if member is None:
        return
    try:
        from app.services.audit_service import audit
    except ImportError:
        return
    try:
        async with db.begin_nested():
            await audit(db, member, action, target_type, target_id, before=before, after=after)
    except Exception as e:  # noqa: BLE001 - audit must never break the domain write
        log.warning("audit.failed", action=action, error=str(e)[:200])


async def notify_admins(db: AsyncSession, workspace_id: UUID, kind: str, title: str, body: str | None, link: str | None,
                        *, severity: str = "info", payload: dict[str, Any] | None = None) -> int:
    """In-app notification to every owner/admin of the workspace (best effort, SAVEPOINT-isolated)."""
    try:
        from app.services.notification_service import NotificationService
    except ImportError:
        return 0
    uids = (await db.execute(select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.role.in_([MemberRole.owner, MemberRole.admin])))).scalars().all()
    sent = 0
    for uid in uids:
        try:
            async with db.begin_nested():
                await NotificationService.notify(db, workspace_id, kind, title, body, link, user_id=uid, severity=severity,
                                                 channels=["in_app"], payload=payload)
            sent += 1
        except Exception as e:  # noqa: BLE001
            log.warning("notify.failed", kind=kind, error=str(e)[:200])
    return sent


async def ai_configured(db: AsyncSession | None, workspace_id: UUID | None, tier: str = "powerful",
                        agent_id: str | None = None) -> bool:
    """True when some provider can serve ``tier``/``agent_id``: a routed model with a usable key, any provider that has a
    key, or a key-less fallback (local Ollama, FREE_FALLBACK_MODELS). No network calls."""
    try:
        from app.integrations.ai.registry import ai_available
    except ImportError:
        return False
    return await ai_available(db, workspace_id, tier, agent_id)


async def start_tool_run(db: AsyncSession, member: Any, *, agent: str, action: str, message: str, brand_id: UUID | None,
                         inputs: dict[str, Any]) -> Any:
    """``AIService.create_run(mode="tool")`` with the job deferred **in the caller's transaction** (the worker can't
    pick the run up before the row is committed); falls back to the service's own out-of-transaction enqueue."""
    from app.agents.orchestrator.service import AIService
    run = await AIService().create_run(db, member, message=message, brand_id=brand_id, mode="tool", agent=agent,
                                       action=action, inputs=inputs, enqueue=False)
    try:
        from app.workers.queue import AlreadyEnqueued, defer_in_txn
        try:
            await defer_in_txn(db, "jobs.ai.run", queue="ai", queueing_lock=f"ai:{run.id}",
                               args={"run_id": str(run.id), "workspace_id": str(run.workspace_id)})
        except AlreadyEnqueued:
            pass
    except Exception as e:  # noqa: BLE001 - e.g. queue schema missing: fall back to the plain enqueue
        log.warning("ai_run.defer_in_txn_failed", run_id=str(run.id), error=str(e)[:200])
        from app.agents.orchestrator.service import enqueue_job
        await enqueue_job("jobs.ai.run", run.id, run.workspace_id)
    return run


async def competitor_deltas(db: AsyncSession, workspace_id: UUID, brand_id: UUID, since: datetime, until: datetime
                            ) -> list[dict[str, Any]]:
    """Per competitor profile: first vs last snapshot in the window (posts/week, followers, avg engagement). With fewer
    than two snapshots the "before" values stay ``None`` — a single snapshot is not a zero change."""
    comps = (await db.execute(select(Competitor).where(Competitor.workspace_id == workspace_id,
                                                       Competitor.brand_id == brand_id,
                                                       Competitor.status != "archived"))).scalars().unique().all()
    out: list[dict[str, Any]] = []
    for comp in comps:
        for prof in comp.profiles:
            snaps = (await db.execute(select(CompetitorSnapshot).where(
                CompetitorSnapshot.workspace_id == workspace_id, CompetitorSnapshot.profile_id == prof.id,
                CompetitorSnapshot.captured_at >= since - timedelta(days=7), CompetitorSnapshot.captured_at <= until)
                .order_by(CompetitorSnapshot.captured_at.asc()))).scalars().all()
            platform = getattr(prof.platform, "value", prof.platform) or prof.kind
            entry: dict[str, Any] = {"competitor_id": str(comp.id), "name": comp.name, "profile_id": str(prof.id),
                                     "platform": platform, "handle": prof.handle,
                                     "availability": getattr(prof.availability, "value", prof.availability),
                                     "snapshots": len(snaps), "snapshot_ids": [str(s.id) for s in snaps[-5:]]}
            if not snaps:
                entry.update({"posts_per_week": {"before": None, "after": None}, "followers": {"before": None, "after": None},
                              "avg_engagement": {"before": None, "after": None}, "posts_last_30d": None})
                out.append(entry)
                continue
            first, last = snaps[0], snaps[-1]
            two = len(snaps) >= 2

            def ppw(s: CompetitorSnapshot) -> float | None:
                if s.posts_last_7d is not None:
                    return float(s.posts_last_7d)
                if s.posts_last_30d is not None:
                    return round(s.posts_last_30d * 7 / 30, 1)
                return None

            def eng(s: CompetitorSnapshot) -> float | None:
                return float(s.avg_engagement) if s.avg_engagement is not None else None

            entry.update({
                "first_captured_at": first.captured_at.isoformat(), "last_captured_at": last.captured_at.isoformat(),
                "posts_per_week": {"before": ppw(first) if two else None, "after": ppw(last)},
                "followers": {"before": first.followers_count if two else None, "after": last.followers_count},
                "avg_engagement": {"before": eng(first) if two else None, "after": eng(last)},
                "posts_last_30d": last.posts_last_30d,
            })
            out.append(entry)
    return out


# ================================================================================================ service
class InsightService:
    """Runs the analysis loop and owns ``insights`` / ``recommendations``."""

    # -------------------------------------------------------------------------------------- evidence
    @classmethod
    async def _brand(cls, db: AsyncSession, workspace_id: UUID, brand_id: Any) -> Brand:
        bid = _uuid(brand_id, "brand_id")
        brand = (await db.execute(select(Brand).where(Brand.id == bid, Brand.workspace_id == workspace_id,
                                                      Brand.deleted_at.is_(None)))).scalar_one_or_none()
        if brand is None:
            raise not_found("Brand")
        return brand

    @classmethod
    async def build_evidence_pack(cls, db: AsyncSession, workspace_id: UUID, brand_id: Any, period_days: int = 30, *,
                                  metric: str = DEFAULT_METRIC, now: datetime | None = None) -> dict[str, Any]:
        brand = await cls._brand(db, workspace_id, brand_id)
        tz = await brand_tz(db, brand.id)
        now = now or datetime.now(UTC)
        since = now - timedelta(days=period_days)
        rows = await post_rows(db, workspace_id, brand_id=brand.id, since=since, until=now)
        labels = {"pillar": await labels_for(db, workspace_id, "pillar")}
        comps = await competitor_deltas(db, workspace_id, brand.id, since, now)
        period = {"start": since.astimezone(tz).date().isoformat(), "end": now.astimezone(tz).date().isoformat(),
                  "days": period_days}
        return evidence_pack_from_rows(rows, metric=metric, tz=tz, labels=labels, period=period, competitor_deltas=comps,
                                       brand={"id": str(brand.id), "name": brand.name, "timezone": brand.timezone}, now=now)

    # -------------------------------------------------------------------------------------- analyze
    @classmethod
    async def analyze(cls, db: AsyncSession, member: Any, brand_id: Any, period_days: int = 30, *, mode: str = "auto",
                      metric: str = DEFAULT_METRIC) -> dict[str, Any]:
        """→ ``{"mode": "ai", "run_id", ...}`` (AI configured) or ``{"mode": "deterministic", "insights_created", ...}``."""
        if not 1 <= int(period_days) <= 365:
            raise validation("period_days must be between 1 and 365")
        if mode not in ("auto", "deterministic", "ai"):
            raise validation("mode must be auto, deterministic or ai")
        ws = member.workspace_id
        brand = await cls._brand(db, ws, brand_id)
        pack = await cls.build_evidence_pack(db, ws, brand.id, int(period_days), metric=metric)
        use_ai = mode != "deterministic" and await ai_configured(db, ws, "powerful", "performance_analyst")
        if mode == "ai" and not use_ai:
            raise ProblemError(409, "ai_not_configured", "AI is not configured",
                               "No AI provider key is configured for the performance analyst; use mode=auto.")
        if use_ai:
            try:
                inputs = {"brand_id": str(brand.id), "period_days": int(period_days), "period": pack["period"],
                          "metric": metric, "dimensions": ["format", "pillar", "platform", "timing", "competitor"],
                          "evidence_pack": pack, "fallback": "deterministic"}
                async with db.begin_nested():     # a failed start leaves no dangling queued run behind
                    run = await start_tool_run(db, member, agent="performance_analyst", action="analyze", brand_id=brand.id,
                                               message=f"Analyze {brand.name}'s performance over the last {period_days} days",
                                               inputs=inputs)
                await audit_safe(db, member, "insights.analyze", "brand", brand.id,
                                 after={"mode": "ai", "run_id": str(run.id), "period_days": period_days})
                return {"mode": "ai", "run_id": run.id, "status": "queued", "status_url": f"/api/v1/ai/runs/{run.id}",
                        "period": pack["period"], "data_notes": pack["data_notes"]}
            except ProblemError as e:
                if mode == "ai" or e.status_code in (402, 403):
                    raise
                log.warning("insights.ai_start_failed", error=str(e.detail)[:200])
            except Exception as e:  # noqa: BLE001 - never leave the user without an analysis
                if mode == "ai":
                    raise
                log.warning("insights.ai_start_failed", error=str(e)[:200])
        res = await cls.write_deterministic(db, ws, brand.id, pack, member=member)
        await audit_safe(db, member, "insights.analyze", "brand", brand.id,
                         after={"mode": "deterministic", "period_days": period_days,
                                "insights_created": res["insights_created"],
                                "recommendations_created": res["recommendations_created"]})
        return res

    @classmethod
    async def _exists(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, statement: str, period_end: date) -> bool:
        row = (await db.execute(select(Insight.id).where(
            Insight.workspace_id == workspace_id, Insight.brand_id == brand_id, Insight.statement == statement,
            Insight.period_end == period_end, Insight.status != "dismissed").limit(1))).first()
        return row is not None

    @classmethod
    async def write_deterministic(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, pack: dict[str, Any], *,
                                  member: Any = None, ai_run_id: UUID | None = None) -> dict[str, Any]:
        insights, recs = derive_insights(pack)
        period = pack.get("period") or {}
        ps = date.fromisoformat(period["start"]) if period.get("start") else datetime.now(UTC).date()
        pe = date.fromisoformat(period["end"]) if period.get("end") else datetime.now(UTC).date()
        created: list[Insight] = []
        index_map: dict[int, Insight] = {}
        for i, ins in enumerate(insights):
            if await cls._exists(db, workspace_id, brand_id, ins["statement"], pe):
                continue
            row = Insight(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, period_start=ps, period_end=pe,
                          statement=ins["statement"], kind=ins["kind"], metric=ins.get("metric"),
                          effect_size=ins.get("effect_size"), n=ins.get("n"), confidence=ins["confidence"],
                          evidence=_jsonable(ins.get("evidence") or {}), ai_run_id=ai_run_id, status="new",
                          created_at=datetime.now(UTC))
            db.add(row)
            created.append(row)
            index_map[i] = row
        rec_rows: list[Recommendation] = []
        for rec in recs:
            ins_row = index_map.get(rec["insight_index"])
            if ins_row is None:
                continue
            r = Recommendation(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, insight_id=ins_row.id,
                               action=rec["action"], rationale=rec["rationale"], expected_impact=rec["expected_impact"],
                               priority=rec["priority"], target=_jsonable({**rec["target"], "source": "deterministic"}),
                               status="proposed", created_at=datetime.now(UTC))
            db.add(r)
            rec_rows.append(r)
        await db.flush()
        await cls._announce(db, workspace_id, brand_id, created, rec_rows, mode="deterministic", member=member,
                            run_id=ai_run_id, period=period)
        return {"mode": "deterministic", "insights_created": len(created), "recommendations_created": len(rec_rows),
                "insight_ids": [r.id for r in created], "recommendation_ids": [r.id for r in rec_rows],
                "period": period, "data_notes": pack.get("data_notes", []), "coverage": pack.get("coverage")}

    @classmethod
    async def _announce(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, insights: list[Insight],
                        recs: list[Recommendation], *, mode: str, member: Any = None, run_id: Any = None,
                        period: dict[str, Any] | None = None) -> None:
        actor = _actor(member) if member is not None else ({"type": "agent", "id": "performance_analyst"} if run_id else None)
        await emit(db, "AI_ANALYSIS_COMPLETED", {"brand_id": str(brand_id), "mode": mode,
                                                 "run_id": str(run_id) if run_id else None,
                                                 "insight_ids": [str(i.id) for i in insights],
                                                 "recommendation_ids": [str(r.id) for r in recs], "period": period or {}},
                   workspace_id=workspace_id, actor=actor)
        for r in recs:
            await emit(db, "RECOMMENDATION_CREATED", {"recommendation_id": str(r.id), "brand_id": str(brand_id),
                                                      "insight_id": str(r.insight_id) if r.insight_id else None,
                                                      "priority": r.priority, "action": r.action[:300]},
                       workspace_id=workspace_id, actor=actor)
        if insights or recs:
            body = "; ".join(i.statement for i in insights[:3])
            await notify_admins(db, workspace_id, "insights_ready",
                                f"{len(insights)} new insight(s), {len(recs)} recommendation(s)", body[:900] or None,
                                f"/analytics?brand_id={brand_id}&tab=insights", severity="info",
                                payload={"brand_id": str(brand_id), "insight_ids": [str(i.id) for i in insights][:20],
                                         "recommendation_ids": [str(r.id) for r in recs][:20]})

    # -------------------------------------------------------------------------------------- persistence for AI output
    @classmethod
    async def save_insights(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, items: list[dict[str, Any]], *,
                            ai_run_id: UUID | None, period: dict[str, Any] | None = None) -> list[Insight]:
        period = period or {}
        today = datetime.now(UTC).date()
        ps = date.fromisoformat(period["start"]) if period.get("start") else today - timedelta(days=30)
        pe = date.fromisoformat(period["end"]) if period.get("end") else today
        rows: list[Insight] = []
        for raw in items or []:
            ins = normalize_agent_insight(raw if isinstance(raw, dict) else {})
            if ins is None:
                continue
            row = Insight(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, period_start=ps, period_end=pe,
                          statement=ins["statement"], kind=ins["kind"], metric=ins.get("metric"),
                          effect_size=ins.get("effect_size"), n=ins.get("n"), confidence=ins["confidence"],
                          evidence=_jsonable(ins["evidence"]), ai_run_id=ai_run_id, status="new",
                          created_at=datetime.now(UTC))
            db.add(row)
            rows.append(row)
        await db.flush()
        return rows

    @classmethod
    async def save_recommendations(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, items: list[dict[str, Any]],
                                   *, ai_run_id: UUID | None, insights: list[Insight] | None = None) -> list[Recommendation]:
        insights = insights or []
        if not insights and ai_run_id is not None:
            insights = list((await db.execute(select(Insight).where(Insight.workspace_id == workspace_id,
                                                                    Insight.ai_run_id == ai_run_id))).scalars())
        by_kind: dict[str, list[Insight]] = defaultdict(list)
        for i in insights:
            by_kind[i.kind].append(i)
        rows: list[Recommendation] = []
        for raw in items or []:
            rec = normalize_agent_recommendation(raw if isinstance(raw, dict) else {})
            if rec is None:
                continue
            insight_id: UUID | None = None
            if rec.get("insight_id"):
                try:
                    cand = UUID(str(rec["insight_id"]))
                    owned = (await db.execute(select(Insight.id).where(Insight.id == cand, Insight.workspace_id == workspace_id))).first()
                    insight_id = cand if owned else None
                except ValueError:
                    insight_id = None
            if insight_id is None and isinstance(rec.get("insight_index"), int) and 0 <= rec["insight_index"] < len(insights):
                insight_id = insights[rec["insight_index"]].id
            if insight_id is None and len(by_kind.get(rec["kind"], [])) == 1:
                insight_id = by_kind[rec["kind"]][0].id
            target = dict(rec["target"])
            if ai_run_id is not None:
                target["ai_run_id"] = str(ai_run_id)
            r = Recommendation(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, insight_id=insight_id,
                               action=rec["action"], rationale=rec["rationale"], expected_impact=rec["expected_impact"],
                               priority=rec["priority"], target=_jsonable(target), status="proposed",
                               created_at=datetime.now(UTC))
            db.add(r)
            rows.append(r)
        await db.flush()
        return rows

    @staticmethod
    def output_from_run(run: Any) -> dict[str, Any] | None:
        """The ``Insights`` dict from a completed run's deliverables (tool mode → ``t1``; other modes → first match)."""
        deliverables = ((run.result or {}).get("deliverables") or {}) if run is not None else {}
        for val in deliverables.values():
            if isinstance(val, dict) and isinstance(val.get("insights"), list):
                return val
        return None

    @classmethod
    async def apply_agent_output(cls, db: AsyncSession, run: Any, output: dict[str, Any] | Any | None = None) -> dict[str, Any]:
        """Persist a ``performance_analyst`` ``Insights`` output (idempotent per run: rows already saved by the
        ``insights.save`` / ``recommendations.save`` tools are not duplicated)."""
        if output is not None and hasattr(output, "model_dump"):
            output = output.model_dump(mode="json")
        output = output or cls.output_from_run(run)
        if not output:
            return {"applied": False, "reason": "no_output"}
        inputs = ((run.input or {}).get("inputs") or {}) if run is not None else {}
        brand_raw = getattr(run, "brand_id", None) or inputs.get("brand_id")
        if not brand_raw:
            return {"applied": False, "reason": "no_brand"}
        brand_id = _uuid(brand_raw, "brand_id")
        ws = run.workspace_id
        existing = list((await db.execute(select(Insight).where(Insight.workspace_id == ws, Insight.ai_run_id == run.id))).scalars())
        new_insights: list[Insight] = []
        if not existing:
            new_insights = await cls.save_insights(db, ws, brand_id, list(output.get("insights") or []), ai_run_id=run.id,
                                                   period=inputs.get("period"))
        recs_exist = (await db.execute(select(Recommendation.id).where(
            Recommendation.workspace_id == ws, Recommendation.target["ai_run_id"].astext == str(run.id)).limit(1))).first()
        new_recs: list[Recommendation] = []
        if not recs_exist:
            new_recs = await cls.save_recommendations(db, ws, brand_id, list(output.get("recommendations") or []),
                                                      ai_run_id=run.id, insights=existing or new_insights)
        if new_insights or new_recs:
            await cls._announce(db, ws, brand_id, new_insights, new_recs, mode="ai", run_id=run.id,
                                period=inputs.get("period"))
        return {"applied": True, "insights_created": len(new_insights), "recommendations_created": len(new_recs)}

    @classmethod
    async def fallback_after_failed_run(cls, db: AsyncSession, run: Any) -> dict[str, Any]:
        """AI run failed → deterministic insights from the evidence pack stored in the run inputs (once per run)."""
        inputs = ((run.input or {}).get("inputs") or {}) if run is not None else {}
        pack = inputs.get("evidence_pack")
        if inputs.get("fallback") != "deterministic" or not isinstance(pack, dict):
            return {"applied": False}
        exists = (await db.execute(select(Insight.id).where(Insight.workspace_id == run.workspace_id,
                                                            Insight.ai_run_id == run.id).limit(1))).first()
        if exists:
            return {"applied": False, "reason": "already_applied"}
        brand_id = _uuid(run.brand_id or inputs.get("brand_id"), "brand_id")
        return await cls.write_deterministic(db, run.workspace_id, brand_id, pack, ai_run_id=run.id)

    # -------------------------------------------------------------------------------------- reads
    @classmethod
    async def list_insights(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None,
                            kind: str | None = None, status: str | None = None, since: datetime | None = None,
                            limit: int = 50, cursor: str | None = None) -> tuple[list[Insight], str | None]:
        q = select(Insight).where(Insight.workspace_id == workspace_id)
        if brand_id:
            q = q.where(Insight.brand_id == brand_id)
        if kind:
            q = q.where(Insight.kind == kind)
        if status:
            q = q.where(Insight.status == status)
        if since:
            q = q.where(Insight.created_at >= since)
        return await paginate(db, q, Insight, limit, cursor)

    @classmethod
    async def list_recommendations(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None,
                                   status: str | None = None, insight_id: UUID | None = None, limit: int = 50,
                                   cursor: str | None = None) -> tuple[list[Recommendation], str | None]:
        q = select(Recommendation).where(Recommendation.workspace_id == workspace_id)
        if brand_id:
            q = q.where(Recommendation.brand_id == brand_id)
        if status:
            q = q.where(Recommendation.status == status)
        if insight_id:
            q = q.where(Recommendation.insight_id == insight_id)
        return await paginate(db, q, Recommendation, limit, cursor)

    @classmethod
    async def get_insight(cls, db: AsyncSession, workspace_id: UUID, insight_id: Any, *, for_update: bool = False) -> Insight:
        q = select(Insight).where(Insight.id == _uuid(insight_id, "insight_id"), Insight.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        row = (await db.execute(q)).scalar_one_or_none()
        if row is None:
            raise not_found("Insight")
        return row

    @classmethod
    async def get_recommendation(cls, db: AsyncSession, workspace_id: UUID, rec_id: Any, *, for_update: bool = False
                                 ) -> Recommendation:
        q = select(Recommendation).where(Recommendation.id == _uuid(rec_id, "recommendation_id"),
                                         Recommendation.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        row = (await db.execute(q)).scalar_one_or_none()
        if row is None:
            raise not_found("Recommendation")
        return row

    @classmethod
    async def insights_in_period(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, start: date, end: date,
                                 limit: int = 20) -> list[Insight]:
        q = select(Insight).where(Insight.workspace_id == workspace_id, Insight.brand_id == brand_id,
                                  Insight.status != "dismissed",
                                  or_(and_(Insight.period_end >= start, Insight.period_start <= end),
                                      and_(Insight.created_at >= datetime.combine(start, datetime.min.time(), UTC),
                                           Insight.created_at < datetime.combine(end + timedelta(days=1),
                                                                                 datetime.min.time(), UTC))))
        return list((await db.execute(q.order_by(Insight.created_at.desc()).limit(limit))).scalars())

    # -------------------------------------------------------------------------------------- decisions
    @classmethod
    async def acknowledge_insight(cls, db: AsyncSession, member: Any, insight_id: Any, status: str = "acknowledged") -> Insight:
        if status not in ("acknowledged", "dismissed", "new"):
            raise validation("status must be acknowledged, dismissed or new")
        ins = await cls.get_insight(db, member.workspace_id, insight_id, for_update=True)
        before = ins.status
        if before != status:
            ins.status = status
            await db.flush()
            await audit_safe(db, member, f"insight.{'acknowledge' if status == 'acknowledged' else status}", "insight",
                             ins.id, before={"status": before}, after={"status": status})
        return ins

    @classmethod
    async def decide_recommendation(cls, db: AsyncSession, member: Any, rec_id: Any, status: str,
                                    reason: str | None = None) -> Recommendation:
        if status not in ("accepted", "rejected"):
            raise validation("status must be accepted or rejected")
        rec = await cls.get_recommendation(db, member.workspace_id, rec_id, for_update=True)
        if rec.status == status:
            return rec
        if rec.status == "applied":
            raise conflict("recommendation_applied", "The recommendation was already applied")
        before = {"status": rec.status}
        rec.status = status
        rec.decided_by = _user_id(member)
        rec.decided_at = datetime.now(UTC)
        applied: dict[str, Any] = dict(rec.applied_to or {})
        if reason:
            applied["reason"] = reason[:1000]
        insight = await db.get(Insight, rec.insight_id) if rec.insight_id else None
        if status == "accepted":
            run_id = await cls._enqueue_ideation(db, member, rec, insight)
            if run_id:
                applied["ideation_run_id"] = str(run_id)
        memory_id = await cls._remember_decision(db, member, rec, insight, status, reason)
        if memory_id:
            applied["memory_id"] = memory_id
        rec.applied_to = applied or None
        await db.flush()
        await audit_safe(db, member, f"recommendation.{'accept' if status == 'accepted' else 'reject'}", "recommendation",
                         rec.id, before=before, after={"status": status, "applied_to": applied})
        return rec

    @classmethod
    async def _enqueue_ideation(cls, db: AsyncSession, member: Any, rec: Recommendation, insight: Insight | None) -> Any:
        """Accepted recommendation → ``ContentService.generate_ideas(from={insight_ids})`` when AI is configured."""
        try:
            from app.services.content_service import ContentService
        except ImportError:
            return None
        if not hasattr(ContentService, "generate_ideas"):
            return None
        if not await ai_configured(db, member.workspace_id, "cheap", "ideation"):
            return None
        try:
            async with db.begin_nested():
                out = await ContentService.generate_ideas(
                    db, member, brand_id=rec.brand_id, count=5,
                    from_={"insight_ids": [str(insight.id)] if insight else [], "recommendation_id": str(rec.id),
                           "prompt": f"Ideas that act on this recommendation: {rec.action}"
                                     + (f" Evidence: {insight.statement}" if insight else "")})
            return (out or {}).get("run_id") if isinstance(out, dict) else getattr(out, "id", None)
        except Exception as e:  # noqa: BLE001 - acceptance must succeed even if ideation can't start
            log.warning("recommendation.ideation_failed", recommendation_id=str(rec.id), error=str(e)[:200])
            return None

    @classmethod
    async def _remember_decision(cls, db: AsyncSession, member: Any, rec: Recommendation, insight: Insight | None,
                                 status: str, reason: str | None) -> str | None:
        """``memories(kind=performance)`` note through MemoryService (embeddings skipped when no key is configured)."""
        try:
            from app.agents.orchestrator.memory import MemoryService
        except ImportError:
            return None
        verb = "Accepted" if status == "accepted" else "Rejected"
        text = f"{verb} recommendation: {rec.action}"
        if insight is not None:
            text += f"\nEvidence: {insight.statement} (confidence {insight.confidence}, n={insight.n})"
        if reason:
            text += f"\nReason: {reason[:500]}"
        conf = insight.confidence if insight is not None else "medium"
        importance = {"high": 0.8, "medium": 0.65, "low": 0.5}.get(conf, 0.6) if status == "accepted" else 0.4
        svc = MemoryService()
        if not await _embeddings_available(db, member.workspace_id):
            async def _no_embed(*_a: Any, **_k: Any) -> None:
                return None
            svc.embed = _no_embed  # type: ignore[method-assign]
        try:
            async with db.begin_nested():
                mem = await svc.remember(db, member.workspace_id, "performance", text, brand_id=rec.brand_id,
                                         user_id=_user_id(member), importance=importance,
                                         source_ref={"recommendation_id": str(rec.id),
                                                     "insight_id": str(insight.id) if insight else None,
                                                     "decision": status})
            return str(mem.get("id")) if isinstance(mem, dict) else None
        except Exception as e:  # noqa: BLE001
            log.warning("recommendation.memory_failed", recommendation_id=str(rec.id), error=str(e)[:200])
            return None


async def _embeddings_available(db: AsyncSession, workspace_id: UUID) -> bool:
    try:
        from app.integrations.embeddings.registry import get_embedding_provider
        prov = await get_embedding_provider(db, workspace_id)
    except Exception:  # noqa: BLE001
        return False
    if getattr(prov, "name", "") in ("openai", "google") and not getattr(prov, "_api_key", "set"):
        return False
    return True


async def paginate(db: AsyncSession, q: Any, model: Any, limit: int, cursor: str | None) -> tuple[list[Any], str | None]:
    limit = max(1, min(int(limit), 200))
    c = decode_cursor(cursor)
    if c and c.get("t") and c.get("id"):
        t = datetime.fromisoformat(c["t"])
        q = q.where(or_(model.created_at < t, and_(model.created_at == t, model.id < UUID(c["id"]))))
    rows = list((await db.execute(q.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))).scalars())
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = encode_cursor({"t": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)})
    return rows, nxt


def _jsonable(v: Any) -> Any:
    import json
    return json.loads(json.dumps(v, default=str))


__all__ = ["InsightService", "derive_insights", "evidence_pack_from_rows", "confidence_for_n", "ai_configured",
           "competitor_deltas", "start_tool_run", "notify_admins", "audit_safe", "normalize_agent_insight",
           "normalize_agent_recommendation", "parse_effect", "infer_kind", "paginate"]
