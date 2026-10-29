# Social API capability research: LinkedIn, X, Pinterest, Google Business Profile

Research date: 2026-10-08. Sources are official developer docs unless a line says **(secondary source)**. Anything I could not confirm is marked **UNVERIFIED - check docs**.

---

## 1. LinkedIn (Marketing / Community Management APIs)

### OAuth & tokens
- OAuth 2.0 authorization code flow (3-legged). Authorize at `https://www.linkedin.com/oauth/v2/authorization`. Token endpoint is `https://www.linkedin.com/oauth/v2/accessToken`.
- **Access token:** 60 days by default.
- **Refresh tokens:** these are "programmatic refresh tokens", and LinkedIn gives them only to **approved Marketing Developer Platform (MDP) partners**: "LinkedIn supports programmatic refresh tokens for all approved Marketing Developer Platform (MDP) partners." A refresh token lasts 365 days, and that lifetime is fixed. Refreshing does **not** reset it. Example from the docs: if you refresh on day 59, the refresh token has 306 days left. When it expires, the member has to go through OAuth again. LinkedIn "reserves the right to revoke Refresh Tokens or Access Tokens at any time."
- Apps without refresh tokens (for example, apps that only use Share on LinkedIn or OIDC) must send the user back through OAuth every 60 days.
- Plan for tokens up to 1000 characters.
- **Sign In with LinkedIn using OpenID Connect:** scopes are `openid`, `profile`, `email`. It returns an ID token (RS256 JWKS) with the claims sub, name, given_name, family_name, picture, email, email_verified and locale. The docs say OIDC "does not verify user identities."

### Account types
- **Member (personal profile):** author `urn:li:person:{id}`.
- **Organization (Company Page / Showcase "brand"):** author `urn:li:organization:{id}`. The authenticated member needs one of these page roles: ADMINISTRATOR, CONTENT_ADMIN or DIRECT_SPONSORED_CONTENT_POSTER. Analytics endpoints need ADMINISTRATOR.

### Scopes/permissions
| Scope | Product | Notes |
|---|---|---|
| `openid`, `profile`, `email` | Sign In with LinkedIn using OIDC | Open permission (self-serve) |
| `w_member_social` | Share on LinkedIn | Open permission (self-serve). Post, comment and like as the member |
| `r_member_social` | Community Mgmt (Member Post Management) | **CLOSED**: "We're not accepting access requests at this time due to resource constraints." |
| `r_member_postAnalytics` | Community Management API (Member Analytics) | Analytics on the authenticated member's own posts |
| `w_organization_social` | Community Management API | Post, comment and like as an org (ADMIN, CONTENT_ADMIN or DSC poster) |
| `r_organization_social` | Community Management API | Read the org's posts, comments and likes |
| `rw_organization_admin` | Community Management API | Manage pages and read reporting data (share, follower and page stats). ADMINISTRATOR only |
| `r_organization_admin` | Community Management API | UNVERIFIED - check docs. The stats pages I fetched list only `rw_organization_admin` |

- The Getting Access page says "Open Permissions are the only permissions that are available to all developers without special approval." These are openid/profile/email (OIDC) and w_member_social (Share on LinkedIn). **Everything else needs approval.**

### App review & verification requirements (Community Management API)
- It is a **vetted product with a Development tier and a Standard tier.**
- **Who can apply:** "Community Management APIs are only available to registered legal organizations for commercial use cases only." You need:
  - a business email address that gets verified (personal emails fail)
  - the legal name, registered address, website and privacy policy
  - the app **verified by a super admin of the LinkedIn Page** for your organization
  - an app name and logo that do not use "Linked", "In" or any LinkedIn or Microsoft branding
- **Development tier** checks: approved use case, verified email, verified organization, verified website and domain, and the app verified by the Page. The FAQ gives Development tier rate limits of **500 requests per app per day and 100 per member per day** (raised from 100 and 10).
- **Standard tier** is an upgrade form under My Apps > Products. It requires:
  - full integration, a company and product overview, and **test credentials** for reviewers
  - a **high-resolution, downloadable screencast** (narration recommended) showing every declared use case. For example, for Page Management: the full OAuth flow, posting to a page, how a comment by a member appears in your app, and which commenter profile fields you show. Analytics, Executive (member posting) and Employee Advocacy use cases have their own required demos.
  - a valid privacy policy and compliance with the data storage requirements
  - a "Technical Sign Off" against the Integration Requirements
- **Rejections:** you cannot re-apply with the same app. You have to create a new app and start over at the Development tier.
- **The Community Management API must be requested on a new app with no other products.** The request option is greyed out if the app has other API products. Advertising API partners create a throwaway verification app first.
- **Review timeline:** not published in the docs. UNVERIFIED - check docs. Community reports suggest weeks, but I did not verify that.
- **Self-serve vs application-only:** Share on LinkedIn and Sign In with OIDC are self-serve and added instantly from the Products tab. Community Management, Advertising API and the other Marketing APIs require an application.

### Versioning (REST `/rest/*`)
- Every call needs the header `Linkedin-Version: YYYYMM` and `X-Restli-Protocol-Version: 2.0.0`. "No unversioned calls": if the header is missing or deprecated, you get an error.
- New versions ship **monthly**, and each is supported "for a minimum of one (1) year." The latest is **202609 (September 2026)**. Docs currently cover 202510 to 202609. **Version 202510 sunsets on October 15, 2026.** LinkedIn may ship patch-level breaking changes for security or privacy.
- The Posts API (`/rest/posts`) replaces `ugcPosts`. The Videos and Images APIs replace the Assets API. The Share on LinkedIn doc page still shows the legacy `/v2/ugcPosts` and `/v2/assets?action=registerUpload` flow (page last updated 2023).

### Publishing capabilities (Posts API `/rest/posts`)
| Capability | Supported? | Details |
|---|---|---|
| Text | Yes | `commentary` uses "little" text format. @mentions work as `@[Name](urn:li:organization:...)` and hashtags are supported. Over-long text returns FIELD_LENGTH_TOO_LONG (max length not stated on the page) |
| Single image | Yes | Images API `initializeUpload` → upload → `urn:li:image:`. JPG/GIF/PNG under 36,152,320 pixels. GIF up to 250 frames |
| Multi-image | Yes (organic only) | MultiImage: **2 to 20 images**. Not available for sponsored posts |
| Carousel (swipe cards) | **No for organic** | "Organic carousel is currently not supported" (sponsored only) |
| Video | Yes | Videos API `initializeUpload` with `fileSizeBytes` → multipart upload in 4 MB parts, sending ETags → `finalizeUpload` → `urn:li:video:`. "Maximum allowed Videos size is 5GB." Optional captions and thumbnail. (Ads-spec pages quote 3 seconds to 30 minutes and 75 KB to 500 MB for video ads) |
| Document / PDF carousel | Yes | Documents API → `urn:li:document:`. PPT, PPTX, DOC, DOCX, PDF. **Max 100 MB and 300 pages** |
| Polls | Yes (organic only) | 2 to 4 options. Duration ONE_DAY, THREE_DAYS, SEVEN_DAYS or FOURTEEN_DAYS. Single vote only. Polls cannot be edited |
| Link preview | Partial | **No URL scraping.** "API partners must set article fields such as thumbnail, title, and description" yourself. Upload the thumbnail through the Images API |
| Reshare | Yes | `reshareContext.parent` |
| Targeted organic (org only) | Yes | Audience must be over 300 followers |
| Scheduling via API | **No** | `lifecycleState`: "PUBLISHED is the only accepted field during creation." There is no publish-at field, so you must schedule yourself |
| Edit | Partial | PARTIAL_UPDATE of `commentary`, CTA label, landing page, lifecycleState and adContext only |
| Delete | Yes | `DELETE /rest/posts/{urn}` is idempotent (204). No batch delete |
| Comments / reactions | Yes | Comments API and Reactions API with w_organization_social or w_member_social. Social Metadata API can turn comments on or off |

### Analytics capabilities
- **Organization share statistics** (`organizationalEntityShareStatistics`, needs `rw_organization_admin` with the ADMINISTRATOR role):
  - Metrics: impressionCount, uniqueImpressionsCount, clickCount, likeCount, commentCount, shareCount, engagement.
  - Organic only.
  - Can be **lifetime** or **time-bound** at DAY or MONTH granularity.
  - Only "share data only within the past 12 months, using a rolling 12-month window."
  - **Per-post** stats work through `shares=List(...)` / `ugcPosts[...]`, but time-bound is NOT supported for specific posts (lifetime only).
  - No pagination. Posts with zero activity are omitted.
- **Follower statistics** (`organizationalEntityFollowerStatistics`, `rw_organization_admin`):
  - **Lifetime** returns demographic facets (association, country, function, industry, geo, seniority, staff count range), top 100 per facet.
  - **Time-bound** (DAY, WEEK or MONTH) returns organic and paid follower gains with no demographics. The window runs from 12 months back to 2 days before the request.
  - The total follower count comes from `networkSizes`.
- **Page statistics** (`organizationPageStatistics` / `brandPageStatistics`, `rw_organization_admin`): page views and clicks, split by mobile, desktop and overall and by page section. Lifetime or DAY/MONTH time-bound.
- **Video analytics:** watch time, video views and viewers, for both org and member videos.
- **Social Metadata API:** reactions by type and comment counts per post.
- **Member (personal) post analytics: YES, now available.** `memberCreatorPostAnalytics` with `r_member_postAnalytics`:
  - Single post (`q=entity`) or aggregated across all the member's posts (`q=me`).
  - Metrics: IMPRESSION, MEMBERS_REACHED, RESHARE, REACTION, COMMENT. Since 202604 it adds POST_SAVE, POST_SEND, LINK_CLICKS, PREMIUM_CTA_CLICKS, FOLLOWER_GAINED_FROM_CONTENT and PROFILE_VIEW_FROM_CONTENT.
  - Aggregation is TOTAL or DAILY. DAILY is not supported for MEMBERS_REACHED, LINK_CLICKS, FOLLOWER_GAINED or PROFILE_VIEW, and "Daily impression metrics are not supported if given entity is post."
  - The docs warn that RESHARE, REACTION and COMMENT in the `me` aggregate are "not consistent with UI."
  - Member follower stats and member video stats also exist.
- Gotcha: `r_member_social` is closed, so you **cannot list a member's posts through the API**. Store the post URNs your app creates.

### Competitor/public data access
- **You cannot get another organization's posts or analytics.** `r_organization_social` and all stats endpoints are limited to orgs where the member holds a page role.
- **Allowed for any organization:**
  - Organization lookup by ID or vanity name returns only id, name, localizedName, website, vanityName, logo, locations and primaryOrganizationType.
  - `GET /rest/networkSizes/urn:li:organization:{id}?edgeType=COMPANY_FOLLOWED_BY_MEMBER` returns the **follower count of any organization**, so a competitor follower-count tracker is possible.
- Restricted uses:
  - No social feeds and no advertising, sales or recruiting uses of member data.
  - No combining or exporting member data.
  - Member data is only shown to people associated with that Page or Profile.
  - **Member social activity data may be stored for 48 hours at most, and most member profile data for 24 hours.**

### Rate limits, quotas & pricing
- Limits are daily and reset at midnight UTC, applied per application and per member. "Standard rate limits are not published." To see an endpoint's limit, call it once and check the app's Analytics tab in the Developer Portal. Over-limit calls return 429. Admins get an email at 75% of app quota, 1 to 2 hours delayed.
- Share on LinkedIn: **150 requests per member per day and 100,000 per app per day.**
- Community Management Development tier: 500 per app per day and 100 per member per day. Standard tier limits are higher but not published.
- **No API fees.**

### Known limitations and gotchas
- There is no native scheduling, no organic carousel, and no link scraping (you supply the title, description and thumbnail).
- Refresh tokens are only for approved MDP or Community Management apps. Even then the 365-day hard cap forces yearly re-auth.
- Monthly versioning means you must bump the version header at least yearly.
- `r_member_social` is closed, which blocks listing member posts and reading member post comments. Reading comments on member posts: UNVERIFIED - check docs.
- The 48h/24h storage caps on member data affect comment and inbox features.
- Every new app has to start at the Development tier, and a rejection means building a new app.
- Like counts can be negative (sponsored unlike counted as organic). Time-bound shareCount excludes instant reposts.

### Notable changes 2025-2026
- `memberCreatorPostAnalytics` (personal post analytics) gained six new metrics in 202604.
- Development tier limits were raised to 500 per app and 100 per member.
- Version 202510 sunsets on 2026-10-15. The latest version is 202609.

### Source URLs
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- https://learn.microsoft.com/en-us/linkedin/marketing/versioning
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/share-statistics
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/follower-statistics
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/page-statistics
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-lookup-api
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/{documents-api, multiimage-post-api, images-api, videos-api, poll-post-api}
- https://learn.microsoft.com/en-us/linkedin/marketing/restricted-use-cases
- https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/rate-limits
- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
- https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access

---

## 2. X (Twitter) API v2

### OAuth & tokens
- OAuth 2.0 Authorization Code with PKCE. Authorize at `https://x.com/i/oauth2/authorize`. The token endpoint is `https://api.x.com/2/oauth2/token` (UNVERIFIED - check docs for the exact host).
- Supports confidential clients (web apps and bots holding a secret) and public clients (native apps and SPAs).
- **Access token:** "will only stay valid for two hours unless you've used the `offline.access` scope." `offline.access` is required to get a refresh token.
- Refresh token lifetime and rotation are not stated on the page I read. UNVERIFIED - check docs; they are commonly single-use and rotating.
- OAuth 1.0a user context is still supported. **New (Sep 21, 2026):** you can migrate OAuth 1.0a user tokens to OAuth 2.0 without re-auth through token exchange (`grant_type=urn:ietf:params:oauth:grant-type:token-exchange`).
- App-only Bearer token: for public reads only.

### Account types
- Standard and X Premium/verified accounts differ in media limits:
  - Video: default 20 minutes and 8 GB; Premium/verified 125 minutes and 16 GB.
  - Post editing is Premium only.
- No separate "business" account type in the API.

### Scopes/permissions
- Read: tweet.read, users.read, follows.read, like.read, bookmark.read, dm.read, space.read, list.read, mute.read, block.read
- Write: tweet.write, follows.write, like.write, bookmark.write, dm.write, **media.write**, list.write, mute.write, block.write
- Other: offline.access
- `POST /2/tweets` needs tweet.write, tweet.read and users.read. Media upload needs media.write.

### App review & verification requirements
- No app review for self-serve. You create a project and app in the Developer Console, buy credits (pay-per-use), and accept the Developer Agreement. Enterprise is sales-led.

### Pricing (BIG CHANGE)
- **Feb 6, 2026: Pay-Per-Use (PPU), credit-based, became the default for all new developers.** It was piloted Oct 20, 2025. "No subscriptions... No contracts, subscriptions, or minimum spend." You buy credits upfront in the Developer Console, and a spending cap per billing cycle blocks requests once it is reached.
- Read prices (per resource returned):

| Resource read | Price |
|---|---|
| Posts | $0.005 |
| Users | $0.010 |
| Followers/Following | $0.010 |
| DM events | $0.010 |
| Lists, Spaces, Communities, Notes | $0.005 |
| Likes, Mutes, Blocks | $0.001 |
| **Owned reads** (your app reading your own users' data, effective Apr 20, 2026) | $0.001 per resource |

- Write prices (per request):

| Write | Price |
|---|---|
| Post create | **$0.015** |
| **Post create containing a URL** | **$0.200** |
| Post create "summoned" (reply when mentioned) | $0.010 |
| DM create | $0.015 |
| User interaction create | $0.015 |
| Interaction delete | $0.010 |
| Media metadata | $0.005 |
| Counts recent | $0.005 |
| Counts all | $0.010 |
| Trends | $0.010 |

- **Caps:** "Pay-per-usage plans are capped at 3 million Post reads per monthly billing cycle." Anything higher needs Enterprise. Resources are deduplicated within a 24-hour UTC day, so re-reading the same post that day is free.
- **Bonuses:** xAI/Grok credit back of 10% for $200–499 spend, 15% for $500–999, 20% for $1,000+. **New Oct 2, 2026:** a one-time $20 for adding a card, plus a match of the first auto-recharge up to $50. These credits expire after 3 months.
- **Legacy tiers:**
  - Free, Basic ($200/mo historically) and Pro ($5,000/mo historically) are no longer sold to new developers.
  - Legacy **Basic** subscribers were auto-migrated to PPU after **June 1, 2026**, and legacy **Pro** after **September 1, 2026**. Both moved at the end of their billing cycle, with a $200 or $5,000 initial credit purchase respectively. Source: official X Developers forum announcements.
  - I could not confirm whether a legacy Free tier still exists. The pricing page mentions only PPU and Enterprise. UNVERIFIED - check docs.
- **Enterprise:** custom pricing and custom rate limits. Exempt from the reply restrictions. Required for quote-posting and for more than 3M post reads per month.

### Publishing capabilities (`POST /2/tweets`)
| Capability | Supported? | Details |
|---|---|---|
| Text | Yes | `text` |
| Image(s) | Yes | `media.media_ids` 1 to 4. `tagged_user_ids` up to 10. JPG/PNG/GIF/WEBP 5 MB, animated GIF 15 MB |
| Multi-image | Yes | Up to 4 images |
| Video | Yes | Chunked upload with dedicated endpoints (`/2/media/upload/initialize`, append, finalize, status). 8 GB and 20 minutes default; 16 GB and 125 minutes for Premium. One-shot `POST /2/media/upload` only for images and subtitles |
| Document/PDF | No | |
| Polls | Yes | `poll.options` 2 to 4 (1 to 25 characters each). `duration_minutes` 5 to 10,080 |
| Link preview | Yes (card auto-unfurls) | But **a post containing a URL costs $0.20** instead of $0.015 |
| Quote posts | **Enterprise only** | "Quote-posting requires an Enterprise plan." Removed from self-serve (Apr 2026 changelog) |
| Replies | Restricted | Since **Feb 23, 2026**, self-serve may reply only when "summoned", meaning the original author @mentioned you or quoted your post. Extra restrictions also apply to programmatic @mentions |
| Threads | Yes, via self-reply chains | Chain `reply.in_reply_to_tweet_id` to your own post IDs. Self-replies reportedly exempt from the summoned rule **(secondary source: opentweet.io)**. The official changelog does not state this. UNVERIFIED - check docs |
| Reply settings | Yes | `reply_settings`: following, mentionedUsers, subscribers, verified |
| Other fields | Yes | made_with_ai, paid_partnership (new Jun 2026), nullcast, community_id, share_with_followers, for_super_followers_only, geo.place_id, card_uri, edit_options (Premium, within 1 hour) |
| Scheduling via API | **No** | Schedule yourself. (The old v1.1 scheduled-tweets feature was Ads-API-only. UNVERIFIED - check docs) |
| Delete | Yes | `DELETE /2/tweets/:id` ($0.010 per "Interaction: Delete" request) |
| Likes / follows via API | **Removed from all self-serve tiers** | Apr 2026. Removed from Free in Aug 2025 |
| Articles | Yes (new Jun 11, 2026) | Draft and publish endpoints |

- **v1.1 media upload:** deprecated and sunset **June 9, 2025** (extended from April 30, 2025), per the official forum announcement. Use the v2 media endpoints. The old `command=INIT/APPEND/FINALIZE` parameter on `/2/media/upload` was replaced by the dedicated endpoints (Apr 30, 2025).

### Analytics capabilities
- **public_metrics:** retweet_count, quote_count, like_count, reply_count, impression_count, bookmark_count. Any auth, including a Bearer token, for any public post.
- **non_public_metrics:** impression_count, url_link_clicks, user_profile_clicks, engagements. Needs user-context OAuth and **posts the user owns**.
- **organic_metrics** and **promoted_metrics** need the same user context and owned posts.
- Media: view_count and playback_0/25/50/75/100_count quartiles.
- **Non-public, organic and promoted metrics are available only for posts created in the last 30 days.** Store snapshots before day 30.
- Granularity is cumulative point-in-time only (no daily series). Per post only. Account-level insight: followers_count from users lookup (`public_metrics` of the user). No account-level impressions endpoint. UNVERIFIED - check docs.
- Real-time events: X Activity API (open beta Oct 2025) provides post.create/delete, profile updates, DMs, mute/block and more.

### Competitor/public data access
- Allowed through the API, as public data, billed per resource:
  - user lookup by username ($0.010 per user)
  - user timelines `GET /2/users/:id/tweets` ($0.005 per post). The 3,200 most-recent cap is UNVERIFIED - check docs.
  - public_metrics of any public post
  - recent search over the last 7 days ("Available to all developers", 100 per request, 512-character query)
  - **full-archive search** back to 2006 ("Available to pay-per-use and Enterprise customers", 500 per request, 1,024-character query)
- Counts endpoints: recent $0.005 and all $0.010 per request.
- Search-index migration (May 2026) added `min_likes:`, `min_replies:` and `min_reposts:` operators. These had been listed as deprecated in Jan 2026; the May entry re-adds them.
- Overall cap: 3M post reads per month on PPU.

### Rate limits (standard self-serve; Enterprise is custom)
| Endpoint | Per app | Per user |
|---|---|---|
| POST /2/tweets | 10,000/24h | 100/15min |
| DELETE /2/tweets/:id | — | 50/15min |
| GET /2/tweets (lookup) | 3,500/15min | 5,000/15min |
| GET /2/tweets/search/recent | 450/15min | 300/15min |
| GET /2/tweets/search/all | 1/sec and 300/15min | 1/sec |
| GET /2/users/:id/tweets | 10,000/15min | 900/15min |
| GET /2/users/by/username/:u | 300/15min | 900/15min |
| GET /2/users/me | — | 75/15min |
| POST /2/media/upload | 50,000/24h | 500/15min |

### Automation rules / policy
- The official page (help.x.com/en/rules-and-policies/x-automation) returned 403 to my fetcher. These points come from search snippets of that page:
  - X does not allow identical or substantially similar content posted to multiple accounts, or multiple duplicate updates on one account.
  - Automated replies and mentions must honor user expectations and get permission when unsure.
  - Non-API automation (scripting the website) can lead to suspension.
- The Feb 2026 "summoned" reply rule and the Apr 2026 removal of likes, follows and quotes on self-serve enforce this at API level. Read the Developer Agreement and Policy in full before launch. UNVERIFIED - check docs for current wording.

### Known limitations and gotchas
- The **$0.20 per post with a URL** makes link-heavy scheduling 13 times more expensive.
- There is no quote-posting, liking or following on self-serve, and replies to others only work when summoned.
- Owner-only metrics disappear after 30 days.
- Access tokens last 2 hours, so refresh aggressively with offline.access.
- Media upload and posting limits are "separately enforced". An upload can succeed and still be rejected at post time (403 if the video exceeds the user's duration cap).
- Credits run out and requests then block, so build balance and spend monitoring.

### Notable changes 2025-2026
- Jan 2025: v2 media upload launched. Jun 9, 2025: v1.1 media upload sunset.
- Aug 2025: likes and follows removed from Free.
- Oct 2025: X Activity API beta and post editing.
- Nov 2025: Python and TypeScript XDKs and news endpoints.
- Feb 6, 2026: PPU launch.
- Feb 23, 2026: summoned-only replies.
- Apr 20, 2026: Owned Reads at $0.001, URL posts at $0.20, and quotes, likes and follows removed from self-serve.
- Jun 1, 2026 and Sep 1, 2026: legacy Basic and Pro migrated.
- Sep 2026: new media limits and OAuth1-to-OAuth2 token exchange.
- Oct 2, 2026: free-credit incentives.

### Source URLs
- https://docs.x.com/x-api/getting-started/pricing
- https://docs.x.com/changelog
- https://docs.x.com/x-api/fundamentals/rate-limits
- https://docs.x.com/x-api/fundamentals/metrics
- https://docs.x.com/x-api/posts/create-post
- https://docs.x.com/x-api/posts/search/introduction
- https://docs.x.com/x-api/media/introduction
- https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/authorization-code
- https://devcommunity.x.com/t/important-update-legacy-x-api-basic-plans-are-moving-to-pay-per-use-ppu/266305 (official forum)
- https://devcommunity.x.com/t/important-update-legacy-x-api-pro-plans-are-moving-to-pay-per-use-ppu/273255 (official forum)
- https://devcommunity.x.com/t/media-upload-endpoints-update-and-extended-migration-deadline/241818 (official forum)
- https://help.x.com/en/rules-and-policies/x-automation (403 to my fetcher; content from search snippets)
- (secondary) https://opentweet.io/how-to/fix-x-api-reply-restriction (self-reply exemption)

---

## 3. Pinterest API v5

### OAuth & tokens
- OAuth 2.0 with three grants: Authorization Code (user data), Client Credentials (the app acting for itself) and Refresh Token.
- **Access token:** 30 days (2,592,000 s).
- **Refresh token: continuous, 60-day expiry, "refreshable indefinitely."** "Pinterest only supports the continuous refresh token (60-day expiration, refreshable indefinitely) and no longer supports the legacy refresh token (365-day expiration, hard limit)." So your assumption of 365 days is **outdated**: refresh at least every 60 days and the token can live forever.

### Account types
- `account_type` is PINNER (personal) or BUSINESS.
- Pinterest docs say some analytics, including audience insights, are only available for business accounts and recommend converting. Source: developers.pinterest.com organic-reporting and FAQ pages via search snippet, because those pages are JS-rendered.
- Business Access lets an agency act on another user's account by passing `ad_account_id`, if the token user has a role on that ad account: Owner, Admin, Analyst or Campaign Manager. Analytics need Admin or Analyst.
- Creating an ad account requires a business account.

### Scopes
- `{entity}:read` and `{entity}:write` for: ads, boards, pins, catalogs, user_accounts, billing, biz_access.
- Create a pin: boards:read, boards:write, pins:read, pins:write.
- Account analytics: user_accounts:read. Pin analytics: boards:read and pins:read.
- Media register: pins:read and pins:write.

### App review & verification requirements
- **Trial access** comes on app approval. It needs a compliant, publicly reachable privacy policy on your domain and a clear app description. Limit: **1,000 requests per day per app** across all calls (300 for write categories). **"All Pins and Boards created with Trial access are only visible to their creator as Sandbox entities."** You cannot publish publicly on Trial.
- **Standard access** is an upgrade request from My Apps. It requires:
  - Trial approval
  - compliance with the Developer Guidelines
  - a **video recording of your app's OAuth flow** completing an action, so Pinterest can check OAuth use and that no sensitive data is stored. Required even for single-user apps; terminal or Postman recordings are accepted.
- No published SLA ("allow a few days"). There is no "Advanced" tier.
- Some endpoints are beta or restricted and "not available to all apps": multi-pin analytics, update pin (PATCH), follow user, partner pin search.

### Publishing capabilities (`POST /v5/pins`)
| Capability | Supported? | Details |
|---|---|---|
| Text-only | No | A pin needs media. Fields: title ≤100, description ≤800, link ≤2048, alt_text ≤500 characters, board_id or board_section_id |
| Single image | Yes | `media_source.source_type`: `image_url` or `image_base64` |
| Carousel (multi-image) | Yes | `multiple_image_urls` or `multiple_image_base64`, **2 to 5 images**, each with its own title, description and link |
| Video | Yes | `POST /v5/media` (register) → upload to `upload_url` with `upload_parameters` → poll `GET /v5/media/{id}` → create the pin with `source_type: video_id`, `media_id` and a cover image (URL, base64 or key-frame time). Video size and duration specs: UNVERIFIED - check docs |
| Document/PDF | No | |
| Polls | No | |
| Link | Yes | Destination `link`. Product pins via `pin_url` are beta-only |
| AI disclosure | Yes | `ai_disclosures` field |
| Scheduling via API | **No** | No publish-date field in the PinCreate schema (spec v5.28.0) |
| Edit | Beta only | `PATCH /pins/{id}` is "not available to all apps" |
| Delete | Yes | `DELETE /pins/{pin_id}` |
| Boards | Yes | Create, update, delete and list boards and sections |
| Policy | — | The API is "intended solely for publishing new content created by the user". Use the Save button for curated content |

### Analytics capabilities
- `GET /user_account/analytics` (account level):
  - Metrics: IMPRESSION, ENGAGEMENT, ENGAGEMENT_RATE, OUTBOUND_CLICK and OUTBOUND_CLICK_RATE, PIN_CLICK and PIN_CLICK_RATE, SAVE and SAVE_RATE.
  - Filters: claimed vs other content, pin format (organic image, product or video vs ads), app type, paid vs organic, source (your pins vs other pins).
  - Splits: APP_TYPE, OWNED_CONTENT, SOURCE, PIN_FORMAT.
  - Results come back as daily data. The daily series is UNVERIFIED - check docs; the response shape was not inspected.
- `GET /user_account/analytics/top_pins` and `/top_video_pins`: top 50, optionally only pins created in the last 30 days.
- `GET /pins/{pin_id}/analytics` (per pin):
  - Standard metrics: IMPRESSION, OUTBOUND_CLICK, PIN_CLICK, SAVE, SAVE_RATE, TOTAL_COMMENTS, TOTAL_REACTIONS, USER_FOLLOW, PROFILE_VISIT.
  - Video metrics: VIDEO_MRC_VIEW, VIDEO_10S_VIEW, QUARTILE_95_PERCENT_VIEW, VIDEO_V50_WATCH_TIME, VIDEO_START, VIDEO_AVG_WATCH_TIME.
  - Split by APP_TYPE.
- `GET /pins/analytics`: up to 100 pins per call. Beta.
- `GET /pins/{id}?pin_metrics=true` returns 90-day and lifetime metrics.
- **Lookback: start_date can be at most 90 days back, and the range at most 90 days.** Store history yourself.
- Pins created before 2023-03-20 have limited lifetime metrics.
- The `Account` object exposes follower_count, following_count, monthly_views, pin_count and board_count.
- Followers list: `GET /user_account/followers`.

### Competitor/public data access
- **Very limited.** Boards and pins endpoints work only for the operation user's own content, group boards shared with them, or accounts reached through Business Access. There is **no public user lookup or public pin search** of other accounts in v5. Partner pin search (top 10 pins for a term) is beta-only.
- Market-level data: the **Trends API** (`/trends/keywords/{region}/top/{trend_type}`, featured topics, trending product categories) with user_accounts:read.

### Rate limits & quotas & pricing
- **Trial:** 1,000 requests per day per app (all), and 300 per day for ads_write and org_write.
- **Standard:** "100 requests per second per user per app" overall, plus per-category per-minute per-user per-app limits:

| Category | Per minute |
|---|---|
| org_read | 1,000 |
| org_write | 100 |
| org_analytics | 60 |
| ads_read | 1,000 |
| ads_write | 400 |
| ads_analytics | 300 |
| catalogs_read / catalogs_write | 100 each |
| trends_read | 60 |

- Headers: `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-reset`.
- No API fees.

### Known limitations and gotchas
- On Trial, everything you create is a sandbox entity visible only to the creator, so a real launch needs Standard access first.
- Analytics only reach back 90 days.
- Refresh tokens expire after 60 days without use.
- Pin editing is beta.
- There is no scheduling, and Pinterest's native scheduler is not exposed. Native scheduler not exposed: UNVERIFIED - check docs.
- No text-only or poll pins.

### Notable changes 2025-2026
- Legacy 365-day refresh tokens dropped; continuous 60-day only.
- AI disclosure field on pins.
- Simplified pin (`is_standard=false`) in beta.
- Current spec version 5.28.0.
- Exact dates of these changes: UNVERIFIED - check docs.

### Source URLs
- https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/
- https://developers.pinterest.com/docs/key-concepts/access-tiers/
- https://developers.pinterest.com/docs/reference/rate-limits/
- https://raw.githubusercontent.com/pinterest/api-description/main/v5/openapi.json (official OpenAPI spec v5.28.0, used for endpoints, schemas and metric enums)
- https://developers.pinterest.com/docs/api-features/organic-reporting/ and /docs/faqs/faqs/ (JS-rendered; business-account statements via search snippet)

---

## 4. Google Business Profile (GBP) APIs

### OAuth & tokens
- Google OAuth 2.0 with the scope **`https://www.googleapis.com/auth/business.manage`**. The legacy `plus.business.manage` is also accepted on v4 methods.
- Standard Google tokens: the access token lasts about 1 hour. Refresh tokens do not expire on a fixed schedule but can be revoked. Apps in "Testing" OAuth consent status get 7-day refresh tokens. That whole description is UNVERIFIED in this session; check Google OAuth docs. Whether business.manage counts as a sensitive scope needing Google OAuth app verification is also UNVERIFIED - check docs.

### Account types
- Google accounts that are owner or manager of a verified Business Profile (location) or a location group / business account.
- Posts are made per location.

### App review & access request
- **Access is gated.** Prerequisites:
  - "Manage a Google Business Profile that is verified and active for 60+ days"
  - "Have a website representing the business listed on the GBP"
  - Use an email listed as owner or manager on the profile
- You submit the **GBP API contact form** with your **Google Cloud project number**.
- **Quota is 0 QPM until approved.** "If your quota is set to 300 QPM, your project is approved."
- The review timeline is not published ("A follow-up email will be sent to you after your request has been reviewed").
- APIs used:
  - My Business v4 (`mybusiness.googleapis.com/v4`) for localPosts, media and reviews
  - Account Management, Business Information, Performance (`businessprofileperformance.googleapis.com`), Verifications, Notifications, Lodging and Place Actions APIs

### Publishing capabilities (v4 `accounts/{a}/locations/{l}/localPosts`)
| Capability | Supported? | Details |
|---|---|---|
| Text (STANDARD post) | Yes | `topicType: STANDARD`, `summary`. Max summary length not stated on the reference page (UNVERIFIED - check docs) |
| Event post | Yes | `EVENT` with `event.title` and `event.schedule` |
| Offer post | Yes | `OFFER` with event and `offer.couponCode`, `redeemOnlineUrl`, `termsConditions` |
| Alert post | Limited | `ALERT`. Only COVID_19 alertType exists, and "not always available for authoring" |
| Product post | **No** | "Product Posts cannot be created using the Google My Business API" |
| Image / video in post | Yes, by URL only | `media[]` where "sourceUrl is the only supported data field for a LocalPost MediaItem". Byte upload is not allowed for post media. Max media count per post: UNVERIFIED - check docs |
| Call to action | Yes | BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, CALL (GET_OFFER deprecated) |
| Multi-image | UNVERIFIED - check docs | `media[]` is an array, but the limit is not documented on the page |
| Document/PDF, polls | No | |
| **Scheduling via API** | **Yes** | `scheduledTime`: "If set, determines when a post will be published. This can be set by the user to schedule posts in advance." The SCHEDULED state exists |
| **Recurring posts** | **Yes (new 2026-04-07)** | `event.recurrenceInfo` with daily, weekly or monthly pattern and `seriesEndTime`. RECURRING state |
| Edit / delete | Yes | PATCH and DELETE on localPosts. Also get and list |
| Post moderation state | Yes | LIVE, PROCESSING, SCHEDULED, RECURRING, REJECTED (content policy) |
| Location photos/videos | Yes | `accounts.locations.media` create with `sourceUrl`, or startUpload → upload bytes → create with `dataRef`. Categories such as COVER and ADDITIONAL |
| Reviews | Yes | list, get, batchGetReviews, updateReply, deleteReply. New 2026 fields: ReviewReplyState, ReviewMediaItems, PolicyViolation, reviewReplyUrl |

### Analytics capabilities
- **Performance API v1:**
  - `locations.getDailyMetricsTimeSeries` and `locations.fetchMultiDailyMetricsTimeSeries` return **daily** values per location.
  - DailyMetric values: BUSINESS_IMPRESSIONS_DESKTOP_MAPS, BUSINESS_IMPRESSIONS_DESKTOP_SEARCH, BUSINESS_IMPRESSIONS_MOBILE_MAPS, BUSINESS_IMPRESSIONS_MOBILE_SEARCH (unique users per day), BUSINESS_DIRECTION_REQUESTS, CALL_CLICKS, WEBSITE_CLICKS, BUSINESS_BOOKINGS, BUSINESS_FOOD_MENU_CLICKS.
  - Deprecated: BUSINESS_CONVERSATIONS and BUSINESS_FOOD_ORDERS.
- **Search keywords:** `locations/{id}/searchkeywords/impressions/monthly` returns monthly keyword impression counts or thresholds, up to 100 per page.
- **Per-post insights: NOT available.** `accounts.locations.localPosts.reportInsights` was discontinued on 2023-02-20 with no replacement. LOCAL_POST_VIEWS_SEARCH, LOCAL_POST_ACTIONS_CALL_TO_ACTION, photo view metrics and MediaInsights were discontinued too. Per-post reporting is impossible, so you only get location-level metrics.
- Historical lookback is about **18 months**, with a data delay of about 2–3 days. **(secondary source: docs.zernio.com.)** UNVERIFIED in official docs.

### Competitor/public data access
- GBP APIs only work on locations the user manages. `googleLocations.search` exists to match or claim locations, but it is not intended for analytics.
- Competitor public data (ratings, review counts, a few reviews) would require the separate paid **Google Places API**, which has its own terms and pricing. UNVERIFIED - check docs.
- The Q&A API, which gave public questions, was **discontinued Nov 3, 2025**.

### Rate limits & quotas & pricing
- **300 QPM per project** for each API: Account Management, Business Information, Performance, Verifications, Lodging, Place Actions and Notifications.
- Business Information also has these limits:

| Business Information request | Limit |
|---|---|
| Create Location | 300 per day |
| SearchGoogleLocation | 300 per day |
| Update Location | 10,000 per day |
| **Edits per Business Profile** | **10 per minute ("cannot be increased")** |

- Quota increases go through a form. They are denied for spiky or under-utilized usage (needs over 50% average use).
- Over-quota calls return 429. Use exponential backoff.
- No API fees. v4 posts and media quotas: UNVERIFIED - check docs (probably the 300 QPM default).

### Known limitations and gotchas
- Access approval is a hard gate: quota stays at 0 until approved, and the business must be verified for 60+ days and have a website.
- Post media must be a publicly fetchable URL.
- No per-post analytics. No product posts. Alert posts are effectively unavailable.
- Posts can be REJECTED by moderation, so poll the state.
- The v4 API is legacy-named (`mybusiness.googleapis.com/v4`), but it remains the home for posts, media and reviews.

### Notable changes 2025-2026
- Q&A API support ended 2025-09-15 and it was discontinued 2025-11-03.
- 2026-04-01: ReviewReplyState.
- **2026-04-07: recurring posts** through RecurrenceInfo.
- 2026-04-20: review media items.
- 2026-05-12: place ID in invitations.
- 2026-07-01: PolicyViolation on reviews.
- 2026-07-24: reviewReplyUrl.

### Source URLs
- https://developers.google.com/my-business/content/prereqs
- https://developers.google.com/my-business/content/limits
- https://developers.google.com/my-business/content/posts-data
- https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts
- https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts/reportInsights
- https://developers.google.com/my-business/content/upload-photos
- https://developers.google.com/my-business/reference/performance/rest/v1/DailyMetric
- https://developers.google.com/my-business/reference/performance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries
- https://developers.google.com/my-business/reference/performance/rest/v1/locations.searchkeywords.impressions.monthly/list
- https://developers.google.com/my-business/content/sunset-dates
- https://developers.google.com/my-business/content/latest-updates
- (secondary) https://docs.zernio.com/platforms/google-business/analytics (18-month lookback)

---

## Cross-platform summary for product design
| | LinkedIn | X | Pinterest | GBP |
|---|---|---|---|---|
| Native API scheduling | No | No | No | **Yes** (`scheduledTime`, recurring) |
| Approval gate | Community Mgmt: Dev then Standard tier with screencast. Legal entity only | None (pay-per-use credits) | Trial (sandbox-only pins) then Standard with OAuth video | Access form. 0 QPM until approved. GBP 60+ days old |
| Access token / refresh | 60 days / 365 days fixed (approved apps only) | 2 hours / refresh with offline.access | 30 days / 60-day continuous | ~1 hour / Google refresh (UNVERIFIED) |
| Per-post analytics | Org: lifetime per post. Member: yes (r_member_postAnalytics) | Yes; owner-private metrics only for 30 days | Yes, 90-day window | **No** (discontinued 2023) |
| Competitor data | Follower count of any org (networkSizes) plus basic org info only | Public posts, users, search (paid per resource, 3M post-read cap per month) | Essentially none (Trends API only) | None (Places API is separate) |
| Cost | Free | $0.015/post, **$0.20/post with URL**, $0.005/post read | Free | Free |
