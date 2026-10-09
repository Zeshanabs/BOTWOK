# 12 — Scheduling Architecture

## 12.1 Flow

```
ScheduledPost (intent, UTC instant + tz)
   │  scheduler (leader) every 5 s: due rows → queued  (+ enqueue job in same txn)
   ▼
Queue (procrastinate, queue=publishing, lock=publish:{id})
   ▼
Worker (publishing)  → PublishingService → Platform Adapter → Publish → Result
   ▼
Database (publish_attempts, published_posts, scheduled_posts.status)
   ▼
Notification (in-app + email/Slack per preference) + SSE event
```

Decision: **Botwok owns scheduling for every platform.** Native platform scheduling (Facebook, YouTube `publishAt`, GBP `scheduledTime`) is exposed as an optional per-post toggle ("hand off to platform") in V2, not the default, because our own scheduler gives uniform behavior: editable until publish time, consistent retries, one calendar truth, and no dependence on platform-side limits (e.g. Facebook 30-day max).

## 12.2 Tables
`scheduled_posts`: `id, workspace_id, brand_id, content_variant_id, social_account_id, scheduled_at timestamptz (UTC), timezone text, status schedule_status_t, priority int default 0, queued_at, publishing_started_at, published_at, attempt_count int default 0, max_attempts int default 5, next_attempt_at timestamptz, last_error text, idempotency_root uuid default gen_random_uuid(), recurring_schedule_id?, approval_id?, native_schedule bool default false, created_by, updated_at`.
Indexes: `(status, scheduled_at)` for the due scan; `(status, next_attempt_at)`; `(brand_id, scheduled_at)`; partial unique `(content_variant_id, social_account_id) WHERE status IN ('scheduled','queued','publishing')`.

`recurring_schedules`: `id, workspace_id, brand_id, name, rrule text (RFC 5545), timezone, kind (repost_variant|automation|slot_template), payload jsonb, next_run_at, last_materialized_until, status (active|paused), created_by`. The scheduler materializes concrete `scheduled_posts` (or automation triggers) 14 days ahead; editing the rule re-materializes future rows not yet queued.

## 12.3 Scheduler loop (leader only)
```python
async def scheduler_loop():
    async with advisory_lock("botwok:scheduler") as held:
        if not held: return                           # standby replica
        while True:
            await dispatch_due_posts()                # below
            await dispatch_retries()                  # status='queued' AND next_attempt_at<=now() AND no pending job → enqueue
            await materialize_recurring()             # recurring_schedules → scheduled_posts / automation triggers
            await dispatch_analytics_cadence()        # per-account sync jobs by cadence table
            await dispatch_automation_cron()          # workflow cron triggers
            await expire_approvals(); await expire_leases()
            await asyncio.sleep(5)

async def dispatch_due_posts():
    async with uow() as db:
        rows = await db.execute("""
          UPDATE scheduled_posts SET status='queued', queued_at=now()
          WHERE id IN (SELECT id FROM scheduled_posts
                       WHERE status='scheduled' AND scheduled_at <= now()
                       ORDER BY priority DESC, scheduled_at
                       FOR UPDATE SKIP LOCKED LIMIT 50)
          RETURNING id, attempt_count""")
        for r in rows:
            await jobs.publishing.publish_post.defer_async(scheduled_post_id=r.id, attempt_no=r.attempt_count+1,
                                                           queueing_lock=f"publish:{r.id}")   # same transaction
```
If the transaction fails after `UPDATE` nothing is enqueued and the status change is rolled back; if it succeeds both are durable. Retries use the same path with `next_attempt_at`.

## 12.4 Operations on a scheduled post

| Operation | Allowed in status | Effect |
|---|---|---|
| Edit time (drag on calendar) | `scheduled` | update `scheduled_at`; `POST_RESCHEDULED` |
| Edit time | `queued` (retry wait) | cancel pending job via lock, set `scheduled`, update time |
| Edit content | `scheduled` | new variant version; re-run `validate_content`; keep schedule |
| Pause | `scheduled` | `status=paused` (never dispatched); resume → `scheduled` (if time passed, prompt for new time) |
| Cancel | `scheduled`, `queued`, `paused`, `failed` | `status=cancelled`; pending job cancelled; `POST_CANCELLED` |
| Retry (manual) | `failed` | `attempt_count` kept, `status=queued`, immediate dispatch |
| Publish now | `scheduled`/`paused`/approved variant | sets `scheduled_at=now()`, priority 10 |
| Anything | `publishing` | refused (409) — wait for terminal state |

## 12.5 Timezones & DST
`scheduled_at` is stored in UTC; the `timezone` column (IANA) is used for display, recurrence expansion (rrule evaluated in that zone), and best-time slots. Wall-clock times that don't exist during a DST gap are shifted forward; ambiguous times resolve to the first occurrence. The brand's default timezone seeds the picker.

## 12.6 Best-time scheduling
`POST /scheduling/best-times {brand_id, platform, social_account_id, date_range, count}`:
1. From `post_metrics` + `published_posts` over the last 90 days: engagement rate by (weekday, hour) in the account's timezone; require n ≥ 3 per cell, else blend with platform priors (seeded table, labeled "generic").
2. Optional audience-online signal where the platform exposes it (Instagram `online_followers` — UNVERIFIED availability; LinkedIn follower stats do not provide hour-level data).
3. Exclude slots already occupied on the same account (min gap: IG 2 h, LinkedIn 4 h, X 30 min, TikTok 4 h, YouTube 24 h, defaults configurable) and slots beyond token expiry.
4. Return top-N slots with scores and the evidence basis ("based on 37 posts" vs "generic prior").

## 12.7 Failure semantics (summary; full matrix in doc 28)
- Retries: 1 m, 5 m, 15 m, 30 m, 60 m (jittered), `max_attempts=5`; rate-limit waits respect `Retry-After`.
- Dead letter: `status=failed` + `PUBLISH_DEAD_LETTERED`; the Publishing screen's "Failed" section lists reason, attempts, and offers Retry / Edit / Cancel.
- Stale `publishing` (worker crash): `expire_leases()` resets rows in `publishing` for > 15 min with no attempt heartbeat to `queued` **after** a reconciliation attempt (never a blind retry).
- Scheduler downtime: on restart, all overdue `scheduled` rows dispatch immediately; posts older than `late_tolerance` (default 6 h) are **held** with status `paused` and a notification ("missed window — publish now or reschedule?") instead of publishing stale content silently.

## 12.8 Calendar aggregation
`GET /calendar?from&to&view&filters` returns cards built from `scheduled_posts ⋈ content_variants ⋈ content_items ⋈ social_accounts` plus unscheduled items in the range's "tray" (approved but unscheduled). Status color per doc 00; drag-and-drop issues `PATCH /scheduling/posts/{id} {scheduled_at}` with optimistic UI and rollback on 409.
