# 08 — Competitor Intelligence Architecture

## 8.1 Honest premise

Most social platforms **do not** expose competitor analytics through official APIs, and scraping gated surfaces violates their terms. Botwok therefore classifies every competitor data point by **availability class** and designs features around what can be collected lawfully. The UI always shows the class next to the data.

| Class | Meaning | Examples |
|---|---|---|
| **A. Official API** | Read through a licensed platform API | IG Business Discovery (followers, media count, recent posts' likes/comments, Reels views) via Facebook Login; YouTube channel/video statistics; X user lookup + recent search (metered); Threads profile/keyword search (after Meta approval); LinkedIn org follower count only |
| **B. Public web** | Competitor's own website, blog, press pages, RSS, sitemaps; open web pages mentioning them | posting cadence of blog, offers, campaigns, product pages, job posts |
| **C. Search-engine data** | Search provider results/news about the competitor | news mentions, PR, reviews, mentions on forums |
| **D. User-provided** | Data the user pastes/uploads (screenshots, exports, notes) | a competitor's post they saw; a newsletter |
| **E. Not collected** | Gated by platform restrictions | LinkedIn posts of other orgs/members, TikTok other accounts, Facebook other Pages (without PPCA approval), Pinterest other accounts, Instagram Stories of others, any engagement data not exposed |

## 8.2 Data model

- `competitors`: `id, workspace_id, brand_id, name, website, description, industry, tags[], status (active|paused), monitoring_frequency (none|weekly|daily), created_by`
- `competitor_profiles`: one per platform handle: `competitor_id, platform, handle, url, platform_account_id?, availability_class (A|B|C|D|E), last_synced_at, sync_status, followers_count?, media_count?, bio, profile_meta jsonb`
- `competitor_posts`: `profile_id, platform, external_id?, url, posted_at, format, caption/text, hashtags[], mentions[], media_urls[], like_count?, comment_count?, share_count?, view_count?, availability_class, content_hash, embedding, analysis jsonb (hook, pillar, tone, cta, topics)`
- `competitor_snapshots`: periodic metrics per profile: `profile_id, captured_at, followers_count?, posts_last_7d, posts_last_30d, avg_engagement?, format_mix jsonb, top_hashtags jsonb, posting_hours jsonb, raw jsonb`
- `competitor_reports`: `competitor_ids[], kind (single|comparison|monitoring), period, content jsonb, rendered_object_key, ai_run_id`
- Research sources about competitors link via `research_sources.competitor_id` (website pages, news).

## 8.3 Collection per platform (what the sync job actually does)

`jobs.competitors.sync_profile(profile_id)` dispatches to a `CompetitorCollector` per platform:

| Platform | Collector behavior | Class |
|---|---|---|
| Website/blog | Crawl (≤200 pages, 2 levels), RSS discovery, sitemap diff, content-hash change detection → `website_changes`, blog cadence | B |
| Instagram | Business Discovery (`business_discovery.username(x){followers_count,media_count,media{...}}`) through the brand's connected IG account on the Facebook Login path; respects app-level and account-level rate limits; stores last ~25 media with like/comment counts; Reels `view_count` when returned | A |
| Instagram hashtags | Hashtag Search for the competitor's branded hashtags (counts against 30 unique hashtags / 7 days per IG account; returns only last 24 h and no usernames) | A (limited) |
| YouTube | `channels.list(statistics)`, `search.list(channelId, order=date)` (own 100-calls/day bucket since 2026-06; budgeted), `videos.list(contentDetails)` + `videos.batchGetStats` (public views/likes/comments, 1 unit). **YouTube API Services policy:** a non-audited app may store another channel's statistics for at most 30 days and may not compute derived metrics (scores, rankings) from them; Botwok keeps a rolling 30-day window for YouTube competitor stats and labels any comparison as "last 30 days, raw counts" until an Analytics & Reporting audit is passed | A (policy-limited) |
| X | `users/by/username`, `users/:id/tweets` (metered per post read; monthly budget enforced in `usage_budgets`), recent search for brand mentions | A (metered) |
| Threads | profile lookup + keyword search once the app is approved; until then "needs approval" | A (approval) |
| LinkedIn | `organizations` lookup + `networkSizes` (follower count) only; posts not readable | A (minimal) + E for posts |
| Facebook | Only if Page Public Content Access is granted after App Review + Business Verification; otherwise E | A/E |
| TikTok | E (no commercial API for other accounts); user may paste public post URLs/notes (D) | E/D |
| Pinterest | E | E |
| News/mentions | search provider (news), stored as research sources with `competitor_id` | C |

Each collector returns `CollectorResult{items[], snapshot, availability, quota_used}`; the sync job records quota use in `usage_ledger` so paid reads (X) are visible.

## 8.4 Analysis (deterministic first, LLM second)

Deterministic `stats.describe` over `competitor_posts` + snapshots computes: posting frequency per platform (7/30/90-day), posting hours/days distribution, format mix, caption length distribution, hashtag frequency, emoji/CTA presence, link usage, cadence changes vs previous snapshot, engagement rate when counts exist (and `null` + "not available" otherwise).

LLM analysis (`competitor_intel.analyze`) then labels: content pillars, hook patterns (first-line archetypes), tone descriptors, offers/campaigns detected, visual style (from image captions/alt text and, if vision is enabled, thumbnails), audience signals (comment themes where available), strengths, weaknesses, and **opportunities for our brand** (gaps = pillars/topics competitors cover that we don't, or that they cover weakly, scored by audience interest proxies and brand fit).

Output is stored on `competitor_posts.analysis`, `competitor_snapshots`, and the run result; every claim references post ids or source ids.

## 8.5 Dashboard, comparison, reports, monitoring

- **Competitor dashboard** (per competitor): header with profile cards per platform and availability badges; tabs Overview · Posts · Pillars & Hooks · Visual & Tone · Website & Blog · News · Gaps & Opportunities · Reports (wireframe in doc 24).
- **Comparison** (`GET /competitors/compare?ids=`): side-by-side table (frequency, format mix, pillars, hashtags, follower trend, engagement where available) + radar chart; brand included as a column.
- **Reports** (`report.compose(kind=competitor|comparison)`): markdown sections with charts and a sources appendix; exported PDF/HTML; email/Slack delivery via NotificationService.
- **Monitoring automation**: built-in workflow template "Weekly competitor monitoring": cron → sync all profiles → research news → trend delta → `competitor_intel.compare` vs last snapshot → report → notify. Alerts: posting-frequency change > 50%, new campaign/offer detected, follower delta > threshold, new blog post, website change on key pages.

## 8.6 Content gap detection (how it actually works)

1. Build topic vectors: embed our last 90 days of content (`content_items`) and each competitor's posts/pages.
2. Cluster all into topics (shared space); compute per-topic coverage: `ours`, `theirs(per competitor)`, `audience_interest` proxy (engagement where available, else source credibility × mention frequency × trend score).
3. Gaps = topics with `theirs ≥ 2 competitors` and `ours = 0`, or `interest high` and `ours low`; weaknesses = topics competitors post about but with poor engagement signals (when available).
4. `competitor_intel.find_gaps` turns clusters into named opportunities with evidence and a `brand_fit` score (similarity to pillars, not in forbidden topics).
5. Opportunities feed `ideation` ("Create 10 posts from those opportunities") with evidence source ids attached.

## 8.7 Guardrails

- Never bypass platform restrictions (no headless browsing of social feeds, no credential sharing, no third-party scraping APIs for platforms that forbid it).
- Respect all quotas; collectors are budgeted per workspace per day (`usage_budgets.kind=platform_reads`).
- Competitor data retention: 365 days of posts/snapshots for sources that permit it; **YouTube other-channel statistics: 30 days** (API Services policy); raw API payloads 30 days. Retention is enforced per `availability_class`/platform by a nightly `jobs.maintenance.enforce_retention` job.
- Everything collected is untrusted text for prompt purposes.
