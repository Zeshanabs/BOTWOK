# 11 — Publishing Architecture

## 11.1 Adapter architecture

```
PublishingService
├── AdapterRegistry  platform → SocialAdapter (configured per social_account)
├── MetaGraphClient  shared HTTP client for FacebookAdapter · InstagramAdapter · ThreadsAdapter
├── FacebookAdapter
├── InstagramAdapter          (two auth flavors: FacebookLogin | InstagramLogin; same publish flow)
├── ThreadsAdapter
├── LinkedInAdapter           (member | organization author URNs)
├── XAdapter
├── TikTokAdapter             (direct_post | inbox_upload modes)
├── YouTubeAdapter
├── PinterestAdapter
└── GBPAdapter
```

### 11.1.1 The `SocialAdapter` protocol
```python
class SocialAdapter(Protocol):
    platform: Platform
    def capabilities(self, account: SocialAccount) -> Capabilities           # formats, limits, native_schedule, delete, metrics, alt_text…
    def auth_url(self, state: str, redirect_uri: str, scopes: list[str]) -> str
    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str|None) -> TokenSet
    async def refresh(self, tokens: TokenSet) -> TokenSet
    async def list_connectable_accounts(self, tokens: TokenSet) -> list[ConnectableAccount]   # pages, IG accounts, orgs, channels
    async def probe(self, account) -> AccountHealth                                            # token valid? scopes? limits?
    async def validate_content(self, account, variant: ContentVariant, assets: list[MediaAsset]) -> ValidationResult
    async def publish(self, account, req: PublishRequest, attempt: PublishAttempt) -> PublishResult   # resumable via attempt.state
    async def schedule(self, account, req, attempt) -> PublishResult      # only if capabilities.native_schedule; V1 unused
    async def get_post(self, account, external_id: str) -> RemotePost
    async def delete_post(self, account, external_id: str) -> None
    async def get_status(self, account, attempt) -> PublishStatus         # for async flows (IG containers, TikTok publish_id, video processing)
    async def get_post_metrics(self, account, external_id: str, since: datetime|None) -> NormalizedPostMetrics
    async def get_account_metrics(self, account, period: DateRange) -> NormalizedAccountMetrics
    async def find_recent_posts(self, account, since: datetime) -> list[RemotePost]   # reconciliation; may return [] if platform cannot list own posts (LinkedIn member)
    def rate_limits(self) -> list[RateLimitSpec]
    def map_error(self, exc) -> PublishError                              # → category: transient|rate_limited|auth|validation|permanent|ambiguous
```
`PublishRequest` = normalized content (text/segments, media renditions with public URLs or bytes, metadata) + `PublishAttempt.state` (JSONB) holding intermediate ids (`creation_id`, `media_ids`, `upload_url`, `publish_id`, `segment_external_ids[]`) so a retry **resumes** instead of restarting.

### 11.1.2 How each adapter talks to its platform (verified against current docs; details in doc 27)

| Adapter | Publish mechanics | Media | Scheduling | Delete | Own-post listing (for reconciliation) |
|---|---|---|---|---|---|
| Facebook | `POST /{page-id}/feed` (text/link), `/photos` (single or multi via unpublished photos + `attached_media` — UNVERIFIED param name), `/videos`, `/video_reels` (init→upload→finish), Stories via `/photo_stories`/`/video_stories` | upload by URL or bytes | native `scheduled_publish_time` (10 min–30 d; Reels ≤ 29 d; Stories no) — not used by default | yes | `GET /{page-id}/feed` (~600 posts/yr cap) |
| Instagram | container flow: `POST /{ig-id}/media` (image_url / video_url+media_type=REELS / STORIES / carousel children + `children=`) → poll `status_code` → `POST /{ig-id}/media_publish` | **public URL required** (JPEG only for images) | none (Botwok scheduler) | yes (since Dec 2025) | `GET /{ig-id}/media` |
| Threads | `POST /{threads-user-id}/threads` (TEXT / IMAGE / VIDEO / CAROUSEL with children) → wait ≥30 s for media → `POST /{id}/threads_publish` | public URL required | none | yes | `GET /{id}/threads` |
| LinkedIn | `POST /rest/posts` with `author=urn:li:person|organization`, `LinkedIn-Version: YYYYMM`; images/videos/documents via `initializeUpload` → binary PUT → reference URN; multi-image 2–20; poll; article (title/description/thumbnail supplied) | bytes upload | none (`lifecycleState=PUBLISHED` only) | yes | org: `GET /rest/posts?author=…`; **member: not possible** → rely on stored ids |
| X | `POST /2/tweets` {text, media.media_ids, poll, reply.in_reply_to_tweet_id}; threads = sequential replies to own posts; media via `POST /2/media/upload` chunked INIT/APPEND/FINALIZE (+STATUS) | bytes | none | yes | `GET /2/users/:id/tweets` (metered) |
| TikTok | **direct_post:** `GET creator_info/query` → `POST post/publish/video/init` (FILE_UPLOAD chunks or PULL_FROM_URL verified domain) → upload → `POST post/publish/status/fetch`; **inbox_upload:** `POST post/publish/inbox/video/init` (user finalizes in app); photos: `post/publish/content/init` (PULL_FROM_URL only) | bytes (video) / public URL (photos) | none | **no API delete** | `POST /v2/video/list/` (own videos) |
| YouTube | resumable `videos.insert` (snippet, status{privacyStatus, publishAt, madeForKids}), `thumbnails.set` (verified channel), `captions.insert` | bytes | native `publishAt` (requires `private`) — used when the user wants native scheduling; otherwise Botwok uploads at publish time | yes | `search.list(forMine)`/`playlistItems` (uploads playlist) |
| Pinterest | `POST /v5/pins` (image URL/base64, carousel 2–5, video via `/v5/media` upload then pin) | URL/base64/upload | none | yes | `GET /v5/pins` |
| GBP | `localPosts.create` (STANDARD/EVENT/OFFER, CTA, media by public URL) | public URL | native `scheduledTime` (recurring supported) | yes | `localPosts.list` |

**Public URL requirement (local-first consequence):** Instagram, Threads, TikTok photos, Pinterest (URL mode), and GBP fetch media from a URL. Locally, MinIO is not reachable from the internet, so `MediaPublicURLService` serves renditions through a public base URL: on a VPS a public bucket/CDN with short-TTL signed URLs; locally an outbound tunnel (`cloudflared tunnel` or `ngrok`) configured by `PUBLIC_MEDIA_BASE_URL`. Without it, those platforms show "needs public media URL" at validation time, and platforms that accept bytes (X, LinkedIn, YouTube, TikTok video, Facebook) still work. (TikTok PULL_FROM_URL additionally requires a **verified domain**.)

## 11.2 Ledger tables

- `scheduled_posts` (doc 12) is the intent.
- `publish_attempts`: `id, scheduled_post_id, attempt_no, idempotency_key (unique), status (running|succeeded|failed|ambiguous|reconciled), state jsonb, request_fingerprint (sha256 of normalized text+media hashes+account), started_at, finished_at, error_category, error_code, error_message, platform_response jsonb (redacted), worker_id`.
- `published_posts`: `id, scheduled_post_id, content_variant_id, social_account_id, platform, external_id, external_url, published_at, segments jsonb (thread ids), raw jsonb, deleted_at`.
Unique: `(social_account_id, external_id)`; partial unique `(scheduled_post_id) WHERE deleted_at IS NULL` (one live published row per scheduled post).

## 11.3 The publish worker (exactly-once in effect)

```python
@app.task(queue="publishing", retry=RetryStrategy(max_attempts=1), lock="publish:{scheduled_post_id}")
async def publish_post(scheduled_post_id: UUID, attempt_no: int):
    async with uow() as db:
        sp = await db.scheduled_posts.lock(scheduled_post_id)                     # SELECT … FOR UPDATE
        if sp.status != "queued" or sp.attempt_count != attempt_no - 1: return    # stale/duplicate job → no-op
        if await db.published_posts.exists(scheduled_post_id): sp.status="published"; return
        sp.status = "publishing"; sp.publishing_started_at = now(); sp.attempt_count = attempt_no
        attempt = await db.publish_attempts.create(sp, attempt_no, idempotency_key=f"{sp.idempotency_root}:{attempt_no}",
                                                   state=await db.publish_attempts.last_state(sp.id))   # resume intermediate ids
        emit(PUBLISH_STARTED)
    adapter = registry.for_account(sp.social_account)
    await rate_limiter.acquire(adapter.platform, sp.social_account_id)
    try:
        result = await adapter.publish(sp.social_account, build_request(sp), attempt)   # updates attempt.state as it goes
    except PublishError as e:
        return await handle_failure(sp, attempt, e)
    async with uow() as db:
        await db.published_posts.create_from(result, sp)
        sp.status = "published"; sp.published_at = result.published_at; attempt.status = "succeeded"
        emit(PUBLISH_SUCCESS); notify(sp.created_by)
```

`handle_failure`:

| `error.category` | Action |
|---|---|
| `validation` / `permanent` (4xx policy, unsupported media, content rejected) | `status=failed`, `PUBLISH_FAILED`, notification with reason; no retry |
| `auth` (401 / Meta code 190 / expired) | try `adapter.refresh()` once → requeue immediately (attempt_no+1, no backoff); if refresh fails: `social_accounts.status=expired`, `status=failed`, `SOCIAL_ACCOUNT_REVOKED`/expiring notification |
| `rate_limited` (429 / Meta code 4, 17, 32, 613) | compute `next_attempt_at` from `Retry-After` or platform window; `status=queued`; `scheduled_posts.next_attempt_at` set; scheduler re-dispatches |
| `transient` (5xx, connect timeout, DNS) | backoff schedule 1m, 5m, 15m, 30m, 60m → `status=queued` with `next_attempt_at`; after `max_attempts` (5) → `failed`, `PUBLISH_DEAD_LETTERED` |
| `ambiguous` (timeout/reset **after** the request was sent; unknown platform state) | `attempt.status=ambiguous` → run `reconcile()` **before** any retry |

`reconcile(sp, attempt)`: `adapter.get_status(attempt)` if an intermediate id exists (IG container, TikTok `publish_id`, X media/post id) → else `adapter.find_recent_posts(since=attempt.started_at-5m)` and match on `request_fingerprint` (normalized text equality + media hash where returned + account + time window). Match → `published_posts` created, `attempt.status=reconciled`, `status=published`. No match and the platform can list own posts → safe retry. No match and the platform **cannot** list own posts (LinkedIn member) → `status=failed` with reason "ambiguous result; verify manually" and a notification with a deep link; never auto-retry blind in that case.

Multi-segment posts (X threads, Threads chains, IG carousels, TikTok photo sets): `attempt.state.segment_external_ids[]` records each successful segment; retry resumes at the first missing segment; a thread is marked `published` only when all segments exist, otherwise `partially_published` is surfaced in the UI with a "continue" action.

## 11.4 Duplicate-prevention layers (defense in depth)

1. **Unique intent**: partial unique index on `scheduled_posts (content_variant_id, social_account_id) WHERE status IN ('scheduled','queued','publishing')`.
2. **One job per post**: Procrastinate `queueing_lock='publish:{id}'`.
3. **State CAS**: worker proceeds only from `queued` with matching `attempt_count`.
4. **Resume, don't restart**: intermediate ids persisted per attempt.
5. **Reconcile before retry** on ambiguous outcomes.
6. **Published uniqueness**: `(social_account_id, external_id)` unique; one live `published_posts` per `scheduled_post`.
7. **Content fingerprint check**: before publishing, if a `published_posts` row for the same account with the same fingerprint exists within 24 h → block with "possible duplicate" (user can override).

## 11.5 Validation (`validate_content`)
Runs at scheduling time and again immediately before publish. Checks (per capability matrix): text length, segment count/length, hashtag count, link count/policy (X URL posts cost more and are flagged), mentions, media count/format/size/aspect/duration/codec, alt-text presence where supported, poll shape, privacy/consent fields (TikTok direct-post requires creator_info-derived privacy options chosen by the user; branded-content disclosure), account capability (TikTok unaudited → `inbox_upload` only; YouTube unaudited → forced private; Pinterest trial → private pins), rate-limit headroom (IG 100 posts/24 h, Threads 250/24 h, FB Reels 30/24 h, TikTok ~15 direct posts/day), token expiry (refuse to schedule beyond token expiry unless refreshable; prompt reconnect). Results are stored on `content_variants.validation` and shown in Studio.

## 11.6 Platform deletes and edits
`DELETE /publishing/published/{id}` → `adapter.delete_post` where supported (all except TikTok) → `published_posts.deleted_at`, audit log, `CONTENT_STATUS_CHANGED`. Edits after publishing are not supported via API on most platforms; the UI offers "delete and republish" with an explicit warning (metrics reset).

## 11.7 Inbound webhooks
`POST /api/v1/webhooks/{platform}` with signature verification (Meta `X-Hub-Signature-256`, others per platform) for: deauthorization callbacks (mark account revoked), data-deletion requests (Meta compliance), content status callbacks where offered. Local-first: webhooks are optional; polling covers status.
