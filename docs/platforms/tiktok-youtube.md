# TikTok and YouTube API capabilities: research notes (checked 2026-10-08)

Method: I read official docs directly (developers.tiktok.com, business-api.tiktok.com, developers.google.com, support.google.com) through WebFetch, curl, and a headless browser for the JS-rendered TikTok Business portal. Facts marked "secondary source" come from non-official pages. Facts marked "UNVERIFIED - check docs" are ones I could not confirm in an official doc.

---

## 1. TikTok

TikTok has **three separate developer surfaces**, each with its own app, review, and OAuth:

| Surface | Portal | Who it serves | Relevance |
|---|---|---|---|
| TikTok for Developers (Login Kit, Display API, Content Posting API, Data Portability, Research API, Commercial Content API) | developers.tiktok.com, `open.tiktokapis.com/v2` | Any TikTok user (personal, creator, business) | Main publishing path and basic stats for the user's own posts |
| TikTok API for Business: Organic API (Accounts, Mentions, TikTok One, Discovery, Spark Ads Recommendation), Marketing API, Business Messaging API | business-api.tiktok.com, `business-api.tiktok.com/open_api/v1.3` | Brands/agencies; needs a TikTok For Business developer account | Rich per-post insights (reach, watch time, traffic sources, audience) plus publishing |
| Research API / Commercial Content API | developers.tiktok.com/products/... | Academics/non-profits (Research); ad-library access (Commercial Content) | Not usable by a commercial tool (Research). Ads-only, EU-only (CCA) |

### 1.1 OAuth & tokens (Login Kit)
- **Desktop flow:** authorize at `https://www.tiktok.com/v2/auth/authorize/` with `client_key`, comma-separated `scope`, `redirect_uri`, `state`, `response_type=code`, `code_challenge`, `code_challenge_method=S256`.
- **PKCE is mandatory for mobile and desktop apps.** Gotcha: TikTok's desktop doc says to build the code challenge with "hex encoding of SHA256" of the verifier, not the base64url encoding in RFC 7636. The verifier must be 43-128 characters. Test this carefully; hex vs base64url is a known integration trap.
- **Desktop redirect URIs:** "Only `localhost` or loopback IP `127.0.0.1` are allowed host names". The URI must include a port, and a wildcard port (`*`) is supported, e.g. `http://127.0.0.1:*/callback/`.
- **Token endpoint:** `POST https://open.tiktokapis.com/v2/oauth/token/` (exchange and refresh). **Revoke:** `POST https://open.tiktokapis.com/v2/oauth/revoke/`.
- **Lifetimes (verified):** access token `expires_in` = 86,400 s (**24 h**). Refresh token `refresh_expires_in` = 31,536,000 s (**365 days**).
- **Refresh tokens can rotate:** "The returned `refresh_token` may be different than the one passed in the payload. You must use the newly-returned token". Always persist the new value.
- The Business API uses its own OAuth: `/tt_user/oauth2/token/` returns an `open_id` that is passed as `business_id`.

### 1.2 Account types
- **TikTok for Developers APIs** work with any TikTok account that authorizes the app. `creator_info` returns different `privacy_level_options` for public and private accounts:
  - Public accounts: `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `SELF_ONLY`.
  - Private accounts: `FOLLOWER_OF_CREATOR`, `MUTUAL_FOLLOW_FRIENDS`, `SELF_ONLY`.
- **Business API (Accounts API):** a developer must first create a TikTok For Business account. Some post metrics are flagged "only available for Business Accounts" (profile_views), and others for "Verified Business Accounts" only (website_clicks, phone_number_clicks, lead_submissions, app_download_clicks, email_clicks, address_clicks). This implies non-business accounts can be connected but get fewer metrics.
- To get insights at all, the account owner must have "Turn On" enabled on the Analytics page of the TikTok app and must have published at least one video.
- Whether a pure personal (non-creator, non-business) account can authorize the Business API: secondary sources say personal accounts cannot. UNVERIFIED - check docs.

### 1.3 Scopes / permissions (developers.tiktok.com)
| Scope | Grants | API |
|---|---|---|
| `user.info.basic` | open_id, union_id, avatar_url(s), display_name | `GET /v2/user/info/` |
| `user.info.profile` | bio_description, profile_deep_link, is_verified, username | `/v2/user/info/` |
| `user.info.stats` | follower_count, following_count, likes_count, video_count | `/v2/user/info/` |
| `video.list` | the user's **public** videos | `/v2/video/list/`, `/v2/video/query/` |
| `video.upload` | "Share content as a draft to your TikTok account" | Upload to inbox (video `/v2/post/publish/inbox/video/init/`, photo `MEDIA_UPLOAD`) |
| `video.publish` | "Post content to TikTok" | Direct Post (`/v2/post/publish/video/init/`, `/v2/post/publish/content/init/`), `creator_info` |

Other scopes exist: research.data.basic / research.data.u18eu / research.data.vra, Data Portability scopes, and local.* scopes. Every scope must be approved during app review.

Business API: separate permission scopes. The post insights response marks each field with a required permission, `video.list` for basic fields and `video.insights` for watch time, retention, audience, and so on. Starting **March 20, 2026**, developers must complete an **"Accounts API Access Application Form"** before submitting a new app or requesting a scope increase that includes the "TikTok Accounts" permission scope.

### 1.4 App review / audit & verification
There are **two gates**, plus a third if you need Business API data.

1. **App review** (needed to go to production for any product).
   - Submit: at least one demo video of the full end-to-end flow (max 5 videos, 50 MB each), a website, and a Privacy Policy and ToS visible on that site. The first submission must demo the integration in a sandbox.
   - **Rejection reasons:** app is "still in development or testing", serves "private or personal use", or has a name that references social media companies.
   - The guidelines state plainly: "Apps must not be for private or personal use."
2. **Content Posting API audit** (needed for public Direct Post).
   - "All content posted by unaudited clients will be restricted to private viewing mode."
   - "Unaudited API Clients can allow up to **5 users** to post in a 24 hour window."
   - "All user accounts using the API client to post must be **set to private** at the time of posting." Error: `unaudited_client_can_only_post_to_private_accounts`.
   - "Unaudited API Clients can only post contents in `SELF_ONLY` viewership."
   - After the audit, each client gets a "24-hour active creator cap ... based on the usage estimates provided in the audit application form" (error `reached_active_user_cap`).
   - **Use cases the audit rejects** (content-sharing guidelines): "An app that copies arbitrary contents from other platforms to TikTok". Also "A utility tool to help upload contents to the account(s) you or your team manages". Clients "should be intended for a wide audience, not limited to internal groups/private use."
   - **Implication:** an internal or single-team posting tool will likely fail the TikTok audit. Plan for the Upload-to-Inbox (draft) flow, or for a genuinely multi-tenant product.
3. **Sandbox:** up to 5 sandboxes per app and up to 10 accounts each, with no app review needed. "Sandbox mode does not offer access to Content Posting API for public videos or Data Portability API."

The Upload (inbox/draft) flow has no stated audit requirement in the docs I read, but the `video.upload` scope still needs app-review approval. Whether unaudited clients can use inbox upload for non-private accounts: UNVERIFIED - check docs.

### 1.5 Publishing capabilities
**Direct Post vs Upload:**
- **Direct Post** (`video.publish`) publishes straight to the profile. The app must build TikTok's mandated UX (below).
- **Upload / `MEDIA_UPLOAD`** (`video.upload`) sends the content to the creator's TikTok inbox. The creator then "click[s] on inbox notifications to continue the editing flow in TikTok and complete the post." The limit is "5 pending shares within any 24-hour period" (`spam_risk_too_many_pending_share`).

**Mandatory Direct Post UX (content-sharing guidelines):**
- Call `POST /v2/post/publish/creator_info/query/` each time the "Post to TikTok" page renders. Show the creator's nickname. Block posting if the creator can't post. Enforce `max_video_post_duration_sec`.
- Privacy: a dropdown built from `privacy_level_options` with **"no default value"**. The user must pick.
- Interaction toggles: Allow Comment, Duet, and Stitch for video; Comment only for photo. **None checked by default.** Grey out a toggle when creator_info says it is disabled.
- Commercial content disclosure: a toggle that, when on, requires at least one of:
  - **"Your Brand"** → label "Promotional content".
  - **"Branded Content"** → label "Paid partnership". Branded content **cannot be private/SELF_ONLY**.
- Declaration text: "By posting, you agree to TikTok's Music Usage Confirmation". With Branded Content it becomes "...Branded Content Policy and Music Usage Confirmation".
- Show a content preview. Get express user consent. Let the user edit any preset caption/hashtags. **No watermarks/logos/promotional text** added to content. Tell users processing can take minutes, then poll status or use webhooks.
- API request fields (video Direct Post):
  - `post_info.title`: max 2,200 UTF-16 runes.
  - `privacy_level`: one of `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR`, `SELF_ONLY`.
  - Toggles: `disable_duet`, `disable_stitch`, `disable_comment`, `brand_content_toggle`, `brand_organic_toggle`, `is_aigc` (AI-generated label).
  - Cover: `video_cover_timestamp_ms`.

**Media requirements (media transfer guide):**
- **Video:**
  - Formats: MP4 (recommended), WebM, MOV. Codecs: H.264 (recommended), H.265, VP8, VP9.
  - Frame rate 23-60 FPS. Resolution min 360 px and max 4096 px per side. Max file size **4 GB**.
  - Duration up to 10 min, but the per-creator cap is in `max_video_post_duration_sec`.
- **Chunked FILE_UPLOAD:**
  - Each chunk ≥5 MB and ≤64 MB. The final chunk can be up to 128 MB.
  - 1-1000 chunks, uploaded sequentially. Files <5 MB go as a single chunk.
  - `upload_url` is valid for **1 hour**.
- **PULL_FROM_URL:** you must verify the domain or URL prefix in the developer portal (`url_ownership_unverified` error otherwise). TikTok's download has a 1-hour timeout.
- **Photos:** WebP or JPEG, max 1080p, max 20 MB each.

**Photo carousels** (`POST /v2/post/publish/content/init/`, `media_type: PHOTO`):
- **`PULL_FROM_URL` only.** "Only PULL_FROM_URL is allowed". There is no FILE_UPLOAD for photos, so images must be hosted on a verified domain.
- `photo_images`: "up to **35** photo content URLs". `photo_cover_index` is required.
- Title max **90** UTF-16 runes. Description max **4,000**.
- `auto_add_music` is available for DIRECT_POST only.
- `post_mode`: `DIRECT_POST` (`video.publish`) or `MEDIA_UPLOAD` (`video.upload`).

**Post status:**
- Endpoint: `POST /v2/post/publish/status/fetch/` (30 req/min per user token).
- Statuses: `PROCESSING_UPLOAD`, `PROCESSING_DOWNLOAD`, `SEND_TO_USER_INBOX`, `PUBLISH_COMPLETE`, `FAILED`.
- `publicaly_available_post_id` [sic] is returned only after the post is public and has passed moderation.
- **Webhooks** can replace polling: `post.publish.failed`, `post.publish.complete`, `post.publish.inbox_delivered`, `post.publish.publicly_available`, `post.publish.no_longer_publicaly_available`.

| Capability | TikTok for Developers (Content Posting API) | TikTok Business API (Accounts API) |
|---|---|---|
| Text-only post | Not supported (only video, and PHOTO media type) | Not documented for publishing. Insights list "photo or text post" as `PHOTO`. UNVERIFIED |
| Image(s) | Yes, 1-35 photos, PULL_FROM_URL only | UNVERIFIED - check docs (a photo publish endpoint likely exists) |
| Video | Yes, FILE_UPLOAD or PULL_FROM_URL, ≤4 GB | Yes, `POST /v1.3/business/video/publish/` from a verified URL. Constraints: mp4/mov/webm, ≤1 GB, 3-600 s, ≥360 px, 23-60 FPS |
| Short-form | All TikTok content is short-form; max duration per creator | same |
| Scheduling via API | **No scheduling parameter.** The tool must hold the post and call the API at the scheduled time | No scheduling param seen. `upload_to_draft` flag exists. UNVERIFIED |
| Thumbnail/cover | Frame pick via `video_cover_timestamp_ms` (no custom image upload). Photo: `photo_cover_index` | `custom_thumbnail_url` (JPG/JPEG/WebP/PNG, ≤20 MB, 360x360 to 1080x1920) or `thumbnail_offset` |
| Captions/subtitles | Not supported via API (no field) | Not seen |
| AI-generated label | `is_aigc` | `is_ai_generated` |
| Commercial disclosure | `brand_content_toggle`, `brand_organic_toggle` | `is_brand_organic`, `is_branded_content` (required booleans) |
| Delete post | **No delete endpoint** in the Content Posting API reference | UNVERIFIED - check docs |
| Drafts | Upload-to-inbox (`video.upload` / `MEDIA_UPLOAD`) | `upload_to_draft` param |

### 1.6 Analytics capabilities
**Display API (developers.tiktok.com):** covers the authorizing user only.
- `GET /v2/user/info/` with `user.info.stats` returns follower_count, following_count, likes_count, and video_count. These are **current lifetime totals; there is no time series**.
- `POST /v2/video/list/` returns the user's **public** videos. Default 10 per page, **max 20**. Cursor = ms timestamp.
- `POST /v2/video/query/` takes up to **20 video IDs**. It "verifies that the videos belong to the user". Other users' videos are not returned.
- Video fields: id, create_time, cover_image_url (6 h TTL), share_url, video_description, duration, height, width, title, embed_html, embed_link, **like_count, comment_count, share_count, view_count**, is_aigc.
- **Lifetime totals only.** No watch time, reach, retention, traffic source, demographics, or daily breakdown. Build your own time series by snapshotting.

**Business API: Accounts API insights.** This is the only official source of deeper organic analytics.
- `GET /open_api/v1.3/business/video/list/` with `business_id`, `fields`, `filters.video_ids`, cursor, and `max_count` ≤20.
- Fields:
  - item_id, media_type, is_ad, thumbnail_url, share_url, embed_url, caption, video_duration, create_time.
  - likes, comments, shares, favorites, reach, video_views (organic + paid).
  - total_time_watched, average_time_watched, full_video_watched_rate, new_followers, profile_views.
  - website_clicks, phone_number_clicks, lead_submissions, app_download_clicks, email_clicks, address_clicks.
  - video_view_retention, impression_sources, audience_genders, audience_countries, audience_cities, audience_types, engagement_likes.
- **Latency:** most metrics update at "T + 24-48 hrs (UTC time)". IDs, URLs, and captions are real-time.
- "Post data will stop updating 365 days after the post is published."
- Post engagement metrics are lifetime aggregates. Profile-level metrics have a **60-day look-back**.
- reach, watch time, impression_sources, and audience_* may be missing if the video has had no activity for over 7 days.
- Data is only available if it is also visible in TikTok Analytics in the app.
- There is also "Get profile data of a TikTok account" (profile-level time series), "Get benchmarks for a business category", and comments endpoints. Their exact profile metrics are UNVERIFIED - check docs.

### 1.7 Competitor / public data access
- **No officially permitted way for a commercial tool to read another account's video list or stats** through TikTok for Developers. Display API and video query are limited to the authorizing user.
- **oEmbed** (`GET https://www.tiktok.com/oembed?url=...`, no auth) returns title, author_name, author_url, thumbnail, and embed html for a public video URL. **No engagement stats.**
- **Research API:** public videos, comments, user profiles, followers/following, liked, pinned, and reposted videos.
  - **Eligibility:** academic institutions in US/EEA/UK/Canada/Switzerland, some not-for-profit research orgs, and Brazilian youth-safety researchers. Applicants must be "independent of commercial interests" and need ethical review.
  - FAQ: "I am a creator, advertiser, or commercial user. Am I eligible ...? No."
  - Quotas: 1,000 req/day (≈100k records/day); followers API 20k calls/day (2M records). Data lag: new videos up to 48 h; stats up to 10 days.
- **Commercial Content API:** public **ad** data only (ads, advertisers, other commercial content), EU data only. Requires an application with a 1-2 week review (secondary source for the timing). Not organic competitor stats.
- **Business API Discovery API:** "emerging trends in hashtags, themes, and Commercial Music Library tracks". **Mentions API:** "Track mentions of your brand and products in trending organic videos". These are trend-level, not per-competitor stats. Exact fields: UNVERIFIED - check docs.
- **Bottom line:** competitor TikTok analytics would need scraping or third-party data vendors. Neither is officially permitted by TikTok.

### 1.8 Rate limits & quotas
| Endpoint | Limit |
|---|---|
| `/v2/user/info/`, `/v2/video/list/`, `/v2/video/query/` | 600 req/min (1-minute sliding window). Error: HTTP 429 `rate_limit_exceeded` |
| Direct Post video init, photo content init, inbox video init | **6 req/min per user access_token** |
| creator_info query | 20 req/min per user token |
| status fetch | 30 req/min per user token |
| Posts per creator per 24 h (Direct Post) | "typically around **15** posts per day/creator account". **Shared across all API clients** (`spam_risk_too_many_posts`) |
| Pending inbox uploads | 5 per 24 h |
| Active publishing creators per client | Cap set during audit (`reached_active_user_cap`) |
| Business API video publish | 6 posts/min, max **15/day** per account |
| Research API | 1,000 req/day; resets 00:00 UTC |

### 1.9 Known limitations & gotchas
- Unaudited = private only (SELF_ONLY), only private accounts, and at most 5 posting users per 24 h. An internal tool for "accounts you or your team manages" is an explicitly unacceptable use case.
- App review rejects apps for "private or personal use". A single-user desktop tool may not pass.
- Desktop PKCE uses a **hex** SHA-256 challenge (non-standard). Redirect must be localhost/127.0.0.1 with a port.
- Photo posts need publicly hosted images on a **verified domain**. A desktop app has no simple local-file option for photos, so you need your own hosting or CDN with domain verification.
- No API scheduling. No delete. No captions/subtitle upload. No custom cover image in the developers.tiktok.com API (only a frame timestamp).
- The ~15 posts/day cap is shared across every third-party tool the creator uses.
- `cover_image_url` expires after 6 h, `creator_avatar_url` after 2 h. Re-fetch them; don't cache.
- Display API stats are lifetime totals with no history. Business API metrics lag 24-48 h and stop updating after 365 days.
- The Business API is a separate developer registration, OAuth, and review. Since March 20, 2026 it also requires the Accounts API Access Application Form.

### 1.10 Notable changes 2025-2026
- **2026-03-20 (Business API):** new mandatory **Accounts API Access Application Form** before new apps or scope increases that include "TikTok Accounts".
- **2026-01-23 (context, secondary source):** the TikTok USDS Joint Venture (US entity) closed. I found **no official developer changelog entry** about US-specific API availability changes. UNVERIFIED - check docs and the portal for US-region notices.
- **TikTok for Developers changelog (official, latest entry 2026-08-25):** nearly all 2025-2026 entries are about the Research API, Data Portability, TikTok GO, Mini Games, and Hotels:
  - Research API added favorites_count and comment display_name (2026-05-21).
  - Research data pipeline now includes videos excluded from the recommendation feed (2026-02-26).
  - Data access opened for vetted (DSA) researchers (2025-12-23).
  - Batch Compliance APIs (2025-05-16) and new Research fields (2025-04-17).
- **No official changelog entries** for 2025-2026 Content Posting API audit-rule changes. The current rules are as quoted above.
- Photo posting (up to 35 images), `is_aigc`, and post webhooks are in the current docs. Their launch dates were not confirmed in the changelog window I checked.

### 1.11 Source URLs (TikTok)
- https://developers.tiktok.com/doc/content-posting-api-get-started
- https://developers.tiktok.com/doc/content-sharing-guidelines
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-reference-photo-post
- https://developers.tiktok.com/doc/content-posting-api-reference-upload-video
- https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info
- https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status
- https://developers.tiktok.com/doc/oauth-user-access-token-management
- https://developers.tiktok.com/doc/login-kit-desktop
- https://developers.tiktok.com/doc/tiktok-api-scopes
- https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info
- https://developers.tiktok.com/doc/tiktok-api-v2-video-list
- https://developers.tiktok.com/doc/tiktok-api-v2-video-query
- https://developers.tiktok.com/doc/tiktok-api-v2-video-object
- https://developers.tiktok.com/doc/tiktok-api-v2-rate-limit
- https://developers.tiktok.com/doc/display-api-overview
- https://developers.tiktok.com/doc/embed-videos
- https://developers.tiktok.com/doc/app-review-guidelines
- https://developers.tiktok.com/doc/add-a-sandbox
- https://developers.tiktok.com/doc/changelog
- https://developers.tiktok.com/doc/research-api-faq
- https://developers.tiktok.com/products/research-api/
- https://developers.tiktok.com/products/commercial-content-api
- https://ads.tiktok.com/help/article/marketing-api
- https://business-api.tiktok.com/portal/docs/get-post-data-of-a-tiktok-account/v1.3
- https://business-api.tiktok.com/portal/docs/publish-a-public-video-post-to-an-owned-account/v1.3
- Secondary (JV context only): https://www.mactrast.com/2026/01/tiktok-finalize-joint-venture-deal-to-avoid-us-bans/amp/

---

## 2. YouTube (Data API v3, Analytics API, Reporting API)

### 2.1 OAuth & tokens
- Standard Google OAuth 2.0. For desktop/installed apps, use **PKCE** (`code_challenge = BASE64URL(SHA256(verifier))`, S256) and a **loopback redirect** `http://127.0.0.1:port` or `http://[::1]:port` on a random free port. The OOB flow is deprecated and no longer supported.
- **Access tokens** are short-lived. Use `expires_in` from the token response. The doc's example shows ~3,600-3,920 s. "1 hour" is the common value; the exact figure is UNVERIFIED - check docs.
- **Refresh tokens** "are always returned for installed applications" and are valid until revoked or expired. A refresh token stops working when:
  - the user revokes access;
  - it has been **unused for 6 months**;
  - the account exceeds the limit of **100 refresh tokens per Google Account per OAuth client ID** (the oldest is silently invalidated);
  - the user granted time-based access;
  - an admin set the requested scopes' services to Restricted;
  - Workspace session-control policies end the session.
- **Testing-status gotcha (verified):** "A Google Cloud Platform project with an OAuth consent screen configured for an external user type and a publishing status of 'Testing' is issued a refresh token expiring in **7 days**". The exception is when only name, email, and profile scopes are requested. YouTube scopes are therefore affected, so publish the consent screen to "In production" for real use.

### 2.2 Account types
- Any Google account with a YouTube channel. Brand Account channels are selected during the consent flow.
- Content owners (CMS partners) use `onBehalfOfContentOwner`.
- Monetary analytics need a channel in the YouTube Partner Program. Non-YPP channels get HTTP 403 for revenue metrics.

### 2.3 Scopes
| Scope | Consent text / use |
|---|---|
| `https://www.googleapis.com/auth/youtube.upload` | "Manage your YouTube videos" (videos.insert, thumbnails.set) |
| `.../youtube` | "Manage your YouTube account" (broad read/write) |
| `.../youtube.force-ssl` | "See, edit, and permanently delete your YouTube videos, ratings, comments and captions" (captions, comments, delete) |
| `.../youtube.readonly` | "View your YouTube account". As of 2026-09-01 also accepted by videos.getRating |
| `.../yt-analytics.readonly` | YouTube Analytics / Reporting (non-monetary) |
| `.../yt-analytics-monetary.readonly` | Revenue / ad metrics (YPP channels only) |
| `.../youtubepartner`, `.../youtube.channel-memberships.creator`, `.../youtubepartner-channel-audit` | Partner / memberships / audit use cases |

### 2.4 App review / audit & verification
There are **two independent processes**.

1. **Google OAuth app verification** (Google Cloud):
   - Needed before a public launch that requests sensitive or restricted scopes.
   - Unverified apps show the "unverified app" screen and are capped at **100 new users in total**.
   - Sensitive-scope verification = brand verification plus a privacy policy (disclosing Google user-data use), a homepage on a verified domain (Search Console), a demo video of the OAuth flow and the scope use, and a per-scope justification.
   - Changing scopes later can trigger re-verification.
   - Whether YouTube scopes are classed as "sensitive" or "restricted": believed sensitive, not restricted. UNVERIFIED - check the Cloud Console Data Access page.
   - Test-user cap in Testing mode (commonly 100): UNVERIFIED - check docs.
2. **YouTube API Services compliance audit:**
   - "All videos uploaded via the videos.insert endpoint from unverified API projects created after 28 July 2020 will be restricted to **private viewing mode**. To lift this restriction, each API project must undergo an audit".
   - The audit is also required for **any quota increase** (Audit and Quota Extension Form).
   - Periodic audits happen. Change of control requires a form.
   - The new (June 2026) derived-metrics and long-term storage permissions are requested through this same quota-extension form, under "Analytics & Reporting".

### 2.5 Publishing capabilities
**Uploads (`POST https://www.googleapis.com/upload/youtube/v3/videos`):**
- Use the **resumable upload** protocol: start a session with `uploadType=resumable` plus `X-Upload-Content-Length` and `X-Upload-Content-Type` headers, then PUT bytes to the session URL. On interruption, query the status, read the `Range` header from the 308 response, and resume.
- Max file size **256 GB**. MIME type `video/*` or `application/octet-stream`.
- `notifySubscribers` defaults to true.
- `uploadLimitExceeded` occurs when a channel exceeds its (undocumented) upload count.

**Metadata rules (videos resource):**
- `snippet.title`: max **100 chars**, no `<` or `>`.
- `snippet.description`: max **5,000 bytes** (bytes, not characters), no `<` or `>`. Clickable links need channel verification / Advanced Features.
- `snippet.tags`: **500 chars total**. Commas count, and a tag containing a space counts its implied quotes (e.g. "Foo Baz" = 9).
- `snippet.categoryId`: required on videos.update.
- `status.privacyStatus`: private, public, or unlisted.
- `status.selfDeclaredMadeForKids` and `status.containsSyntheticMedia` (AI/altered-content disclosure, added Oct 2024).
- `status.publicStatsViewable`.
- `brandPartner` part (July 2026): link a brand partner channel via channelId or channelHandle.

**Scheduling:** `status.publishAt` (ISO 8601) "can only be set if the video's privacy status is **private** and the video has never been published". A time in the past publishes immediately. Error: `invalidPublishAt`.

**Shorts:**
- No API flag. Any upload **up to 3 minutes with a square or vertical aspect ratio** is categorized as a Short. This applies from **Oct 15, 2024**.
- Shorts over 1 minute with **any active Content ID claim are blocked globally**.

| Capability | YouTube Data API v3 |
|---|---|
| Text-only post (Community/"Posts") | **Not available.** There is no posts/community resource in the v3 reference (resources: activities, captions, channelBanners, channelSections, channels, commentThreads, comments, members, membershipsLevels, playlistImages, playlistItems, playlists, search, subscriptions, thumbnails, videoAbuseReportReasons, videoCategories, videos, watermarks) |
| Image(s) | Only as thumbnails, channel banners, playlist images, or watermarks. No image posts |
| Video | Yes: `videos.insert` (resumable), ≤256 GB |
| Short-form | Yes: same `videos.insert`; classified automatically (≤3 min, square/vertical) |
| Scheduling via API | Yes: `status.publishAt` with `privacyStatus=private` (blocked in practice until the audit passes, since unaudited uploads are locked private) |
| Thumbnails | `thumbnails.set` (~50 units). **Max 50 MB since 2026-09-14** (was 2 MB), JPEG/PNG. The account must be allowed custom thumbnails (YouTube Help: "if your account is verified"); otherwise 403. Shorts custom thumbnails are "currently only available ... in YouTube Studio on a computer", so API support for Shorts thumbnails is UNVERIFIED - check docs |
| Captions | `captions.insert` (400 units, ≤100 MB, `snippet.isDraft` supported). The `sync` param is unsupported since Apr 12, 2024 (per revision history), so timed caption files are required |
| Playlists | playlists.insert/update/delete and playlistItems.insert (50 units each) |
| Comments | commentThreads.insert (50) and list (1); comments.insert, setModerationStatus, delete (50). As of Sept 2026 comments have `snippet.imageUrl` (image/GIF comments), available to all users Nov 2026 |
| Delete | videos.delete (50 units) |
| Update metadata | videos.update (50 units) |

### 2.6 Analytics capabilities
**Data API (public, near-real-time):**
- `videos.list part=statistics` returns viewCount, likeCount, and commentCount. `dislikeCount` is private since Dec 13, 2021 (owner-only), and `favoriteCount` is always 0.
- `channels.list part=statistics` returns viewCount, subscriberCount (**rounded down to 3 significant figures**), hiddenSubscriberCount, and videoCount.
- **New `videos.batchGetStats`** (2026-06-03): `GET /youtube/v3/videos:batchGetStats`, 1 unit per call in its own bucket (10,000/day default). No auth needed for public videos. Returns viewCount, likeCount, commentCount, publishTime, and duration, plus a summary of failed IDs. The maximum number of IDs per call is UNVERIFIED - check docs.
- **View-count semantics changed:**
  - Shorts: from Mar 31, 2025 a view = each start or replay.
  - All formats: per the 2026-08-27 entry, public views now count "the moment a video begins to play". "Engaged views" keep the old methodology.

**YouTube Analytics API (`reports.query`, targeted queries):** owner/authorized data only.
- Metrics include:
  - views, **engagedViews**, estimatedMinutesWatched, averageViewDuration, averageViewPercentage, redViews;
  - likes, dislikes, comments, shares, subscribersGained, subscribersLost;
  - playlist metrics (playlistStarts, playlistSaves, ...);
  - card metrics (cardImpressions, cardClicks, cardClickRate, cardTeaser*);
  - annotation metrics (annotationClickThroughRate, etc.), which are still listed but meaningless since annotations were retired;
  - estimatedRevenue and related metrics (monetary scope).
- Dimensions verified: day, month, video, country, insightTrafficSourceType, insightTrafficSourceDetail, deviceType, operatingSystem, ageGroup, gender, creatorContentType (Shorts/Videos/Live etc.), subscribedStatus, youtubeProduct, liveOrOnDemand, elapsedVideoTimeRatio (retention), sharingService.
- From 2026-03-09, ageGroup includes users estimated to be under 18.
- **Latency:** "Data processing typically introduces a latency of **48 to 72 hours**". endDate is truncated to the last fully processed day. Use `videos.list` for real-time counts. This was formalized in the docs on 2026-09-09.
- Invalid dimension/metric combinations return 400 "The query is not supported."
- **Impressions and impression CTR are not Analytics API metrics.** They are only available via the Reporting API reach reports (below).

**YouTube Reporting API (bulk):**
- Schedule a job per report type. You get daily CSVs covering 24 h. The first reports arrive within 48 h of job creation, plus 30 days of historical backfill.
- Reports are downloadable for **60 days** (historical reports for 30 days). You must handle **backfill** reports, which carry new IDs for the same time range.
- Channel report types: channel_basic_a3, channel_combined_a3, channel_device_os_a3, channel_playback_location_a3, channel_province_a3, channel_traffic_source_a3, channel_demographics_a1, channel_sharing_service_a2, channel_subtitles_a3, channel_cards_a1, channel_end_screens_a2, channel_annotations_a2, plus **channel_reach_basic_a1 / channel_reach_combined_a1**.
- The reach reports were **added 2026-01-15** with `video_thumbnail_impressions` and `video_thumbnail_impressions_ctr`.
- Report versions were bumped (e.g. a2→a3) on 2025-06-30 for the Shorts view change. These versions add an `engaged_views` column. Old versions were deprecated Oct 31, 2025.

### 2.7 Competitor / public data access (officially allowed, with policy limits)
- **Allowed:**
  - `videos.list` / `videos.batchGetStats` for **any public video** (views, likes, comments).
  - `channels.list` for any channel (subscribers rounded, views, video count).
  - `search.list` with `channelId`.
  - Better: read the channel's **uploads playlist** via `playlistItems.list` (1 unit). The search docs themselves say "To reliably retrieve a channel's most recently uploaded videos, do not use search.list". search.list with channelId + type=video is capped at 500 results.
  - Public comments via commentThreads.list.
- **Not available for competitors:** Analytics/Reporting (owner-only), watch time, retention, traffic sources, demographics, impressions.
- **Developer Policy limits (important for an analytics product):**
  - "An API Client must not store statistics retrieved as Non-Authorized Data for more than **30 days**". Example from the policy: you can't keep a competitor's subscriber count longer than 30 days without the owner's authorization.
  - Other non-authorized data must be deleted or refreshed every 30 days.
  - Authorized (own-channel) statistics and Analytics/Reporting data may be stored longer, but authorization must be re-verified every 30 days.
  - "must not ... access or use API Data to create new or derived data or metrics". Data aggregation across content owners is also restricted.
- **NEW (June 1, 2026) exception, "Additional policies for derived metrics and data storage":**
  - Audited developers with an "Analytics & Reporting" use case can accept a policy amendment through the quota-extension form.
  - It allows derived metrics: custom channel scores and ratios, revenue estimates labelled as third-party, own tagging, sentiment, leaderboards and comparisons, and brand suitability/safety (planning).
  - Accepted clients may store **statistics (views, likes, subs, comment counts) and derived metrics for up to 36 calendar months**. Titles, descriptions, and comment text still follow the 30-day rule.
  - Derived metrics must be clearly distinguished from YouTube data.

### 2.8 Rate limits & quotas
**Granular quota system (major change).** Since 2026-06-01, quota is split into buckets per the quota page. The page's own AI summary is stale and still says 1600.

| Bucket | Default daily |
|---|---|
| **Video Uploads** (`videos.insert`) | **100 calls/day**, 1 unit per call |
| **Search Queries** (`search.list`) | **100 calls/day**, 1 unit per call |
| `videos.batchGetStats` | 10,000 units/day, 1 per call |
| Everything else | 10,000 units/day combined |

- Before that, on 2025-12-04, the upload cost dropped from ~1,600 to ~100 units.
- **The often-cited "videos.insert = 1,600 units; search.list = 100 units" figures are obsolete.**
- Costs in the general bucket:
  - 1 unit: list calls (videos, channels, playlistItems, commentThreads, comments, activities, subscriptions, ...).
  - 50 units: videos.update/delete/rate, thumbnails.set (~50), playlists.insert/update/delete, playlistItems.insert, commentThreads.insert, comments.insert/update/delete/setModerationStatus, channels.update, watermarks.
  - captions.list 50, captions.insert 400, captions.update 450, captions.delete 50.
- Every request, even an invalid one, costs ≥1 unit. Each extra page costs again. Quotas reset at **midnight Pacific Time**.
- More quota requires the compliance audit.
- Other limits: per-minute/per-user limits shown in the Cloud Console (UNVERIFIED - exact defaults not documented in the pages read). There is also a per-channel upload limit (`uploadLimitExceeded`, number not documented).

### 2.9 Known limitations & gotchas
- Unaudited projects: every upload is locked **private**, so publishAt scheduling to public effectively needs the audit. Plan the audit early.
- Testing-mode consent screen means refresh tokens die after **7 days**. Unverified production apps are capped at 100 users. OAuth verification and the YouTube audit are separate queues.
- Community/text/image posts cannot be published by API.
- Descriptions are limited in **bytes** (5,000). Tags count quotes and commas.
- Shorts are inferred (≤3 min, square/vertical). Shorts over 1 min with a Content ID claim get blocked. Custom Shorts thumbnails may not be settable via the API.
- subscriberCount is rounded. dislikeCount is owner-only.
- View-count definition changed in 2025 (Shorts) and in 2026 (all formats). Historic time series will show a step change. Use `engagedViews` for continuity.
- Analytics is 48-72 h behind. There are no impressions/CTR in `reports.query`; use Reporting API reach reports, which have 60-day download windows and backfills.
- Competitor stats can't be stored longer than 30 days unless you are audited and accepted under the June 2026 derived-metrics policy.
- On revocation: delete Authorized Data within 7 days (and all related API Data within 30). The privacy policy must link https://security.google.com/settings/security/permissions. You must also provide an in-app "delete my data" option (7-day SLA).

### 2.10 Notable changes 2025-2026 (official revision histories)
- 2025-03-26 / 03-31: Shorts views count every start or replay.
- 2025-06-24 / 06-30: Reporting API report versions bumped and an `engaged_views` column added. Old versions deprecated 2025-10-31.
- 2025-07-21: the `mostPopular` chart now uses Trending Music/Movies/Gaming (Trending page deprecated).
- 2025-12-04: upload quota cost ~1,600 → ~100 units.
- 2026-01-15: Reporting API **reach reports** (thumbnail impressions + CTR).
- 2026-03-09: ageGroup includes estimated under-18 viewers.
- 2026-06-01: **granular quota buckets.** videos.insert and search.list each get 100 calls/day at 1 unit per call. Derived-metrics/36-month storage policy available to audited analytics apps.
- 2026-06-03: **videos.batchGetStats** method.
- 2026-07-07: `brandPartner` part on videos.
- 2026-08-27: public views count from the first frame for all formats.
- 2026-09-01: getRating accepts youtube.readonly.
- 2026-09-09: Analytics docs formalize 48-72 h latency and the YPP-only monetary metrics (403 otherwise).
- 2026-09-11: fhd/qhd/uhd thumbnail sizes in responses.
- 2026-09-14: thumbnails.set and playlistImages.insert max **50 MB**.
- 2026-09-30: `comments.snippet.imageUrl` (rolls out Nov 2026).

### 2.11 Source URLs (YouTube / Google)
- https://developers.google.com/youtube/v3/determine_quota_cost
- https://developers.google.com/youtube/v3/revision_history
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/docs/videos
- https://developers.google.com/youtube/v3/docs/videos/list
- https://developers.google.com/youtube/v3/docs/videos/batchGetStats
- https://developers.google.com/youtube/v3/docs/channels
- https://developers.google.com/youtube/v3/docs/search/list
- https://developers.google.com/youtube/v3/docs/thumbnails/set
- https://developers.google.com/youtube/v3/docs/captions/insert
- https://developers.google.com/youtube/v3/docs (resource list)
- https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits
- https://developers.google.com/youtube/v3/guides/auth/installed-apps
- https://developers.google.com/identity/protocols/oauth2
- https://developers.google.com/youtube/terms/developer-policies
- https://developers.google.com/youtube/terms/derived-metrics-policy
- https://developers.google.com/youtube/analytics/metrics
- https://developers.google.com/youtube/analytics/dimensions
- https://developers.google.com/youtube/analytics/data_model
- https://developers.google.com/youtube/analytics/reference/reports/query
- https://developers.google.com/youtube/analytics/revision_history
- https://developers.google.com/youtube/reporting/v1/reports
- https://developers.google.com/youtube/reporting/v1/reports/channel_reports
- https://support.google.com/youtube/answer/15424877 (Shorts up to 3 min)
- https://support.google.com/youtube/answer/72431 (custom thumbnails)
- https://support.google.com/cloud/answer/13464321 (sensitive scope verification)
- https://support.google.com/cloud/answer/7454865 (unverified apps, 100-user cap)
