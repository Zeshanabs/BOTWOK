"""Deterministic statistics for the performance_analyst tools (doc 13 §13.5) — numpy only.

* ``mann_whitney_u`` with tie correction and normal approximation (two-sided p-value).
* ``bootstrap_ci`` percentile CI for the mean.
* ``compare_groups``, ``time_of_day``, ``trend``, ``top_posts`` operate on the row dicts from ``analytics.queries``.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from app.analytics.queries import group_key, metric_value

MIN_N = 5


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def mann_whitney_u(a: list[float], b: list[float]) -> dict[str, Any]:
    """Two-sided Mann–Whitney U (normal approximation with tie correction; exact enough for n ≥ 8 per group)."""
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return {"u": None, "p_value": None, "n1": n1, "n2": n2}
    allv = np.concatenate([x, y])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv), dtype=float)
    sorted_vals = allv[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    r1 = ranks[:n1].sum()
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u = min(u1, u2)
    mu = n1 * n2 / 2
    _, counts = np.unique(allv, return_counts=True)
    n = n1 + n2
    tie_term = (counts ** 3 - counts).sum() / (n * (n - 1)) if n > 1 else 0.0
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - tie_term)) if n > 1 else 0.0
    if sigma == 0:
        p = 1.0
    else:
        z = (u - mu + 0.5) / sigma   # continuity correction
        p = min(1.0, 2 * _norm_sf(abs(z)))
    return {"u": float(u), "p_value": round(float(p), 5), "n1": n1, "n2": n2, "effect_r": round(float(abs((u - mu) / sigma)) / math.sqrt(n), 4) if sigma else None}


def bootstrap_ci(values: list[float], *, iters: int = 2000, alpha: float = 0.05, seed: int = 7) -> tuple[float | None, float | None]:
    arr = np.asarray(values, dtype=float)
    if len(arr) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(iters, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return round(float(lo), 5), round(float(hi), 5)


def compare_groups(rows: list[dict[str, Any]], metric: str, group_by: str, *, tz: ZoneInfo | None = None, labels: dict[str, str] | None = None,
                   min_n: int = MIN_N) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = metric_value(r, metric)
        if v is None:
            continue
        groups[group_key(r, group_by, tz) or "(none)"].append(v)
    allv = [v for vs in groups.values() for v in vs]
    overall = float(np.mean(allv)) if allv else None
    out = []
    for key, vals in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        rest = [v for k2, vs in groups.items() if k2 != key for v in vs]
        mw = mann_whitney_u(vals, rest) if rest else {"p_value": None}
        lo, hi = bootstrap_ci(vals)
        mean = float(np.mean(vals))
        out.append({"key": key, "label": (labels or {}).get(key, key), "n": len(vals), "mean": round(mean, 5), "median": round(float(np.median(vals)), 5),
                    "ci95": [lo, hi], "effect_vs_overall": round(mean / overall, 3) if overall else None, "p_value": mw.get("p_value"), "min_n_ok": len(vals) >= min_n})
    return {"metric": metric, "group_by": group_by, "overall_mean": round(overall, 5) if overall is not None else None, "n": len(allv), "groups": out,
            "coverage": {"posts": len(rows), "with_metric": len(allv)}}


def time_of_day(rows: list[dict[str, Any]], metric: str, *, tz: ZoneInfo | None = None) -> dict[str, Any]:
    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    for r in rows:
        v = metric_value(r, metric)
        if v is None:
            continue
        local = r["published_at"].astimezone(tz or UTC)
        cells[(local.weekday(), local.hour)].append(v)
    heat = [{"weekday": wd, "hour": h, "n": len(vs), "mean": round(float(np.mean(vs)), 5), "min_n_ok": len(vs) >= 3} for (wd, h), vs in sorted(cells.items())]
    best = sorted([c for c in heat if c["min_n_ok"]], key=lambda c: -c["mean"])[:5]
    return {"metric": metric, "timezone": (tz or UTC).key if hasattr(tz or UTC, "key") else "UTC", "cells": heat, "best": best,
            "coverage": {"posts": len(rows), "with_metric": sum(c["n"] for c in heat)}}


def trend(rows: list[dict[str, Any]], metric: str, *, granularity: str = "week") -> dict[str, Any]:
    series: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = metric_value(r, metric)
        if v is None:
            continue
        at: datetime = r["published_at"].astimezone(UTC)
        key = at.strftime("%Y-%m-%d") if granularity == "day" else (at.strftime("%G-W%V") if granularity == "week" else at.strftime("%Y-%m"))
        series[key].append(v)
    points = [{"period": k, "n": len(vs), "mean": round(float(np.mean(vs)), 5), "sum": round(float(np.sum(vs)), 3)} for k, vs in sorted(series.items())]
    slope = change = None
    if len(points) >= 2:
        y = np.array([p["mean"] for p in points])
        x = np.arange(len(y))
        slope = round(float(np.polyfit(x, y, 1)[0]), 6)
        half = len(points) // 2
        prev, cur = float(np.mean(y[:half])) if half else None, float(np.mean(y[half:]))
        change = round((cur - prev) / prev, 4) if prev else None
    return {"metric": metric, "granularity": granularity, "points": points, "slope": slope, "change_vs_previous": change,
            "coverage": {"posts": len(rows), "with_metric": sum(p["n"] for p in points)}}


def top_posts(rows: list[dict[str, Any]], metric: str, k: int = 10) -> dict[str, Any]:
    scored = [(metric_value(r, metric), r) for r in rows]
    scored = [(v, r) for v, r in scored if v is not None]
    scored.sort(key=lambda t: -t[0])
    return {"metric": metric, "posts": [{"published_post_id": r["published_post_id"], "value": v, "text": (r.get("text") or "")[:200], "title": r.get("title"),
                                         "format": r.get("format"), "pillar_id": r.get("pillar_id"), "platform": r.get("platform"), "url": r.get("external_url"),
                                         "published_at": r["published_at"].isoformat()} for v, r in scored[:k]],
            "coverage": {"posts": len(rows), "with_metric": len(scored)}}
