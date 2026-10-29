# 18 — Event Architecture

## 18.1 Mechanism: transactional outbox + Redis fan-out + queue consumers

```
Service (in a DB transaction)
   └─ EventBus.emit(Event)  ──►  events_outbox row (same txn)        [durable]
                                        │
                     outbox relay (worker, every 500 ms / LISTEN-NOTIFY)
                                        │
                   ┌────────────────────┼─────────────────────┐
                   ▼                    ▼                     ▼
        Redis PUBLISH ws:{ws_id}   Consumer jobs enqueued    audit_logs (selected events)
        (SSE to browsers)          (procrastinate, per consumer)
```
- Emitting is cheap and atomic with the domain write; the relay marks rows `published_at` after fan-out (at-least-once; consumers are idempotent by `event_id`).
- Consumers are registered in code: `@on_event("PUBLISH_SUCCESS") async def schedule_metric_pulls(evt): …`. Each consumer runs as its own job so one slow consumer cannot block others.
- Events are **facts, past tense**, never commands. Commands are service calls or jobs.

## 18.2 Envelope
```json
{"event_id":"uuid","name":"PUBLISH_SUCCESS","workspace_id":"…","brand_id":"…","occurred_at":"…",
 "actor":{"type":"system|user|agent","id":"…"},"payload":{…},"correlation_id":"request or run id","version":1}
```

## 18.3 Catalog: producers → consumers

| Event | Producer | Payload (key fields) | Consumers |
|---|---|---|---|
| `CONTENT_CREATED` / `CONTENT_UPDATED` | ContentService | content_item_id, version | embedding updater (content memory), SSE |
| `CONTENT_STATUS_CHANGED` | ContentService | id, from, to, by | calendar cache, automation `trigger.event`, notifications (assignee) |
| `VARIANT_CREATED` | ContentService/repurposer | variant_id, platform | critic auto-pass job, validation job |
| `APPROVAL_REQUESTED` | ApprovalService | approval_id, kind, target | NotificationService (approvers), SSE |
| `CONTENT_APPROVED` / `CONTENT_REJECTED` | ApprovalService | content_item_id, approver, comment | content memory writer, automation triggers, SSE |
| `POST_SCHEDULED` / `POST_RESCHEDULED` / `POST_CANCELLED` / `POST_PAUSED` | SchedulingService / scheduler (late-tolerance hold, expiry hold) | scheduled_post_id, at, reason | calendar SSE, notifications |
| `PUBLISH_STARTED` | publish worker | scheduled_post_id, attempt_no | SSE |
| `PUBLISH_SUCCESS` | publish worker | published_post_id, external_url | AnalyticsSync (schedule metric pulls 1h/6h/…), NotificationService, content memory, SSE |
| `PUBLISH_FAILED` | publish worker | scheduled_post_id, category, message, next_attempt_at | NotificationService (if permanent or last attempt), SSE |
| `PUBLISH_DEAD_LETTERED` | publish worker | scheduled_post_id, attempts | NotificationService (urgent), admin dashboard |
| `ANALYTICS_SYNC_STARTED` / `ANALYTICS_UPDATED` / `ANALYTICS_SYNC_FAILED` | AnalyticsSyncService | account_id, posts_updated, deltas | snapshot recompute, InsightService trigger (daily gate), SSE |
| `RESEARCH_STARTED` / `RESEARCH_COMPLETED` / `RESEARCH_FAILED` | ResearchService | run_id, source_count | trend signal ingestion, research memory, SSE |
| `SOURCE_SAVED` | ResearchService | source_id, injection_flag | chunk+embed job |
| `COMPETITOR_ADDED` / `COMPETITOR_UPDATED` / `COMPETITOR_SNAPSHOT_TAKEN` | CompetitorService | competitor_id, profile_id, deltas | trend signals, monitoring alerts, SSE |
| `TREND_DETECTED` / `TREND_UPDATED` | TrendService | trend_id, score, kinds | automation triggers, notifications (score ≥ threshold) |
| `AI_RUN_STARTED` / `AI_RUN_STEP_COMPLETED` / `AI_RUN_AWAITING_APPROVAL` / `AI_RUN_COMPLETED` / `AI_RUN_FAILED` | Orchestrator | run_id, step, cost, sources_count | SSE (Command Center), AutomationEngine (resume waiting step), usage ledger |
| `AI_ANALYSIS_COMPLETED` / `RECOMMENDATION_CREATED` | InsightService | insight_ids, recommendation_ids | NotificationService, performance memory, Dashboard SSE |
| `SOCIAL_ACCOUNT_CONNECTED` / `SOCIAL_ACCOUNT_TOKEN_EXPIRING` / `SOCIAL_ACCOUNT_EXPIRED` / `SOCIAL_ACCOUNT_REVOKED` | SocialAccountService / token monitor / adapters on 401 | account_id, expires_at, reason | NotificationService, scheduler (pause posts on expired/revoked accounts → `POST_PAUSED`), SSE |
| `AUTOMATION_TRIGGERED` / `AUTOMATION_STEP_COMPLETED` / `AUTOMATION_COMPLETED` / `AUTOMATION_FAILED` | AutomationEngine | run_id, node_key | SSE, notifications |
| `MEDIA_GENERATED` / `MEDIA_PROCESSED` | MediaService | asset_id, provider, cost | usage ledger, SSE (Studio media panel) |
| `BUDGET_THRESHOLD_REACHED` / `BUDGET_EXCEEDED` | BudgetGuard | kind, period, used, limit | NotificationService (admins), run pausing |
| `NOTIFICATION_CREATED` | NotificationService | notification_id, channels | channel senders (email/Slack/webhook) |
| `REPORT_GENERATED` | ReportService | report_id | delivery job |

## 18.4 Consumers that matter for correctness
- **Token monitor** (daily): scans `oauth_tokens.expires_at` within 7 days → `SOCIAL_ACCOUNT_TOKEN_EXPIRING`; attempts refresh where the platform supports it (Meta long-lived refresh, Threads refresh, X refresh token, TikTok refresh, Google refresh, Pinterest continuous refresh; **LinkedIn only if the app has refresh tokens**) and otherwise notifies to reconnect.
- **Metric pull scheduler**: on `PUBLISH_SUCCESS` creates the decaying pull schedule (stored as jobs with `run_at`).
- **Outbox relay** is a single-leader loop (advisory lock) with batch size 200; failures increment `attempts`, rows with `attempts > 10` go to a dead-letter view and alert.

## 18.5 SSE topics
`runs` (AI run events for the current user's runs + workspace-wide for admins), `publishing` (scheduled post transitions), `notifications`, `calendar`, `media`. Clients reconnect with `Last-Event-ID`; the server replays from a 10-minute Redis stream (`XADD` with MAXLEN).

## 18.6 Outbound webhooks (workspace integrations)
`webhooks(direction=outbound)` subscribe to event names; delivery job signs the body (HMAC-SHA256, `X-Botwok-Signature`), retries 5× with backoff, and records deliveries in `audit_logs`. Allowed only to hosts not in private IP ranges (SSRF guard).
