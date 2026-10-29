# 13 — Analytics Architecture & AI Performance Analysis

## 13.1 Normalized metric model

Platforms expose different metrics under different names, with different windows and latencies. Botwok stores a **common internal model** and records, per platform, which metrics are *available*, *derived*, or *not available*. Missing is `NULL`, never `0`.

`post_metrics` (one row per published post per capture): `published_post_id, platform, captured_at, window (lifetime|day), impressions, reach, views, engaged_views, likes, comments, shares, saves, clicks, link_clicks, profile_clicks, watch_time_s, avg_watch_time_s, completion_rate, follows_from_post, engagement_rate (derived), reposts, replies, quotes, dislikes, raw jsonb, availability jsonb {metric: available|derived|not_available|deprecated}`.

`account_metrics` (daily): `social_account_id, date, followers, followers_delta, following, impressions, reach, views, profile_views, website_clicks, posts_count, engagement_total, raw jsonb, availability jsonb`.

`analytics_snapshots`: materialized aggregates for dashboards: `scope (account|platform|brand|campaign|pillar|format), scope_id, period (day|week|month), period_start, metrics jsonb, computed_at`.

**Engagement rate (normalized):** `(likes + comments + shares + saves + clicks) / denominator`, where denominator = `impressions` if available, else `reach`, else `views`, else `followers` (labeled "per follower"). The chosen denominator is stored with the row (`engagement_rate_basis`) so comparisons across platforms are labeled honestly.

## 13.2 Availability by platform (current, verified where noted; see doc 26 for sources)

| Metric | facebook | instagram | threads | linkedin (org / member) | x | tiktok | youtube | pinterest | gbp |
|---|---|---|---|---|---|---|---|---|---|
| impressions | `post_impressions` (non-unique only; unique metrics removed Jun 2026) | removed Apr 2025 → use `views` | `views` | org ✓ / member ✓ (post analytics since 202604) | `impression_count` (public) | ✗ | Reporting API only (reach reports) | `IMPRESSION` | location-level only |
| reach | replaced by `post_total_media_view_unique` | `reach` | ✗ | org unique impressions / member reach ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| views | `post_media_view` | `views` | `views` | video views | ✗ (impressions) | `view_count` (lifetime) | `views`, `engagedViews` | `PIN_CLICK`/`OUTBOUND_CLICK` | ✗ |
| likes/comments/shares | ✓ | ✓ (`shares` on media) | likes/replies/reposts/quotes | ✓ | public_metrics | ✓ | ✓ | `SAVE` (as "saves") | ✗ |
| saves | ✗ | `saved` | ✗ | member saves ✓ | `bookmark_count` | ✗ | ✗ | `SAVE` | ✗ |
| clicks | `post_clicks` | Story `link_clicks` (Jun 2026) | `link_clicks` UNVERIFIED | clicks ✓ | `url_link_clicks` (owner, ≤30 days) | ✗ | ✗ | outbound clicks | website clicks (location) |
| watch time | video metrics | Reels `ig_reels_avg_watch_time` | ✗ | ✗ | ✗ | ✗ (Business API only) | ✓ Analytics | ✗ | ✗ |
| follower growth | daily `page_follows` | `follower_count` UNVERIFIED | `followers_count` | follower stats (12 mo) | followers via user lookup | `follower_count` (user.info.stats) | `subscribersGained` | `follower_count` | ✗ |
| audience demographics | ✓ | this_week/this_month, ≥100 followers, top 45 | ≥100 followers | org follower demographics | ✗ | ✗ | Analytics (age/gender/geo) | ✗ | ✗ |
| per-post history window | lifetime + daily | lifetime | lifetime | lifetime (post), 12 mo (org) | private metrics ≤ 30 days | lifetime totals only | daily, 48–72 h latency | 90 days | **no per-post** (discontinued 2023) |

## 13.3 Sync (AnalyticsSyncService)

- **Account metrics**: daily per account at a stable hour (brand timezone 03:00), plus on-demand.
- **Post metrics**: decaying cadence after publish: 1 h, 6 h, 24 h, 72 h, 7 d, 14 d, 30 d, then monthly for 6 months (configurable per platform; X private metrics only within 30 days, so the 30-day pull is the last for those).
- **Quota awareness**: each adapter declares costs (YouTube units, X per-read dollars, Meta BUC budget); `BudgetGuard` throttles syncs under `usage_budgets(kind=platform_reads)`.
- **Idempotency**: upsert on `(published_post_id, captured_at::date, window)`; snapshots recomputed incrementally.
- **Failures**: auth → account `expired` + notification; rate-limited → reschedule with `Retry-After`; metric deprecated (platform error code) → mark `availability=deprecated` and continue (never fail the whole sync for one metric).
- Events: `ANALYTICS_SYNC_STARTED`, `ANALYTICS_UPDATED` (with deltas), `ANALYTICS_SYNC_FAILED`.

## 13.4 Analytics dimensions

Queries (`GET /analytics/breakdown?by=…`) group `post_metrics` ⋈ `published_posts` ⋈ `content_variants` ⋈ `content_items` by: account, platform, campaign, post, content pillar, content format, content type, hour/weekday, period. Each response includes `coverage` (how many posts had the metric) and `basis` labels.

## 13.5 AI performance analysis (learning loop)

```
Collect (sync) → Normalize (post_metrics) → Analyze (deterministic stats tools) → Find patterns → AI recommendation
```
Trigger: daily after syncs complete (or on demand `POST /insights/analyze`), when ≥ 8 posts have ≥ 72 h metrics in the period, or weekly regardless (with "early signal" labels).

Deterministic tools the `performance_analyst` must use (it cannot do arithmetic itself):
- `stats.compare_groups(metric, group_by, period)` → per group: n, mean, median, CI95, effect vs overall (ratio), p-value (Mann–Whitney), `min_n_ok`.
- `stats.time_of_day(metric)` → weekday×hour heatmap with n per cell.
- `stats.trend(metric, period, granularity)` → slope, change vs previous period.
- `stats.top_posts(metric, k)` → ids with text/format/pillar.
- `competitors.delta(period)` → competitor frequency/follower changes.

Outputs:
- `insights`: `brand_id, period_start, period_end, statement, kind (format|pillar|timing|topic|platform|competitor|audience), metric, effect_size, n, confidence (low|medium|high), evidence jsonb (tool call ids, post ids), ai_run_id, status (new|acknowledged|dismissed)`.
- `recommendations`: `brand_id, insight_id?, action, rationale, expected_impact, priority (p0–p3), target (pillar_id|format|time_slot|topic|platform), status (proposed|accepted|rejected|applied), applied_to (idea ids / strategy version)`.

Example statements the system can truthfully produce (numbers from tools): "Carousel posts performed 42% better than static images (n=23 vs 31, CI 18–66%)." "Educational posts generated 2.1× average engagement (n=19)." "Posts published 10:00–12:00 performed best (n=14; early signal)." "Competitor X increased posting frequency from 3 to 7 posts/week."

Acceptance of a recommendation triggers: `ideation.generate(from=insight_ids)` or `strategy.recommend_mix`, writes `memories(kind=performance)` and updates the strategy version; `RECOMMENDATION_CREATED` → notification → Dashboard "What to do next" card.

## 13.6 Reports
`weekly_performance` report (automation template) composes: KPIs vs previous period, top posts, insights, recommendations, competitor deltas, upcoming schedule; delivered by email/Slack/in-app; stored in `reports` with the rendered object key.
