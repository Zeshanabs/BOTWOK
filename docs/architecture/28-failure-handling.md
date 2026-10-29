# 28 — Failure Handling & Retry Policies

## 28.1 Shared machinery
- `ResilientClient` (httpx): connect timeout 5 s, read timeout 30 s (uploads 300 s), retries with exponential backoff + full jitter (base 1 s, cap 60 s), retry only on idempotent operations or when explicitly marked resumable; circuit breaker per host (open after 5 consecutive failures, half-open after 30 s); per-platform/account token-bucket rate limiters in Redis fed by `rate_limits()` specs and live `X-App-Usage`/`x-rate-limit-remaining` headers.
- Error taxonomy: `transient`, `rate_limited`, `auth`, `validation`, `permanent`, `ambiguous`, `unsupported`. Every adapter/provider maps native errors to this taxonomy (`map_error`), with the native code preserved.
- Jobs: Procrastinate retry strategies per task; every job is idempotent by payload key; stale `running` rows are leased and recovered by the scheduler.

## 28.2 Failure matrix

| Failure | Detection | Immediate behavior | Retry policy | User-facing | Recovery |
|---|---|---|---|---|---|
| **Expired OAuth token** | 401/`190` (Meta), `401` (others), probe | `TokenVault.refresh()` if the platform supports refresh for this app; else mark `social_accounts.status=expired` | one refresh attempt, then no retry | Social Accounts shows "Reconnect"; scheduled posts within expiry paused + notification | user reconnects; paused posts resume automatically if their time hasn't passed |
| **Revoked access** | deauth webhook, `190` subcode 458/460, `403` | `status=revoked`; cancel pending job; pause posts | none | urgent notification | reconnect |
| **API rate limit** | 429 / Meta codes 4, 17, 32, 613, 80001/2 / X 429 / YouTube `quotaExceeded` | compute wait from `Retry-After`, `estimated_time_to_regain_access`, or window reset; set `next_attempt_at`; local limiter tightens | until window resets, then normal | queue shows "rate limited until hh:mm" | automatic |
| **API downtime** | 5xx, connection errors | backoff retries; circuit breaker opens | 5 attempts over ~2 h (publishing); 3 attempts (reads) | status "retrying"; dead-letter notification on exhaustion | manual retry button; automatic when breaker closes |
| **Malformed media** | ffprobe/Pillow validation at ingest; platform 4xx at publish | reject at validation (preferred) | none | Studio shows the exact error (codec, size, aspect) with "Fix automatically" (re-encode/transform) | re-upload or auto-transform |
| **Unsupported media** | capability matrix check | block scheduling (`422 unsupported_format`) | none | inline guidance ("Instagram requires JPEG images") | transform or choose another format |
| **Duplicate post** | partial unique index; fingerprint check; platform "duplicate status" errors (X 403 duplicate) | refuse scheduling (409) or mark attempt `permanent` with reason | none | "Possible duplicate of post X" with override (editor) | edit text |
| **AI timeout / provider error** | provider exceptions, `finish_reason=length`, JSON parse failure | per-call retry 3× with backoff; fallback model; re-prompt on schema error (2×) | then task fails; dependents skipped | run step shows ✗ with reason; "Retry from this step" | retry; switch model in AI Settings |
| **Search failure** | provider error/timeout/empty | fall back to next provider in order; cached results if < 24 h | 2 providers max per query | run shows "search degraded (used cache/fallback)" | none needed |
| **Worker crash** | job lease/heartbeat expiry; Procrastinate stalled job detection | job retried by queue; AI runs resume from ledger; publishing resumes via reconciliation | per task | brief "resuming…" state | automatic |
| **Database failure** | connection errors, failover | API returns 503 with `Retry-After`; workers pause (backoff 5 s→60 s); scheduler loses lock and re-acquires | until healthy | banner "Service temporarily unavailable" | automatic; runbook for restore |
| **Network failure (local machine offline)** | DNS/connect errors across hosts | breaker opens for external hosts; local CRUD still works | background jobs retry | status pill "Offline — publishing and AI paused" | automatic on reconnect; overdue posts handled by late-tolerance rule (doc 12) |
| **Partial publishing (threads/carousels)** | per-segment ids in `attempt.state` | stop at failed segment; mark `partially_published` | resume from failed segment with backoff | UI shows which segments posted, offers Continue / Delete posted segments | continue or delete |
| **Ambiguous publish result** | timeout after send, 5xx after upload finalize | `attempt.status=ambiguous` → reconcile | retry only if reconciliation proves nothing was posted | "Verifying with platform…" | automatic; manual check link if platform cannot list own posts |
| **Analytics API failure** | errors per account/post | skip and continue; mark `availability=error` for the metric; schedule retry | 3 attempts over 6 h; deprecated metrics flagged permanently | Analytics shows "last synced hh:mm; 2 metrics unavailable" | automatic |
| **Media provider failure** | provider errors, moderation rejection | fallback provider if configured; moderation → no retry | 2 attempts | Studio media panel error with reason and "Try another provider" | manual |
| **Budget exceeded** | BudgetGuard pre-check | run/task fails fast (`402`); automations pause | none until budget raised | banner + notification to admins | raise budget / wait for period |
| **Prompt injection detected** | classifier/canary | source flagged; run step fails if canary leaks | none | warning badge on source; run failure reason "unsafe source content" | human excludes source |
| **Platform policy rejection** (content violates rules) | 4xx with policy code | `permanent` failure | none | reason + link to content for editing | edit and reschedule |

## 28.3 Retry policies (reference)

| Context | Attempts | Backoff | Notes |
|---|---|---|---|
| Publishing (transient) | 5 | 1 m, 5 m, 15 m, 30 m, 60 m (+jitter ≤ 20%) | reconciliation before retries after ambiguous |
| Publishing (rate limited) | unlimited within 24 h | per `Retry-After`/window | after 24 h → failed |
| Platform reads (analytics/competitor) | 3 | 30 s, 5 m, 30 m | quota errors wait for reset |
| LLM calls | 3 | 1 s, 4 s, 12 s | then fallback model |
| Search/fetch | 2 | 2 s, 8 s | then next provider |
| Media generation | 2 | 10 s, 60 s | async providers polled with 10 s→60 s backoff, 30 min max |
| Outbox relay | 10 | 1 s × 2^n cap 5 m | then dead-letter view |
| Outbound webhooks | 5 | 1 m, 5 m, 30 m, 2 h, 12 h | signed; disabled after 20 consecutive failures |

## 28.4 Runbooks (docs/runbooks)
Dead-lettered publish; mass token expiry after app review changes; platform API version sunset; restoring Postgres from backup; rotating `BOTWOK_MASTER_KEY`; re-embedding after model change; clearing a stuck scheduler lock.
