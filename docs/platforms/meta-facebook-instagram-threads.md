# Meta Platform API Research: Facebook Pages, Instagram, Threads (as of 2026-10-08)

Method: facts below were pulled from official Meta developer docs (developers.facebook.com) in this session, via an automated fetch-and-summarize tool, so quoted text is close to the docs but may be paraphrased in places. Anything not confirmed in this session is marked **UNVERIFIED - check docs**. Secondary (non-Meta) sources are labelled.

Cross-platform facts:
- **Graph API versions** (from the Graph API changelog): latest is **v26.0 (released July 29, 2026)**. Recent releases: v25.0 Feb 18, 2026 (supported until Jul 29, 2028); v24.0 Oct 8, 2025 (until Feb 18, 2028); v23.0 May 29, 2025 (until Oct 8, 2027); v22.0 Jan 21, 2025 (until May 20, 2027); v21.0 Oct 2, 2024 (until Jan 21, 2027); **v20.0 May 21, 2024 (until Sep 24, 2026, so it has already expired)**. Each version is supported for about 2 years, and a new one ships about every 4-6 months. Pin a version and plan an upgrade at least once a year. The release date of the next version (v27) is UNVERIFIED.
- **Threads API is versioned separately** (`v1.0`, on graph.threads.net / graph.threads.com).
- **Rate-limit headers and errors** (Graph API rate-limiting doc): `X-App-Usage` (call_count, total_cputime, total_time, as %), `X-Business-Use-Case-Usage` (adds `estimated_time_to_regain_access` in minutes). Error codes: 4 (app limit), 17 (user limit), 32 (Pages API limit), 613 (custom limit), 80001 (Pages BUC), 80002 (Instagram BUC).

---

## 1. Facebook Pages (Graph API, graph.facebook.com)

### OAuth & tokens
- The user signs in with Facebook Login and you get a **User access token**. You then fetch **Page access tokens** from `/me/accounts`, which needs `pages_show_list`.
- Short-lived user and Page tokens "expir[e] in hours". A **long-lived user token "generally lasts about 60 days"**. You get one with `GET /oauth/access_token?grant_type=fb_exchange_token&client_id&client_secret&fb_exchange_token=...`, called server-side only.
- **A Page token fetched with a long-lived user token "do[es] not have an expiration date"**. It is only invalidated under certain conditions: the user changes their password, revokes permissions, or loses their Page role. The exact list of conditions is UNVERIFIED (see the debugging/expired-tokens doc).
- **Data Access Expiration is separate from token expiry.** Data access "is 90 days, based on when the user was last active". After that the user stays authenticated, "but your app can't access their data" until they re-authorize (`auth_type: 'reauthorize'`). Plan a re-consent flow for inactive users.
- System User tokens (Business Manager), which avoid dependence on a person's login, are UNVERIFIED in this session. Check the Business Manager system user docs.

### Account types
- Facebook Pages, including the New Pages Experience. The token must belong to a person who can perform the needed **tasks** on the Page: `CREATE_CONTENT`, `MODERATE`, `MESSAGING`, `ANALYZE`, `ADVERTISE`, `MANAGE` (also `MANAGE_LEADS`, `VIEW_MONETIZATION_INSIGHTS`).
- Profiles of individual people cannot be published to through the API.

### Scopes / permissions
| Permission | Use (verified in session unless noted) |
|---|---|
| `pages_show_list` | List the user's Pages, get Page tokens (required for Reels, Stories and feed publishing) |
| `pages_manage_posts` | Create, edit and delete posts, photos, videos, Reels and Stories |
| `pages_read_engagement` | Read Page content and engagement; needed with publishing and Insights |
| `pages_read_user_content` | Read user-generated content on the Page (comments, visitor posts) |
| `pages_manage_engagement` | Reply to, hide and delete comments as the Page (listed in Posts guide requirements) |
| `read_insights` | Page and Post Insights (with `pages_read_engagement`, ANALYZE task) |
| `publish_video` | Video publishing (listed in Posts guide) |
| `business_management` | Needed when the Page/assets are accessed through Business Manager / system users (Stories doc) |
| `pages_manage_metadata` | Page settings, subscribing the app to Page webhooks. **UNVERIFIED - check docs** (not confirmed in fetched pages) |
| `pages_messaging` | Messenger Platform (Page inbox). **UNVERIFIED - check docs** |

### App review & verification requirements
- "Most endpoints require one or more permissions which must be granted ... [and] App Review before an app user can grant them to your app after it is live."
- Each permission needs **Advanced Access**, which requires App Review, to be granted by users who have no role on the app. **Business Verification** is required for apps used by people with no role on the app or its owning business (stated in Meta's IG overview; the same Meta platform policy applies to Pages).
- **Page Public Content Access (PPCA)** and **Page Public Metadata Access (PPMA)** each require App Review **and** Business Verification ("You may also need to sign additional contracts").

### Publishing capabilities
| Capability | Supported via API? | Notes |
|---|---|---|
| Text | Yes | `POST /{page_id}/feed` with `message` |
| Link post / link preview | Yes | `link` param on `/feed`. The preview is generated by scraping the URL. Custom `picture`/`name`/`description`/`thumbnail` overrides are deprecated (for v2.10 and lower per doc; treat as unsupported). `call_to_action` object exists. `child_attachments` gives multi-link "carousel" link posts |
| Single photo | Yes | `POST /{page_id}/photos` with `url` (or upload) |
| Multi-photo | Yes (pattern) | Upload each photo with `published=false`, then `POST /feed` with `attached_media[]` = media_fbids. **The `attached_media` param name was not confirmed in this session - UNVERIFIED, check /page/feed reference** |
| Video | Yes | `/{page_id}/videos` (Video API). Needs `publish_video` per Posts guide |
| Reels | Yes | `POST /{page_id}/video_reels`, three-phase upload (`upload_phase=start` -> upload to `rupload.facebook.com` -> `upload_phase=finish`). **30 API-published Reels per Page per 24h moving window.** Specs: 9:16, recommended 1080x1920 (min 540x960), 24-60 fps, **3-90 s**, H.264/H.265 (VP9, AV1 also), AAC 48kHz stereo 128kbps+. fbcdn-hosted URLs are rejected. Collaborator invites: 10 per Page per 24h |
| Stories | Yes | `POST /{page_id}/photo_stories`, `/{page_id}/video_stories`, read via `/{page_id}/stories`. Video 3-90 s per spec table, but the doc also says "A video story can not exceed 60 seconds" (contradiction; assume **60 s max**). Media cannot have been used in a previous post. Stickers and links are not documented |
| Scheduling via API | Yes (feed, photos, Reels) | Feed: `published=false` + `scheduled_publish_time` (UNIX or ISO 8601), **10 minutes to 30 days ahead**. Reels: `video_state=SCHEDULED` + `scheduled_publish_time`, **>10 min and within 29 days**. Stories: no scheduling documented. `backdated_time` is supported on feed |
| Alt text | **UNVERIFIED - check docs** (no alt-text param confirmed for Page photos) |
| Polls | **UNVERIFIED - not documented** in the Pages API pages fetched. Assume no |
| Edit / delete | `POST /{post_id}` (only posts created by the same app), `DELETE /{post_id}` |
| Audience targeting | `targeting`, `feed_targeting` params on `/feed` |

### Analytics capabilities
- Endpoint `GET /{page_id}/insights` and `GET /{post_id}/insights`. Needs a Page token from a person with the **ANALYZE** task, plus `read_insights` and `pages_read_engagement`.
- Periods: `day`, `week`, `days_28`, `lifetime`. Retention: "Metric data of public Pages is stored ... for 2 years". For unpublished Pages, only 5 days. When using since/until for daily metrics, the first `end_time` is since+1 day.
- Page-level metrics (sample from the v23 reference):
  - Engagement: `page_post_engagements`, `page_daily_follows_unique`, `page_fan_adds_by_paid_non_paid_unique`
  - Views/media: `page_media_view`, `page_total_media_view_unique` (the replacements for impressions/reach), `page_views_total`
  - Reactions: `page_actions_post_reactions_*_total`
  - Follows: `page_follows`, `page_daily_follows_unique`. `page_fans`, `page_fan_adds` are still listed, but Pages have moved to a followers model
  - Video: `page_video_views`, `page_video_views_organic`, `page_video_complete_views_30s`
- Post-level metrics (lifetime): `post_media_view`, `post_total_media_view_unique`, `post_clicks`, `post_reactions_by_type_total`, `post_video_views`, `post_video_avg_time_watched`.
- **Deprecations (important):** "By **June 15, 2026**, a number of the Page Insights metrics will be deprecated for all API versions." These are deprecated from v25+, and as of today (Oct 2026) they are gone in all versions:
  - `page_impressions_unique`, `post_impressions_unique`, `page_posts_impressions_unique`
  - `post_impressions_fan_unique`, `post_impressions_organic_unique`, `post_impressions_nonviral_unique`
  - `page_video_views_unique`, `post_video_views_unique` (`page_video_views_10s_unique` was already removed in v18+)
  - Replacements: `page_media_view` / `page_total_media_view_unique`, `post_media_view` / `post_total_media_view_unique`, `page_follows` / `page_daily_follows_unique`. Some unique-reach metrics have **no replacement** (secondary source: improvado.io / Supermetrics docs).
  - Whether the non-unique `page_impressions*` family was also removed in late 2025 is **UNVERIFIED - check the Page Insights deprecation list**.

### Competitor / public data access
- **PPCA (Page Public Content Access)**: "read public data for Pages for which you lack the pages_read_engagement permission and the pages_read_user_content permission. Readable data includes business metadata, public comments and posts." Allowed usage: "Analyze and/or display posts and engagement on Pages." Requires App Review and Business Verification, and possibly extra contracts. In dev mode it only works on Pages whose admin has a role on the app. "Once you set your app to live mode, it will not be able to see any Page public content without this feature."
- **PPMA (Page Public Metadata Access)**: allows "Analyze engagement with public Pages by viewing Like and follower counts" and aggregating public "about" info, plus the Pages Search API. It cannot read feed or comments. It "is superseded by" PPCA and cannot be requested if PPCA is already approved. Requires App Review and Business Verification.
- Feed reading limits: max `limit` 100 posts per request, and "approximately 600 ranked, published posts per year" are returned.
- In practice PPCA is hard to obtain. Meta's reviewers expect a clear benchmarking use case. Approval rate and current reviewer stance are UNVERIFIED.

### Rate limits & quotas
- **Platform (app-level, user tokens):** "Calls within one hour = 200 * Number of Users" (daily active users).
- **Pages BUC (Page or system-user token):** "Calls within 24 hours = 4800 * Number of Engaged Users" (per Page). Error 80001; also code 32 for Pages.
- Reels: 30 published per Page per 24h. Collaborator invites: 10 per Page per 24h.
- Published-post limits for feed/photos are UNVERIFIED (none documented in fetched pages).

### Known limitations & gotchas
- An app can edit only Page posts **it created**.
- Page token invalidation and 90-day data access expiration are two separate failure modes. Handle error 190 and re-auth flows (exact error subcodes UNVERIFIED).
- Reels and Stories reject media hosted on Meta's CDN (fbcdn). Story media cannot be reused from an existing post.
- Insights metrics are churning (June 2026 removals). Build metric definitions as configuration, not hard-coded.
- Feed read is capped at about 600 ranked posts per year, so it is not a complete archive.

### Notable changes 2025-2026
- v22.0 (Jan 2025) through v26.0 (Jul 29, 2026). v20.0 expired Sep 24, 2026.
- Page Insights unique reach/impression and unique video-view metrics were deprecated in v25 and removed for all versions on Jun 15, 2026. Use the `*_media_view` and `*_total_media_view_unique` replacements.
- Facebook Page Reels API: limit of 30 per 24h, collaborator invites, scheduling within 29 days. When each of these was introduced is UNVERIFIED.

### Source URLs
- https://developers.facebook.com/docs/pages-api/overview
- https://developers.facebook.com/docs/pages-api/posts
- https://developers.facebook.com/docs/graph-api/reference/page/feed/
- https://developers.facebook.com/docs/video-api/guides/reels-publishing
- https://developers.facebook.com/docs/page-stories-api
- https://developers.facebook.com/docs/platforminsights/page
- https://developers.facebook.com/docs/graph-api/reference/v23.0/insights
- https://developers.facebook.com/docs/features-reference/page-public-content-access
- https://developers.facebook.com/docs/features-reference/page-public-metadata-access
- https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
- https://developers.facebook.com/docs/facebook-login/auth-vs-data
- https://developers.facebook.com/docs/graph-api/overview/rate-limiting
- https://developers.facebook.com/docs/graph-api/changelog
- Secondary: https://improvado.io/product-updates/connectors/facebook-pages-metrics-deprecation , https://docs.supermetrics.com/docs/facebook-insights-field-changes-june-30-2026-1

---

## 2. Instagram (Instagram Platform)

There are **two paths**. The legacy **Instagram Basic Display API** (personal accounts) was deprecated on **Dec 4, 2024**: "All requests to the Instagram Basic Display API will return an error message." **Personal accounts are not supported by any current API.**

### OAuth & tokens
| | Instagram API with **Instagram Login** | Instagram API with **Facebook Login for Business** |
|---|---|---|
| Host | `graph.instagram.com` | `graph.facebook.com` |
| Auth UI | `https://www.instagram.com/oauth/authorize` (IG credentials). New `enable_fb_login` param (Feb 6, 2026) controls whether the "Log in with Facebook" option is shown. `force_reauth` param (Jun 2025) | Facebook Login for Business |
| Token type | Instagram User token | Facebook User token, then Page token |
| Code / short-lived | Auth code valid 1 hour, single use. Short-lived token valid 1 hour | Short-lived (hours) |
| Long-lived | `GET graph.instagram.com/access_token?grant_type=ig_exchange_token`, valid **60 days** | `fb_exchange_token`, about 60 days. Page token derived from it has no expiry (subject to invalidation and 90-day data access expiration) |
| Refresh | `GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`. Token must be at least 24h old, not expired, and have `instagram_business_basic`. "Tokens that have not been refreshed in 60 days will expire and can no longer be refreshed." | Re-exchange via Facebook Login. Page tokens do not need refresh |

### Account types
- **Instagram Login:** Instagram professional accounts (Business **and** Creator). **No Facebook Page required.**
- **Facebook Login:** professional accounts (Business and Creator) **linked to a Facebook Page**. The user must be able to perform admin-equivalent tasks on that Page.
- **Personal:** not supported (Basic Display API is gone).

### Scopes / permissions
| Instagram Login | Facebook Login |
|---|---|
| `instagram_business_basic` | `instagram_basic` |
| `instagram_business_content_publish` | `instagram_content_publish` |
| `instagram_business_manage_comments` | `instagram_manage_comments` |
| `instagram_business_manage_messages` | `instagram_manage_messages` (messaging goes through the Messenger Platform) |
| `instagram_business_manage_insights` (named in the media and user Insights references as the requirement for Insights on IG Login; it does not appear in the Business Login scope example list) | `instagram_manage_insights` |
| — | `pages_show_list`, `pages_read_engagement` (+ `ads_management`/`ads_read` when the Page role comes via Business Manager; `business_management` in some cases) |
| — | Feature: **Instagram Public Content Access** (needed for Hashtag Search) |
| — | `instagram_manage_contents`: DELETE media (Dec 3, 2025). Whether an IG Login equivalent exists is UNVERIFIED |
| — | `instagram_manage_engagement`: like/unlike media and comments (Apr 22, 2026). IG Login equivalent UNVERIFIED |
- The old IG-Login scope values (`business_basic`, `business_content_publish`, `business_manage_comments`, `business_manage_messages`) were **deprecated Jan 27, 2025**. Use the `instagram_business_*` names.

### App review & verification requirements
- **Standard Access** is the default. It is enough for apps that serve only accounts you own or manage (people with a role on the app).
- **Advanced Access** is "Required if your app serves Instagram professional accounts that you don't own or manage". It requires **App Review + Business Verification**.
- Business Verification is required when "your app will be used by app users who do not have a Role on the app itself, or a Role in a Business that has claimed the app."
- Private apps (no external users) can only request approval for `instagram_basic` and `instagram_manage_comments`.
- Hashtag Search requires approval of the **Instagram Public Content Access** feature.

### Feature matrix by path (from the official overview table)
| Feature | IG Login | FB Login |
|---|---|---|
| Comment moderation | Yes | Yes |
| Content publishing | Yes | Yes |
| Insights | Yes (since Jan 21, 2025) | Yes |
| Mentions | Yes | Yes |
| Messaging | Yes (direct) | Via Messenger Platform |
| Hashtag search | **No** | Yes |
| Product tagging | **No** | Yes |
| Partnership Ads | No | Yes |
| Business Discovery (competitor lookup) | **No** (reference page shows FB Login only) | Yes |
| Facebook Page required | No | Yes |
The IG Login docs say: "This API setup cannot access ads or tagging."

### Publishing capabilities
Flow: `POST /{ig-user-id}/media` creates a **container**. For video, optionally upload resumably via `POST https://rupload.facebook.com/ig-api-upload/{container-id}` (`upload_type=resumable`). Poll `GET /{container-id}?fields=status_code` until it returns `FINISHED`, then call `POST /{ig-user-id}/media_publish` with `creation_id`. Possible statuses: `EXPIRED` ("not published within 24 hours"), `ERROR`, `FINISHED`, `IN_PROGRESS`, `PUBLISHED`.

| Capability | Supported? | Notes |
|---|---|---|
| Text-only | **No** | An image or video is always required |
| Single image | Yes | **JPEG only** (MPO/JPS not supported). Max 8 MB. **Aspect 4:5 to 1.91:1**. Width 320-1440 px. sRGB |
| Video / Reels | Yes | `media_type=REELS`. MOV/MP4, moov atom at the front, no edit lists. HEVC or H.264. AAC up to 48kHz, 1-2 channels, 128kbps. 23-60 fps. Max 1920 px horizontal. Aspect 0.01:1 to 10:1 (9:16 recommended). **3 s to 15 min**. **Max 300 MB**. Video up to 25 Mbps VBR. Params: `cover_url` (JPEG, 8 MB), `thumb_offset`, `share_to_feed`, `audio_name`, `trial_params` (Trial Reels, `graduation_strategy` MANUAL or SS_PERFORMANCE). Whether `media_type=VIDEO` still works for feed video is UNVERIFIED (assume REELS) |
| Carousel | Yes | **Up to 10** images/videos/mix. Reels-type children are not supported. A carousel counts as **one** post toward the limit |
| Stories | Yes | `media_type=STORIES`. Image: JPEG, 8 MB, 9:16 recommended. Video: 3-60 s, max 100 MB, aspect 0.1:1 to 10:1. Stickers, links and polls on Stories are not documented, so assume **unsupported** (UNVERIFIED) |
| Scheduling via API | **No native scheduling** | Containers expire after 24h. Your backend must hold the post and call `media_publish` at the scheduled time |
| Alt text | Yes, **images only** | `alt_text` added Mar 24, 2025. "Reels and stories are not supported" |
| Collaborators | Yes | `collaborators` param, **max 3** usernames. Collaboration-invite endpoints added Dec 3, 2025. Collaborative Media API (media where your user is an accepted collaborator) added Apr 22, 2026 |
| Location tag | Yes | `location_id` (a Facebook Page ID with location) |
| User tags | Yes | `user_tags` |
| Product tags | FB Login only | `product_tags`, max 5. "Shopping tags are not supported" in the Content Publishing guide, so verify against the Product Tagging guide (UNVERIFIED reconciliation) |
| Branded content / paid partnership | Yes (FB Login) | `branded_content_sponsor_ids` (max 2), `is_paid_partnership` (Apr 22, 2026) |
| AI-generated label | Yes | `is_ai_generated=true` (Jun 22, 2026) |
| Music | Partial | Instagram Audio API (Jun 1, 2026) to search original sounds and Meta Sound Collection royalty-free music and attach them. `audio_name` for Reels. The exact attach params are UNVERIFIED |
| Filters | No | "Filters are not supported" |
| Link previews | No | Instagram does not render link previews in feed. Clickable links in captions are UNVERIFIED as a platform behavior (generally not clickable) |
| Polls | No | Not documented (UNVERIFIED) |
| Delete media | Yes (FB Login, `instagram_manage_contents`) | Dec 3, 2025. Covers posts, carousels, Reels, Stories |
| Caption limits | 2,200 characters, 30 hashtags, 20 @-tags | |

### Analytics capabilities
**Media insights** (`GET /{ig-media-id}/insights`). Data is kept up to 2 years and can be delayed up to 48h.
| Metric | Media types |
|---|---|
| `views` (replaces impressions/plays) | FEED, REELS, STORY |
| `reach` | FEED, REELS, STORY |
| `likes`, `comments`, `saved` | FEED, REELS |
| `shares` | FEED, REELS, STORY |
| `total_interactions` | FEED, REELS, STORY |
| `reposts` (Dec 2025) | FEED, REELS, STORY |
| `follows`, `profile_visits`, `profile_activity` (breakdown `action_type`: BIO_LINK_CLICKED, CALL, DIRECTION, EMAIL, TEXT, OTHER) | FEED, STORY |
| `replies`, `navigation` (breakdown `story_navigation_action_type`: SWIPE_FORWARD, TAP_BACK, TAP_EXIT, TAP_FORWARD), `link_clicks` (Jun 22, 2026) | STORY |
| `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`, `reels_skip_rate` (Dec 2025) | REELS |
| `crossposted_views` (IG + FB), `facebook_views` | REELS (`facebook_views` also FEED and STORY since Apr 2026) |
| `total_views`, `total_likes`, `total_comments` (across surfaces including boosted/ads; Apr 22, 2026) | FEED, REELS (+STORY for total_views) |

The standard metrics are **organic only**: interactions on ads are not counted. New media **fields** added Apr 22, 2026: `reposts_count`, `saved_count`, `shares_count`, `total_like_count`, `total_comments_count`, `total_views_count`.

Media insights limitations:
- Story insights are available for **24h only**.
- **No insights for individual children of a carousel/album.**
- Story metrics below 5 return an error ("Not enough viewers").
- Story `replies` returns 0 for users in Europe and Japan.

**Account insights** (`GET /{ig-user-id}/insights`):
- Interaction metrics (period `day`, `metric_type` = `total_value` or `time_series`): `accounts_engaged`, `reach` (breakdowns: `media_product_type`, `follow_type`), `views` (breakdowns: `follower_type`, `media_product_type`), `likes`, `comments`, `saves`, `shares`, `replies`, `reposts`, `total_interactions`, `follows_and_unfollows` (breakdown `follow_type`), `profile_links_taps` (breakdown `contact_button_type`).
- Demographics (`lifetime`, total_value only): `follower_demographics`, `engaged_audience_demographics`, broken down by age, city, country, gender. **`timeframe` is limited to `this_week` and `this_month`** (last_14/30/90_days and prev_month were removed in v20). Requires **100+ followers**. Only the **top 45** values are returned.
- `follower_count` and `online_followers` are mentioned in the limitations (need 100+ followers; online_followers only for the last 30 days) but do **not** appear in the current metrics table. **UNVERIFIED whether still queryable.** Use the `followers_count` field on the IG User node for follower totals.

**Deprecated metrics:**
- `video_views` (media) and user metrics `email_contacts`, `get_directions_clicks`, `profile_views`, `text_message_clicks`, `website_clicks`, `phone_call_clicks`: deprecated in v21, removed for all versions **Jan 8, 2025**.
- `impressions`, `plays`, `clips_replays_count`, `ig_reels_aggregated_all_plays_count`: deprecated in v22, removed for all versions **Apr 21, 2025**. `impressions` still returns data only for media created before July 2, 2024 on v21 and older.
- Replacement: **`views`** (Jan 21, 2025).

### Competitor / public data access
- **Business Discovery** (Facebook Login path only):
  - Query: `GET /{your-ig-user-id}?fields=business_discovery.username(TARGET){followers_count,media_count,media{comments_count,like_count,view_count,...}}`
  - Permissions per reference: `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement` (+ `ads_management`/`ads_read` with Business Manager roles). Earlier docs listed fewer, so re-check.
  - The target must be a professional (Business or Creator) account. Age-gated accounts are not returned.
  - `view_count` on Reels is available **only via Business Discovery** (Jun 16, 2025).
  - You cannot GET the returned media IDs directly ("insufficient permissions").
  - Whether `like_count` is omitted when the owner hides likes is UNVERIFIED.
  - Business Discovery has no specific rate limit documented; it falls under the IG BUC limit. Note: the "240 to 1,000 queries/user/hour" increase (Mar 30, 2026) applies to the **Creator Marketplace Discovery API**, not Business Discovery.
- **Hashtag Search** (Facebook Login path only, needs the Instagram Public Content Access feature + `instagram_basic`):
  - `GET /ig_hashtag_search?user_id=&q=` returns a hashtag ID. Then `/{hashtag-id}/top_media` or `/{hashtag-id}/recent_media` (`recent_media` returns only media published **within the last 24 hours**). `/{ig-user-id}/recently_searched_hashtags` lists recent searches.
  - **Max 30 unique hashtags per IG account per rolling 7 days.**
  - Up to 50 results per page, `after` cursor only.
  - Fields: caption, children, comments_count, id, like_count, media_type, media_url, permalink, timestamp. **`username` cannot be requested.**
  - Not supported: emojis, Stories, promoted/boosted/ad media. You cannot comment on media found this way. Results are not chronological.
- **Mentions**: both paths support mentions (tags / mentioned_media / mentioned_comment). Exact endpoints were not re-checked (UNVERIFIED details).
- **oEmbed**: since May 15, 2026 it can be called **without an access token**.

### Rate limits & quotas
- IG BUC: "Calls within 24 hours = 4800 * Number of Impressions" (impressions of the account). Error 80002.
- **Publishing: 100 API-published posts per 24h moving window** (carousel = 1). Check with `GET /{ig-user-id}/content_publishing_limit`.
- **Container creation: 400 containers per rolling 24h.**
- Hashtag search: 30 unique hashtags per 7 days.
- Messaging:
  - Conversations API: 2 calls/s per account.
  - Private Replies: 750/hour for post and Reel comments, 100/s for Live comments.
  - Send API: 100/s for text, links, reactions and stickers; 10/s for audio and video.

### Known limitations & gotchas
- No personal accounts. No text-only posts. No native scheduling (24h container expiry). JPEG only for images.
- The feed image aspect ratio (4:5 to 1.91:1) is stricter than Reels/Stories, so build automatic crop/pad.
- Hashtag search, product tagging and Business Discovery all require the **Facebook Login** path. A product that offers competitor analytics must support the FB Login path, or offer both paths.
- Insights metrics changed heavily in 2024-2025 and again in Dec 2025 and Apr/Jun 2026. Story insights vanish after 24h, so poll them before then. There are no insights for carousel children.
- Media must be on a publicly reachable URL (or use resumable upload for video).
- The European/Japanese story `replies` metric returns 0.

### Notable changes 2025-2026
- Jan 21, 2025: Insights on the IG Login path, `views` metric, and v22 removals (impressions, plays and related metrics; all versions Apr 21, 2025). IG v1.0 endpoints deprecated.
- Jan 27, 2025: old IG Login scope names removed.
- Mar 24, 2025: `alt_text`.
- Jun 2025: `view_count` via Business Discovery, `force_reauth`.
- Dec 3, 2025: Trial Reels, delete-media permission (`instagram_manage_contents`), collaboration invites, `reels_skip_rate` / `reposts` / `crossposted_views` / `facebook_views`. Dec 2025: PDF attachments in DMs.
- Feb 6, 2026: `enable_fb_login` OAuth param.
- Mar 2026: Creator Marketplace Discovery API limits raised to 1,000/user/hour.
- Apr 22, 2026: `total_*` cross-surface metrics/fields, `reposts_count`/`saved_count`/`shares_count`, Collaborative Media API, partnership-ad labels, `instagram_manage_engagement` (like media/comments).
- May 15, 2026: tokenless oEmbed.
- Jun 1, 2026: Instagram Audio API, `media_audio_type`.
- Jun 22, 2026: `is_ai_generated`, Story `link_clicks`.

### Source URLs
- https://developers.facebook.com/docs/instagram-platform/overview
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
- https://developers.facebook.com/docs/instagram-platform/content-publishing
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
- https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights
- https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/hashtag-search
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-hashtag/recent-media
- https://developers.facebook.com/docs/instagram-platform/changelog
- https://developers.facebook.com/docs/graph-api/overview/rate-limiting

---

## 3. Threads API (graph.threads.net / graph.threads.com, v1.0)

### OAuth & tokens
- Requires a Meta app created with the **Threads use case**. Use the **Threads app ID and secret**, which are separate from the main app ID.
- Short-lived token: valid **1 hour**.
- Long-lived token: `GET /access_token?grant_type=th_exchange_token` (server-side, needs the app secret), valid **60 days**.
- Refresh: `GET /refresh_access_token?grant_type=th_refresh_token`. The token must be **at least 24h old, not expired**, and the user must have granted `threads_basic`. Expired tokens cannot be refreshed or exchanged, so the user must re-authenticate.
- "Permission grants made by app users with public profiles are valid for 90 days". For **private** profiles "the permission grant cannot be extended and the app user must grant the expired permission" again.
- Authorization URL (threads.net/oauth/authorize) was not confirmed in fetched pages: UNVERIFIED.

### Account types
- Any Threads profile, public or private, with the caveat above about re-granting for private profiles. There is no business/creator distinction documented.
- That a Threads profile requires an Instagram account is UNVERIFIED for the API (it is product behavior).
- Testers must be invited as "Threads Tester" in the App Dashboard and accept the invitation.

### Scopes / permissions
- Core (since the June 2024 launch): `threads_basic` (required for all endpoints), `threads_content_publish`, `threads_read_replies` (GET replies), `threads_manage_replies` (POST replies / hide / reply control), `threads_manage_insights` (GET insights).
- Added later: `threads_keyword_search` (Dec 9, 2024), `threads_manage_mentions` (Dec 9, 2024), `threads_delete` (Mar 6, 2025), `threads_location_tagging` (May 27, 2025), `threads_profile_discovery` (Jul 14, 2025), `threads_share_to_instagram` (Mar 25, 2026; cross-share to IG Stories).

### App review & verification requirements
- "Each permission must first be approved through the App Review process, and your app must be published" for non-tester users.
- Keyword search without approval searches **only the authenticated user's own posts**. With approval it searches public posts.
- Profile lookup with standard access works only on Meta's official accounts (@meta, @threads, @instagram, @facebook).
- Whether Threads requires Business Verification is **UNVERIFIED - check docs**.

### Publishing capabilities
Flow: `POST /{threads-user-id}/threads` creates a container, then `POST /{threads-user-id}/threads_publish`. Meta recommends waiting about **30 s** before publishing. Carousels take three steps (item containers, then a carousel container, then publish). Media must be on a publicly accessible URL.

| Capability | Supported? | Notes |
|---|---|---|
| Text | Yes | **500 characters** (emojis counted as UTF-8 bytes). Text attachments for long text added Oct 3, 2025 (limits UNVERIFIED) |
| Image | Yes | JPEG/PNG, 8 MB, width 320-1440 px, aspect up to 10:1 |
| Video | Yes | MOV/MP4, HEVC/H.264, 23-60 fps, max width 1920, 9:16 recommended, up to 100 Mbps, **max 5 min**, **max 1 GB** |
| Carousel | Yes | **2 to 20 items** (raised to 20 on Sep 19, 2024) |
| Stories | No (Threads has no Stories). `threads_share_to_instagram` (Mar 2026) cross-shares to IG Stories |
| Short video / Reels | Video posts only |
| Scheduling via API | **No native scheduling param documented** (UNVERIFIED absence). Schedule in your own backend |
| Alt text | Yes (Aug 21, 2024) |
| Link previews | Yes | `link_attachment` (text-only posts). "The number of links is restricted to 5 or less" |
| Polls | Yes (poll attachment, Apr 14, 2025; poll-votes metric Aug 12, 2025). Exact param name UNVERIFIED |
| Other | Quote posts and reposts (Oct 2024), topic tags (`topic_tag`, 1-50 chars, Jul 2025), location tagging (May 2025), GIFs (`gif_attachment`, GIPHY only; Tenor sunset Mar 31, 2026), spoilers (Oct 2025), ghost posts (Dec 15, 2025), reply approvals (Feb 13, 2026), deletion (Mar 2025), replies / reply moderation |

### Analytics capabilities
- Media insights: `views`, `likes`, `replies`, `reposts`, `quotes`, `shares`. Poll votes are tracked via the changelog (Aug 2025). Nested replies are not included, and REPOST_FACADE posts return an empty result.
- User insights: `views` (time series), `likes`, `replies`, `reposts`, `quotes`, `clicks` (Jul 2, 2025), `followers_count`, `follower_demographics`. Demographics take one breakdown: country, city, age or gender, and need **100+ followers**. `followers_count` and `follower_demographics` do not support since/until.
- Earliest date: **Apr 13, 2024** (timestamp 1712991600). "user insights are not guaranteed to work before June 1, 2024."
- Requires `threads_basic` + `threads_manage_insights`.

### Competitor / public data access
- **Keyword search**: `GET /keyword_search?q=`. Params: `search_type` TOP|RECENT, `search_mode` KEYWORD|TAG, `media_type`, `since`/`until`, `limit` (max 100), `author_username`. Returns id, text, media_type, permalink, timestamp, username, has_replies, is_quote_post, is_reply. **2,200 queries per user per rolling 24h** (empty results don't count). Needs `threads_keyword_search` plus approval for public posts.
- **Profile discovery**: `GET /profile_lookup?username=`. Returns username, name, picture, biography, `follower_count`, `likes_count`, `quotes_count`, `reposts_count`, `views_count`, `is_verified`. Only for public profiles with **at least 100 followers**. **1,000 requests per 24h**. Needs `threads_profile_discovery` (Advanced Access required for non-Meta accounts). An endpoint that lists another profile's posts is **UNVERIFIED - check docs**.
- Mentions: `threads_manage_mentions` (Dec 2024).

### Rate limits & quotas (per profile, 24h moving window)
- **250 API-published posts.** 1,000 replies. 100 deletions. 500 location searches. 2,200 keyword-search queries. 1,000 profile lookups.
- API calls: "4800 * Number of Impressions" (minimum impressions value 10). CPU: total_cputime = 720000 * impressions, total_time = 2880000 * impressions.

### Known limitations & gotchas
- A separate app ID/secret, host and version (v1.0) from the Graph API.
- Private-profile users must re-grant permissions when they expire.
- There is no Stories or scheduling endpoint. Insights only go back to April 2024.
- The Threads "views" and "shares" metrics are marked "in development".

### Notable changes 2025-2026
- Polls (Apr 2025), deletion (Mar 2025), location (May 2025), `graph.threads.com` domain alias (Jun 6, 2025), clicks metric (Jul 2025), topic tags and profile discovery (Jul 2025), publish/delete webhooks (Aug 2025), spoilers and text attachments (Oct 2025), GIPHY GIFs (Oct 2025), ghost posts (Dec 2025).
- 2026: reply approvals (Feb 2026), extra reply/quote params (Mar 19, 2026), share to Instagram (Mar 25, 2026), Tenor GIF sunset (Mar 31, 2026).
- Threads Ads expanded through 2025-2026 (video, carousel, catalog, app ads, Page-backed accounts Apr 2026).

### Source URLs
- https://developers.facebook.com/docs/threads/overview
- https://developers.facebook.com/docs/threads/get-started
- https://developers.facebook.com/docs/threads/get-started/long-lived-tokens
- https://developers.facebook.com/docs/threads/posts
- https://developers.facebook.com/docs/threads/insights
- https://developers.facebook.com/docs/threads/keyword-search
- https://developers.facebook.com/docs/threads/threads-profiles
- https://developers.facebook.com/docs/threads/changelog
