# 27 — API Integration Strategy (per platform)

For each platform: OAuth · permissions/scopes · tokens · account types · publishing · analytics · approval/audit · rate limits · failure cases · Botwok decisions. Facts verified 2026-10-08 (`docs/platforms/`).

## 27.1 Meta — Facebook Pages
- **OAuth:** Facebook Login (code flow, `state`), HTTPS redirect. User token → long-lived (60 d) via `oauth/access_token?grant_type=fb_exchange_token` → Page tokens from `/me/accounts` (`pages_show_list`); Page tokens derived from long-lived user tokens **do not expire**, but Meta revokes data access after **90 days of user inactivity** → Botwok re-prompts consent when probes fail.
- **Scopes:** `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `pages_read_user_content` (comments), `pages_manage_engagement` (reply/hide), `business_management` (for IG linkage/BUC), `pages_manage_metadata` (webhooks; ?), `read_insights`.
- **Publishing:** feed/photos/videos/Reels (3-phase upload)/Stories; native scheduling available but Botwok uses its own scheduler (option to hand off in V2). Limits: Reels 30/24 h.
- **Analytics:** Page Insights (`page_media_view`, `post_media_view`, `post_total_media_view_unique`, engagements, clicks, follows); unique impression/reach metrics removed 2026-06-15 → normalizer maps to `views`/`reach` with `availability=deprecated` for old names.
- **Approval:** App Review for publishing/insights permissions in Live mode; development mode works for app admins/developers/testers (MVP dogfooding). Business Verification where required.
- **Rate limits:** 200 calls/h/user (app-level), Page BUC 4,800/engaged-user/24 h; honor `X-App-Usage`, `X-Business-Use-Case-Usage` (`estimated_time_to_regain_access`).
- **Failures:** code 190 (token) → refresh/reconnect; 4/17/32/613/80001 (limits) → wait; 368 (policy) → permanent; media fetch errors → public URL check.
- **Decisions:** `MetaGraphClient` pinned to v26.0 with upgrade reminder every 6 months; Stories not schedulable via API → Botwok schedules and publishes at time.

## 27.2 Meta — Instagram
- **Two flavors:** *Facebook Login (Business)* — requires a Professional account linked to a Facebook Page; unlocks Business Discovery, Hashtag Search, product tagging. *Instagram Login* — no Page needed; publishing, comments, insights, mentions; scopes `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_comments`, `instagram_business_manage_messages`, `instagram_business_manage_insights` (required for insights though missing from the login scope list — ?). Personal accounts unsupported (Basic Display API shut down 2024-12).
- **Tokens:** long-lived 60 days, refreshable (`refresh_access_token`) when ≥ 24 h old; Botwok refreshes at 50 days.
- **Publishing:** container flow; JPEG only; aspect 4:5–1.91:1; carousels ≤ 10; Reels 3 s–15 min ≤ 300 MB; Stories video 3–60 s ≤ 100 MB; alt text images only; ≤ 3 collaborators; **100 API posts/24 h** (`content_publishing_limit` endpoint checked before scheduling); 400 containers/24 h; containers expire 24 h (never pre-create containers; create at publish time); delete supported (2025-12); `is_ai_generated` flag set by Botwok when media is AI-generated.
- **Analytics:** `views` (replaces impressions/plays), reach, likes, comments, saved, shares, reposts, `ig_reels_avg_watch_time`, `reels_skip_rate`, Story `link_clicks`; account: follower_count (?), demographics (`this_week`/`this_month`, ≥ 100 followers, top 45).
- **Competitor data:** Business Discovery (username → followers_count, media_count, media with like/comment counts, Reels `view_count`); Hashtag Search 30 unique/7 d, last 24 h only.
- **Approval:** App Review (Advanced Access) + Business Verification for Live; dev mode for testers.
- **Decisions:** ship Facebook Login flavor first (competitor features), Instagram Login as the second adapter flavor (sole-proprietor creators without a Page).

## 27.3 Meta — Threads
- **OAuth:** Threads Login (`threads.net/oauth/authorize`), separate app product; scopes `threads_basic`, `threads_content_publish`, `threads_manage_insights`, `threads_manage_replies`, `threads_read_replies`, plus keyword search/profile discovery permissions after approval.
- **Tokens:** short → long-lived 60 d, refresh when ≥ 24 h old; private profiles must re-grant on expiry.
- **Publishing:** container → wait ≥ 30 s for media → publish; TEXT 500 chars (UTF-8 bytes), ≤ 5 links, IMAGE/VIDEO (≤ 5 min, ≤ 1 GB)/CAROUSEL 2–20; polls, alt text, topic tags, location, GIFs; limits 250 posts/24 h, 1,000 replies, 100 deletes; no Stories; no native scheduling.
- **Analytics:** views, likes, replies, reposts, quotes, shares (?), followers, demographics ≥ 100 followers; data from 2024-04-13.
- **Competitor data:** keyword search (2,200/24 h) and profile lookup (1,000/24 h; public ≥ 100 followers) after Meta approval.
- **Decisions:** Threads adapter shares the Meta client; treat as V1 platform (simple API, cheap).

## 27.4 LinkedIn
- **Products:** Sign In (OIDC: `openid profile email`) + Share on LinkedIn (`w_member_social`) are self-serve → member posting works day one. Community Management API (`w_organization_social`, `r_organization_social`, `r_organization_admin`, `rw_organization_admin`, `r_member_postAnalytics`) requires an application by a registered legal organization with a verified business email and Page super-admin verification; Development tier (500/app/day, 100/member/day) → Standard tier (test credentials + screencast). Rejection means a new app.
- **Tokens:** access 60 days; **refresh tokens only for approved MDP partners** (fixed 365-day life). Without refresh, Botwok must send users through OAuth every 60 days → `SOCIAL_ACCOUNT_TOKEN_EXPIRING` 7 days ahead; posts scheduled beyond expiry are blocked at scheduling time.
- **Versioning:** `LinkedIn-Version: YYYYMM` mandatory; monthly versions supported ≥ 1 year; adapter pins a version and tests a bump quarterly.
- **Publishing:** `POST /rest/posts` (`author` person/organization URN); text (limit unspecified on the page; ~3,000 chars ?), image (Images API), multi-image 2–20 (organic only), video ≤ 5 GB (multipart 4 MB parts), document PDF/PPT/DOC ≤ 100 MB/300 pages (carousel-like), article shares (title/description/thumbnail supplied — no URL scraping), polls 2–4 options; no scheduling (`lifecycleState=PUBLISHED`); delete supported.
- **Analytics:** org share statistics (12-month rolling, daily/monthly; per-post lifetime), follower statistics (demographics; gains up to 12 months), page statistics; member post analytics (`memberCreatorPostAnalytics`: impressions, reach, link clicks, saves since 202604).
- **Competitor data:** organization lookup + follower count only; other orgs'/members' posts not readable. `r_member_social` closed → **Botwok cannot list a member's own posts; it stores every post id it creates** (and imports nothing).
- **Data rules:** member social activity storable 48 h, profile data 24 h → retention job; analytics stored as Botwok-derived aggregates only where permitted.
- **Rate limits:** Share: 150/member/day, 100k/app/day; CM: unpublished standard limits (read from portal); daily reset midnight UTC.
- **Decisions:** MVP = member posting; org posting + analytics after Community Management approval (apply in Phase 3; expect weeks).

## 27.5 X
- **OAuth:** OAuth 2.0 PKCE (user context) with scopes `tweet.read tweet.write users.read media.write offline.access`; access tokens 2 h, refresh via `offline.access` (rotation details ?). App-only Bearer for public reads.
- **Pricing (changed 2026-02-06):** pay-per-use credits (Free/Basic/Pro discontinued; legacy migrated by 2026-09). Post create $0.015; **post containing a URL $0.20**; post read $0.005; user read $0.01; owned reads $0.001; delete $0.01; 3M post reads/month cap then Enterprise. Botwok shows per-post cost at scheduling and tracks spend in `usage_ledger`.
- **Publishing:** `POST /2/tweets` (text ≤ 280; media ≤ 4; polls 2–4 options, 5 min–7 d; `reply_settings`); media via v2 chunked upload (`initialize/append/finalize/status`; one-shot for images); v1.1 media upload shut down 2025-06-09; video 8 GB/20 min (16 GB/125 min Premium); threads via self-reply chains (self-reply exemption from the "summoned" rule is a **secondary source** → verify in sandbox before enabling threads by default); **quote posts Enterprise-only**; likes/follows removed from self-serve 2026-04; replies to others only when summoned (2026-02-23). Delete supported.
- **Analytics:** `public_metrics` (impressions, likes, replies, reposts, quotes, bookmarks) for any post; `non_public`/`organic` metrics (url/profile clicks, engagements) owner-only, **last 30 days** → pull cadence ends at day 30.
- **Competitor data:** user lookup, user timelines (3,200 cap ?), recent search (7 d) and full-archive search on pay-per-use; metered → monthly budget per workspace.
- **Rate limits:** per-endpoint 15-minute windows (e.g. delete 50/15 min); headers `x-rate-limit-*` drive the limiter.
- **Failures:** 403 duplicate content → permanent; 429 → window wait; 401 → refresh; media processing `failed` → permanent with reason.
- **Decisions:** MVP platform; URL-cost warning; thread mode behind a verified flag; no engagement automation (policy).

## 27.6 TikTok
- **Surfaces:** TikTok for Developers (Login Kit, Content Posting, Display) for publishing/basic stats; TikTok Business API (Organic Accounts API, gated by access form since 2026-03-20) for deep insights; Research API (academic only) and Commercial Content API (EU ads) not usable.
- **OAuth:** Login Kit PKCE (desktop: **hex-encoded SHA-256 challenge**; localhost/127.0.0.1 with port allowed); scopes `user.info.basic`, `user.info.profile`, `user.info.stats`, `video.list`, `video.upload`, `video.publish`; access 24 h, refresh 365 d (rotating → always persist the new one).
- **Publishing:** Direct Post (`video.publish`; mandated UX: `creator_info` fetched on screen open, privacy dropdown with no default, duet/stitch/comment toggles unchecked, branded-content declaration, no watermarks, preview + consent, `is_aigc` flag) vs Upload to inbox (`video.upload`; user finalizes in app; 5 pending/24 h). Video ≤ 4 GB chunked (5–64 MB chunks, last ≤ 128 MB, ≤ 1,000 chunks, upload URL 1 h) or PULL_FROM_URL (verified domain); photo posts ≤ 35 images PULL_FROM_URL only, title ≤ 90, description ≤ 4,000; video title ≤ 2,200. No scheduling, **no delete**, no captions API, cover by frame timestamp only. Status via `post/publish/status/fetch` (30/min).
- **Audit:** unaudited apps: SELF_ONLY privacy, private accounts, ≤ 5 posting users/24 h. **"A utility tool to help upload contents to the account(s) you or your team manages" is listed as unacceptable**, and private/personal-use apps are rejected → a single-team Botwok instance should plan on **inbox upload** (draft) as the realistic mode; Direct Post only if Botwok is offered as a multi-user product and passes audit.
- **Analytics:** own videos lifetime views/likes/comments/shares (`video.list`/`video.query`, ≤ 20 per request); follower counts via `user.info.stats`; deep metrics via Business API (RA).
- **Competitor data:** none for commercial tools.
- **Rate limits:** ~15 direct posts/creator/day shared across apps; init 6/min/user; creator_info 20/min; Display 600/min.
- **Decisions:** V2 platform; adapter modes `inbox_upload` (default) and `direct_post` (flag after audit); TikTok scripts generated regardless (user can post manually).

## 27.7 YouTube
- **OAuth:** Google OAuth; scopes `youtube.upload`, `youtube` (or `youtube.force-ssl`), `youtube.readonly`, `yt-analytics.readonly`; access 1 h, refresh tokens (7-day expiry while the consent screen is in Testing; unverified apps capped at 100 users) → publish the consent screen and complete verification before V1; YouTube compliance audit is a separate process (unaudited uploads are **locked private**; audit also required for quota increases and for derived-metrics/36-month storage permissions).
- **Quota (changed 2026-06-01):** general 10,000 units/day; `videos.insert` and `search.list` each in their own 100-calls/day bucket at 1 unit/call; `videos.batchGetStats` 1 unit (own 10k bucket, no auth for public videos); every request ≥ 1 unit; reset midnight PT. BudgetGuard tracks units per project.
- **Publishing:** resumable `videos.insert` (title ≤ 100 chars no `<>`; description ≤ 5,000 **bytes**; tags ≤ 500 chars; categoryId; madeForKids; `privacyStatus`; `publishAt` requires `private` and a never-published video); Shorts auto-detected (≤ 3 min, vertical/square; > 1 min with Content ID claim blocked); `thumbnails.set` (verified channel, ≤ 50 MB); `captions.insert`; playlists; comments; community posts N; delete supported.
- **Analytics:** Data API statistics (views, likes, comments) for any public video; Analytics API `reports.query` (views, estimatedMinutesWatched, averageViewDuration, subscribersGained, likes, shares, comments, by day/video/trafficSource/device; 48–72 h latency; `engagedViews` for consistent history after the 2026-08 view-count change); impressions/CTR only via Reporting API reach reports (since 2026-01).
- **Competitor data:** public channel/video statistics (`search.list(channelId)` budgeted; `batchGetStats`); **store ≤ 30 days** and no derived metrics unless audited; titles/descriptions/comments 30-day rule always.
- **Decisions:** V1 platform (uploads with optional native `publishAt`); Shorts as normal uploads; quota-aware competitor sync (max 1 `search.list` per competitor per week).

## 27.8 Pinterest
- **OAuth:** OAuth 2.0 code flow; scopes `boards:read boards:write pins:read pins:write user_accounts:read`; access 30 days; **continuous refresh token (60-day expiry, refreshable indefinitely)**; business account required.
- **Access tiers:** Trial (on approval; 1,000 req/day; pins/boards visible only to creator) → Standard (video of the OAuth flow required even for single-user apps).
- **Publishing:** pins need media: image (URL/base64/upload), carousel 2–5 images, video via `/v5/media` + cover; title ≤ 100, description ≤ 800, link ≤ 2,048, alt_text ≤ 500; no text/polls; no scheduling; delete yes; edit beta.
- **Analytics:** account and pin analytics (impressions, pin clicks, outbound clicks, saves, video metrics), ≤ 90-day lookback; top pins.
- **Competitor data:** none (Trends API for market keywords only).
- **Decisions:** V2 platform; Standard access needed before public pins → warn users in Trial.

## 27.9 Google Business Profile
- **OAuth:** `https://www.googleapis.com/auth/business.manage`; standard Google tokens; OAuth verification requirement for the scope ?.
- **Access:** request form; quota 0 QPM until approved (300 QPM after); business verified ≥ 60 days with a website.
- **Publishing:** `localPosts.create` STANDARD/EVENT/OFFER with CTA buttons; media by public URL; **native `scheduledTime`** and recurring posts (2026-04); max length/media count ?; 10 edits/min/profile (fixed); delete supported.
- **Analytics:** daily location metrics (impressions by Maps/Search × desktop/mobile, calls, website clicks, directions, bookings, menu clicks) + monthly search keywords; **no per-post insights** (discontinued 2023); lookback ~18 months (secondary).
- **Competitor data:** none. Q&A API discontinued 2025-11-03.
- **Decisions:** V2 platform; use native scheduling optionally; GBP posts generated as a repurposing target regardless.

## 27.10 Cross-platform integration rules
1. Pin external API versions per adapter; record `VERIFIED_AT`; quarterly verification task.
2. Probe capabilities per account after connect and daily; store in `social_accounts.capabilities`; the UI only offers what the account can do (e.g. TikTok unaudited → inbox mode; YouTube unaudited → "will be private").
3. Every write is preceded by `validate_content()` using the matrix; every read is budgeted.
4. Developer-app registration checklist per platform lives in `docs/platforms/app-setup.md` (redirect URIs, privacy policy URL, data deletion callback, demo video requirements).
5. Never implement an undocumented endpoint; where a capability is `?`, keep the feature flag off until verified.
