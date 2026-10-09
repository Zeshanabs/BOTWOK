"""Per-platform metric normalizers (doc 13 §13.1-13.2).

Every adapter returns platform-shaped raw dicts; these mappers turn them into the common ``post_metrics`` /
``account_metrics`` columns plus an ``availability`` map ``{metric: available|derived|not_available|deprecated}``.
Missing metrics are ``None`` (NULL) — never ``0``. ``engagement_rate`` is derived with basis selection
``impressions → reach → views → followers`` and the chosen basis is returned so dashboards label it honestly.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

POST_METRIC_KEYS: tuple[str, ...] = (
    "impressions", "reach", "views", "engaged_views", "likes", "comments", "shares", "saves", "clicks", "link_clicks",
    "profile_clicks", "watch_time_s", "avg_watch_time_s", "completion_rate", "follows_from_post", "reposts", "replies",
    "quotes", "dislikes",
)
ACCOUNT_METRIC_KEYS: tuple[str, ...] = (
    "followers", "followers_delta", "following", "impressions", "reach", "views", "profile_views", "website_clicks",
    "posts_count", "engagement_total",
)
ENGAGEMENT_NUMERATOR = ("likes", "comments", "shares", "saves", "clicks")
AVAILABLE, DERIVED, NOT_AVAILABLE, DEPRECATED = "available", "derived", "not_available", "deprecated"

Mapper = Callable[[dict[str, Any], str | None, dict[str, Any]], tuple[dict[str, Any], dict[str, str]]]


def _num(v: Any) -> float | int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return None
    if isinstance(v, dict):  # Graph insights value objects {"value": n}
        return _num(v.get("value"))
    return None


def _set(metrics: dict[str, Any], avail: dict[str, str], key: str, value: Any, status: str = AVAILABLE) -> None:
    n = _num(value)
    if n is None:
        avail.setdefault(key, NOT_AVAILABLE)
        metrics.setdefault(key, None)
        return
    metrics[key] = n
    avail[key] = status


def _finish(metrics: dict[str, Any], avail: dict[str, str], keys: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, str]]:
    for k in keys:
        metrics.setdefault(k, None)
        avail.setdefault(k, NOT_AVAILABLE)
    return metrics, avail


def compute_engagement_rate(metrics: dict[str, Any], avail: dict[str, str], followers: Any = None) -> tuple[float | None, str | None]:
    """(likes+comments+shares+saves+clicks) / basis; basis = impressions → reach → views → followers."""
    parts = [metrics.get(k) for k in ENGAGEMENT_NUMERATOR if avail.get(k) in (AVAILABLE, DERIVED) and metrics.get(k) is not None]
    if not parts:
        return None, None
    numerator = float(sum(parts))
    for basis in ("impressions", "reach", "views"):
        d = metrics.get(basis)
        if avail.get(basis) == AVAILABLE and d is not None and float(d) > 0:
            return round(numerator / float(d), 5), basis
    f = _num(followers)
    if f and float(f) > 0:
        return round(numerator / float(f), 5), "followers"
    return None, None


# ----------------------------------------------------------------------------------------------- post mappers
def _facebook_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    ins = raw.get("insights") or {}
    # unique impression/reach metrics removed 2026-06-15 → replacements are the *_media_view family
    _set(m, a, "views", ins.get("post_media_view"))
    _set(m, a, "reach", ins.get("post_total_media_view_unique"))
    a["impressions"] = DEPRECATED if ("post_impressions" in ins or "post_impressions_unique" in ins) else NOT_AVAILABLE
    m["impressions"] = None
    _set(m, a, "clicks", ins.get("post_clicks"))
    _set(m, a, "likes", raw.get("likes"))
    if m.get("likes") is None and isinstance(ins.get("post_reactions_by_type_total"), dict):
        _set(m, a, "likes", sum(_num(v) or 0 for v in ins["post_reactions_by_type_total"].values()))
    _set(m, a, "comments", raw.get("comments"))
    _set(m, a, "shares", raw.get("shares"))
    _set(m, a, "watch_time_s", (ins.get("post_video_view_time") or 0) / 1000 if ins.get("post_video_view_time") else None)
    avg_ms = _num(ins.get("post_video_avg_time_watched"))
    _set(m, a, "avg_watch_time_s", avg_ms / 1000 if avg_ms is not None else None)
    if m.get("views") is None and ins.get("post_video_views") is not None:
        _set(m, a, "views", ins.get("post_video_views"))
    return _finish(m, a, POST_METRIC_KEYS)


def _instagram_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    ins = raw.get("insights") or {}
    fields = raw.get("fields") or {}
    _set(m, a, "views", ins.get("views"))
    a["impressions"] = DEPRECATED   # removed for all versions 2025-04-21 → use views
    m["impressions"] = None
    _set(m, a, "reach", ins.get("reach"))
    _set(m, a, "likes", ins.get("likes") if ins.get("likes") is not None else fields.get("like_count"))
    _set(m, a, "comments", ins.get("comments") if ins.get("comments") is not None else fields.get("comments_count"))
    _set(m, a, "saves", ins.get("saved"))
    _set(m, a, "shares", ins.get("shares"))
    _set(m, a, "reposts", ins.get("reposts"))
    _set(m, a, "replies", ins.get("replies"))
    _set(m, a, "link_clicks", ins.get("link_clicks"))
    _set(m, a, "follows_from_post", ins.get("follows"))
    _set(m, a, "profile_clicks", ins.get("profile_visits"))
    _set(m, a, "avg_watch_time_s", (_num(ins.get("ig_reels_avg_watch_time")) or 0) / 1000 if ins.get("ig_reels_avg_watch_time") is not None else None)
    _set(m, a, "watch_time_s", (_num(ins.get("ig_reels_video_view_total_time")) or 0) / 1000 if ins.get("ig_reels_video_view_total_time") is not None else None)
    if ins.get("reels_skip_rate") is not None:
        sr = _num(ins.get("reels_skip_rate"))
        _set(m, a, "completion_rate", (1 - sr) if sr is not None and sr <= 1 else None, DERIVED)
    for dep in ("plays", "video_views"):
        if dep in ins:
            a.setdefault("views", DEPRECATED)
    return _finish(m, a, POST_METRIC_KEYS)


def _threads_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    ins = raw.get("insights") or {}
    _set(m, a, "views", ins.get("views"))
    _set(m, a, "likes", ins.get("likes"))
    _set(m, a, "replies", ins.get("replies"))
    _set(m, a, "comments", ins.get("replies"), DERIVED)   # replies are the comment analogue
    _set(m, a, "reposts", ins.get("reposts"))
    _set(m, a, "quotes", ins.get("quotes"))
    _set(m, a, "shares", ins.get("shares"))
    _set(m, a, "link_clicks", ins.get("link_clicks"))
    if m.get("shares") is None and (m.get("reposts") is not None or m.get("quotes") is not None):
        _set(m, a, "shares", (m.get("reposts") or 0) + (m.get("quotes") or 0), DERIVED)
    return _finish(m, a, POST_METRIC_KEYS)


def _linkedin_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    org = raw.get("org_stats")
    member = raw.get("member_stats")
    if isinstance(org, dict):
        _set(m, a, "impressions", org.get("impressionCount"))
        _set(m, a, "reach", org.get("uniqueImpressionsCount"))
        _set(m, a, "clicks", org.get("clickCount"))
        _set(m, a, "likes", org.get("likeCount"))
        _set(m, a, "comments", org.get("commentCount"))
        _set(m, a, "shares", org.get("shareCount"))
    elif isinstance(member, dict):
        _set(m, a, "impressions", member.get("IMPRESSION"))
        _set(m, a, "reach", member.get("MEMBERS_REACHED"))
        _set(m, a, "shares", member.get("RESHARE"))
        _set(m, a, "likes", member.get("REACTION"))
        _set(m, a, "comments", member.get("COMMENT"))
        _set(m, a, "saves", member.get("POST_SAVE"))
        _set(m, a, "link_clicks", member.get("LINK_CLICKS"))
        _set(m, a, "follows_from_post", member.get("FOLLOWER_GAINED_FROM_CONTENT"))
        _set(m, a, "profile_clicks", member.get("PROFILE_VIEW_FROM_CONTENT"))
    social = raw.get("social") or {}
    if m.get("likes") is None:
        _set(m, a, "likes", social.get("likes"))
    if m.get("comments") is None:
        _set(m, a, "comments", social.get("comments"))
    return _finish(m, a, POST_METRIC_KEYS)


def _x_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    pub = raw.get("public_metrics") or {}
    priv = raw.get("non_public_metrics") or {}
    org = raw.get("organic_metrics") or {}
    _set(m, a, "impressions", pub.get("impression_count"))
    _set(m, a, "likes", pub.get("like_count"))
    _set(m, a, "replies", pub.get("reply_count"))
    _set(m, a, "comments", pub.get("reply_count"), DERIVED)
    _set(m, a, "reposts", pub.get("retweet_count"))
    _set(m, a, "quotes", pub.get("quote_count"))
    _set(m, a, "saves", pub.get("bookmark_count"))
    if m.get("reposts") is not None or m.get("quotes") is not None:
        _set(m, a, "shares", (m.get("reposts") or 0) + (m.get("quotes") or 0), DERIVED)
    _set(m, a, "link_clicks", priv.get("url_link_clicks") if priv else org.get("url_link_clicks"))
    _set(m, a, "profile_clicks", priv.get("user_profile_clicks") if priv else org.get("user_profile_clicks"))
    if priv.get("url_link_clicks") is not None or priv.get("user_profile_clicks") is not None:
        _set(m, a, "clicks", (_num(priv.get("url_link_clicks")) or 0) + (_num(priv.get("user_profile_clicks")) or 0), DERIVED)
    if raw.get("private_metrics_window_closed"):
        # owner-only metrics are only served for posts created in the last 30 days (doc 27 §27.5)
        for k in ("link_clicks", "profile_clicks", "clicks"):
            if m.get(k) is None:
                a[k] = NOT_AVAILABLE
    return _finish(m, a, POST_METRIC_KEYS)


def _tiktok_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    v = raw.get("video") or {}
    _set(m, a, "views", v.get("view_count"))
    _set(m, a, "likes", v.get("like_count"))
    _set(m, a, "comments", v.get("comment_count"))
    _set(m, a, "shares", v.get("share_count"))
    return _finish(m, a, POST_METRIC_KEYS)


def _youtube_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    st = raw.get("statistics") or {}
    an = raw.get("analytics") or {}
    _set(m, a, "views", st.get("viewCount") if st.get("viewCount") is not None else an.get("views"))
    _set(m, a, "engaged_views", an.get("engagedViews"))
    _set(m, a, "likes", st.get("likeCount") if st.get("likeCount") is not None else an.get("likes"))
    _set(m, a, "comments", st.get("commentCount") if st.get("commentCount") is not None else an.get("comments"))
    _set(m, a, "shares", an.get("shares"))
    _set(m, a, "dislikes", an.get("dislikes"))
    _set(m, a, "follows_from_post", an.get("subscribersGained"))
    minutes = _num(an.get("estimatedMinutesWatched"))
    _set(m, a, "watch_time_s", minutes * 60 if minutes is not None else None)
    _set(m, a, "avg_watch_time_s", an.get("averageViewDuration"))
    pct = _num(an.get("averageViewPercentage"))
    _set(m, a, "completion_rate", pct / 100 if pct is not None else None, DERIVED)
    a["impressions"] = NOT_AVAILABLE   # Reporting API reach reports only (doc 13 §13.2)
    m["impressions"] = None
    return _finish(m, a, POST_METRIC_KEYS)


def _pinterest_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    lt = raw.get("lifetime") or {}
    _set(m, a, "impressions", lt.get("IMPRESSION"))
    _set(m, a, "clicks", lt.get("PIN_CLICK"))
    _set(m, a, "link_clicks", lt.get("OUTBOUND_CLICK"))
    _set(m, a, "saves", lt.get("SAVE"))
    _set(m, a, "comments", lt.get("TOTAL_COMMENTS"))
    _set(m, a, "likes", lt.get("TOTAL_REACTIONS"))
    _set(m, a, "follows_from_post", lt.get("USER_FOLLOW"))
    _set(m, a, "profile_clicks", lt.get("PROFILE_VISIT"))
    _set(m, a, "views", lt.get("VIDEO_MRC_VIEW"))
    _set(m, a, "avg_watch_time_s", (_num(lt.get("VIDEO_AVG_WATCH_TIME")) or 0) / 1000 if lt.get("VIDEO_AVG_WATCH_TIME") is not None else None)
    return _finish(m, a, POST_METRIC_KEYS)


def _gbp_post(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    # per-post insights discontinued 2023-02-20 with no replacement
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    return _finish(m, a, POST_METRIC_KEYS)


POST_MAPPERS: dict[str, Mapper] = {
    "facebook": _facebook_post, "instagram": _instagram_post, "threads": _threads_post, "linkedin": _linkedin_post,
    "x": _x_post, "tiktok": _tiktok_post, "youtube": _youtube_post, "pinterest": _pinterest_post, "gbp": _gbp_post,
}


# -------------------------------------------------------------------------------------------- account mappers
def _facebook_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    ins = raw.get("insights") or {}
    _set(m, a, "followers", raw.get("followers_count"))
    _set(m, a, "views", ins.get("page_media_view"))
    _set(m, a, "reach", ins.get("page_total_media_view_unique"))
    a["impressions"] = DEPRECATED if "page_impressions_unique" in ins else NOT_AVAILABLE
    m["impressions"] = None
    _set(m, a, "followers_delta", ins.get("page_daily_follows_unique") if ins.get("page_daily_follows_unique") is not None else ins.get("page_follows"))
    _set(m, a, "profile_views", ins.get("page_views_total"))
    _set(m, a, "engagement_total", ins.get("page_post_engagements"))
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _instagram_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    ins = raw.get("insights") or {}
    _set(m, a, "followers", raw.get("followers_count"))
    _set(m, a, "following", raw.get("follows_count"))
    _set(m, a, "posts_count", raw.get("media_count"))
    _set(m, a, "reach", ins.get("reach"))
    _set(m, a, "views", ins.get("views"))
    a["impressions"] = DEPRECATED
    m["impressions"] = None
    _set(m, a, "engagement_total", ins.get("total_interactions"))
    _set(m, a, "website_clicks", ins.get("profile_links_taps"))
    a["profile_views"] = DEPRECATED   # removed 2025-01-08
    m["profile_views"] = None
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _threads_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    ins = raw.get("insights") or {}
    _set(m, a, "followers", ins.get("followers_count") if ins.get("followers_count") is not None else raw.get("followers_count"))
    _set(m, a, "views", ins.get("views"))
    _set(m, a, "website_clicks", ins.get("clicks"))
    total = [ins.get(k) for k in ("likes", "replies", "reposts", "quotes") if _num(ins.get(k)) is not None]
    if total:
        _set(m, a, "engagement_total", sum(_num(x) or 0 for x in total), DERIVED)
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _linkedin_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    _set(m, a, "followers", raw.get("followers"))
    _set(m, a, "followers_delta", raw.get("followers_gained"))
    _set(m, a, "impressions", raw.get("impressions"))
    _set(m, a, "reach", raw.get("unique_impressions"))
    _set(m, a, "profile_views", raw.get("page_views"))
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _x_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    pm = raw.get("public_metrics") or {}
    _set(m, a, "followers", pm.get("followers_count"))
    _set(m, a, "following", pm.get("following_count"))
    _set(m, a, "posts_count", pm.get("tweet_count"))
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _tiktok_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    u = raw.get("user") or {}
    _set(m, a, "followers", u.get("follower_count"))
    _set(m, a, "following", u.get("following_count"))
    _set(m, a, "posts_count", u.get("video_count"))
    _set(m, a, "engagement_total", u.get("likes_count"))
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _youtube_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    st = raw.get("statistics") or {}
    an = raw.get("analytics") or {}
    _set(m, a, "followers", st.get("subscriberCount"))
    _set(m, a, "views", st.get("viewCount"))
    _set(m, a, "posts_count", st.get("videoCount"))
    gained, lost = _num(an.get("subscribersGained")), _num(an.get("subscribersLost"))
    if gained is not None:
        _set(m, a, "followers_delta", gained - (lost or 0), DERIVED)
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _pinterest_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    _set(m, a, "followers", raw.get("follower_count"))
    _set(m, a, "following", raw.get("following_count"))
    _set(m, a, "views", raw.get("monthly_views"))
    _set(m, a, "posts_count", raw.get("pin_count"))
    an = raw.get("analytics") or {}
    _set(m, a, "impressions", an.get("IMPRESSION"))
    _set(m, a, "engagement_total", an.get("ENGAGEMENT"))
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


def _gbp_account(raw: dict[str, Any], flavor: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    m: dict[str, Any] = {}
    a: dict[str, str] = {}
    d = raw.get("daily") or {}
    imp_keys = ("BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
                "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH")
    imps = [_num(d.get(k)) for k in imp_keys if _num(d.get(k)) is not None]
    if imps:
        _set(m, a, "impressions", sum(imps), DERIVED)
    _set(m, a, "website_clicks", d.get("WEBSITE_CLICKS"))
    return _finish(m, a, ACCOUNT_METRIC_KEYS)


ACCOUNT_MAPPERS: dict[str, Mapper] = {
    "facebook": _facebook_account, "instagram": _instagram_account, "threads": _threads_account,
    "linkedin": _linkedin_account, "x": _x_account, "tiktok": _tiktok_account, "youtube": _youtube_account,
    "pinterest": _pinterest_account, "gbp": _gbp_account,
}


# ------------------------------------------------------------------------------------------------- public API
def normalize_post_metrics(platform: str, raw: dict[str, Any] | None, *, flavor: str | None = None,
                           context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``{"platform", "metrics", "availability", "engagement_rate", "engagement_rate_basis", "raw", "captured_at"}``."""
    raw = raw or {}
    ctx = context or {}
    mapper = POST_MAPPERS.get(platform, _gbp_post)
    metrics, avail = mapper(raw, flavor, ctx)
    er, basis = compute_engagement_rate(metrics, avail, followers=ctx.get("followers"))
    return {"platform": platform, "metrics": metrics, "availability": avail, "engagement_rate": er,
            "engagement_rate_basis": basis, "raw": raw, "captured_at": datetime.now(UTC).isoformat(),
            "window": raw.get("window", "lifetime")}


def normalize_account_metrics(platform: str, raw: dict[str, Any] | None, *, flavor: str | None = None,
                              context: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or {}
    mapper = ACCOUNT_MAPPERS.get(platform, _gbp_account)
    metrics, avail = mapper(raw, flavor, context or {})
    return {"platform": platform, "metrics": metrics, "availability": avail, "raw": raw,
            "captured_at": datetime.now(UTC).isoformat()}
