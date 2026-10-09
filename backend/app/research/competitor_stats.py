"""Deterministic competitor statistics — ``stats.describe`` (doc 08 §8.4). Pure functions over post-like objects so they
can be unit-tested without a database.

Engagement is reported only when counts exist (``None`` + "not available" otherwise) and never derived for sources whose
policy forbids derived metrics (YouTube other-channel statistics).
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

_EMOJI_RE = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]")
_CTA_RE = re.compile(r"\b(link in bio|shop now|buy now|sign up|signup|register|subscribe|learn more|download|book (a|your)|"
                     r"get started|try (it|for) free|order now|join (us|now)|dm us|comment below|tap the link|swipe up|"
                     r"read more|contact us|save this|share this)\b", re.I)
_URL_RE = re.compile(r"https?://\S+")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FREQ_ALERT_PCT = 50.0


def _get(p: Any, key: str, default: Any = None) -> Any:
    if isinstance(p, Mapping):
        return p.get(key, default)
    return getattr(p, key, default)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _fmt(v: Any) -> str:
    v = getattr(v, "value", v)
    return str(v) if v else "unknown"


def _pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    if old == 0:
        return None if new == 0 else 100.0
    return round((new - old) / old * 100, 1)


def describe_posts(posts: Iterable[Any], *, now: datetime | None = None, followers: int | None = None,
                   previous: Mapping[str, Any] | None = None, allow_derived: bool = True,
                   tz_offset_hours: int = 0) -> dict[str, Any]:
    """Posting frequency (7/30/90 d), hours/days distribution, format mix, caption length distribution, hashtag frequency,
    emoji/CTA presence, link usage, engagement (when counts exist), and changes vs the previous snapshot."""
    now = _aware(now) or datetime.now(UTC)
    rows = list(posts)
    dated = [(p, _aware(_get(p, "posted_at"))) for p in rows]
    in_window = {d: [p for p, t in dated if t is not None and now - t <= timedelta(days=d)] for d in (7, 30, 90)}
    counts = {"7d": len(in_window[7]), "30d": len(in_window[30]), "90d": len(in_window[90]), "total": len(rows),
              "undated": sum(1 for _, t in dated if t is None)}
    cadence = {"per_week_30d": round(counts["30d"] / (30 / 7), 2), "per_week_90d": round(counts["90d"] / (90 / 7), 2)}
    basis = in_window[90] or rows
    hours: Counter[int] = Counter()
    days: Counter[str] = Counter()
    for p in basis:
        t = _aware(_get(p, "posted_at"))
        if t is None:
            continue
        local = t + timedelta(hours=tz_offset_hours)
        hours[local.hour] += 1
        days[WEEKDAYS[local.weekday()]] += 1
    fmt = Counter(_fmt(_get(p, "format")) for p in basis)
    total_fmt = sum(fmt.values()) or 1
    format_mix = {k: round(v / total_fmt, 3) for k, v in fmt.most_common()}
    texts = [(_get(p, "text") or "") for p in basis]
    lengths = [len(t) for t in texts if t]
    caption = None
    if lengths:
        q = statistics.quantiles(lengths, n=4) if len(lengths) >= 2 else [lengths[0]] * 3
        caption = {"mean": round(statistics.fmean(lengths), 1), "median": statistics.median(lengths), "p25": round(q[0], 1),
                   "p75": round(q[2], 1), "min": min(lengths), "max": max(lengths)}
    tags: Counter[str] = Counter()
    for p in basis:
        for t in _get(p, "hashtags") or []:
            tags[str(t).lower().lstrip("#")] += 1
    n = len(basis) or 1
    emoji_share = round(sum(1 for t in texts if _EMOJI_RE.search(t)) / n, 3) if basis else 0.0
    cta_share = round(sum(1 for t in texts if _CTA_RE.search(t)) / n, 3) if basis else 0.0
    link_share = round(sum(1 for p in basis if _URL_RE.search(_get(p, "text") or "") or
                           (_get(p, "url") and _fmt(_get(p, "format")) in ("link", "article"))) / n, 3) if basis else 0.0

    engagement: dict[str, Any] = {"available": False, "reason": "not available"}
    with_counts = [p for p in basis if _get(p, "like_count") is not None or _get(p, "comment_count") is not None]
    if not allow_derived:
        engagement = {"available": False, "reason": "derived metrics not permitted for this source (platform policy)"}
    elif with_counts:
        per_post = [(_get(p, "like_count") or 0) + (_get(p, "comment_count") or 0) + (_get(p, "share_count") or 0)
                    for p in with_counts]
        avg = statistics.fmean(per_post)
        engagement = {"available": True, "posts_with_counts": len(with_counts), "avg_interactions": round(avg, 2),
                      "median_interactions": statistics.median(per_post),
                      "avg_rate": round(avg / followers, 5) if followers else None,
                      "rate_basis": "interactions / followers" if followers else "followers unknown"}
        views = [_get(p, "view_count") for p in with_counts if _get(p, "view_count") is not None]
        if views:
            engagement["avg_views"] = round(statistics.fmean(views), 1)

    changes: dict[str, Any] = {}
    alerts: list[str] = []
    if previous:
        prev7, prev30 = previous.get("posts_last_7d"), previous.get("posts_last_30d")
        changes = {"posts_last_7d_delta": None if prev7 is None else counts["7d"] - int(prev7),
                   "posts_last_30d_delta": None if prev30 is None else counts["30d"] - int(prev30),
                   "posts_last_30d_pct": _pct_change(counts["30d"], prev30),
                   "followers_delta": (followers - int(previous["followers_count"]))
                   if followers is not None and previous.get("followers_count") is not None else None}
        pct = changes["posts_last_30d_pct"]
        if pct is not None and abs(pct) > FREQ_ALERT_PCT:
            alerts.append(f"posting frequency changed {pct:+.0f}% vs previous snapshot")
        prev_mix = previous.get("format_mix") or {}
        new_formats = [f for f in format_mix if f not in prev_mix and f != "unknown"]
        if new_formats and prev_mix:
            alerts.append(f"new format(s): {', '.join(new_formats)}")
    return {
        "computed_at": now.isoformat(),
        "counts": counts,
        "cadence": cadence,
        "posting_hours": {str(h): hours[h] for h in sorted(hours)},
        "posting_days": {d: days[d] for d in WEEKDAYS if days[d]},
        "top_hours": [h for h, _ in hours.most_common(3)],
        "format_mix": format_mix,
        "caption_length": caption,
        "hashtags": {"top": [[t, c] for t, c in tags.most_common(15)], "per_post_avg": round(sum(tags.values()) / n, 2)
                     if basis else 0.0, "unique": len(tags)},
        "emoji_share": emoji_share,
        "cta_share": cta_share,
        "link_share": link_share,
        "engagement": engagement,
        "followers_count": followers,
        "changes": changes,
        "alerts": alerts,
    }


def snapshot_fields(stats: Mapping[str, Any]) -> dict[str, Any]:
    """Map ``describe_posts`` output onto competitor_snapshots columns."""
    eng = stats.get("engagement") or {}
    return {
        "followers_count": stats.get("followers_count"),
        "posts_last_7d": stats["counts"]["7d"],
        "posts_last_30d": stats["counts"]["30d"],
        "avg_engagement": eng.get("avg_interactions") if eng.get("available") else None,
        "format_mix": stats.get("format_mix"),
        "top_hashtags": dict(stats.get("hashtags", {}).get("top", [])),
        "posting_hours": stats.get("posting_hours"),
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_by_jaccard(docs: list[tuple[Any, set[str]]], *, threshold: float = 0.2) -> list[list[int]]:
    """Single-pass agglomerative clustering on keyword sets (centroid = union of top terms). Returns index lists."""
    clusters: list[tuple[set[str], list[int]]] = []
    for i, (_, terms) in enumerate(docs):
        if not terms:
            continue
        best, best_sim = None, 0.0
        for ci, (cterms, _) in enumerate(clusters):
            sim = max(jaccard(terms, cterms), len(terms & cterms) / max(1, min(len(terms), 8)) * 0.5)
            if sim > best_sim:
                best, best_sim = ci, sim
        if best is not None and best_sim >= threshold:
            cterms, members = clusters[best]
            members.append(i)
            counts = Counter(t for m in members for t in docs[m][1])
            clusters[best] = ({t for t, _ in counts.most_common(12)}, members)
        else:
            clusters.append((set(terms), [i]))
    return [m for _, m in clusters]
