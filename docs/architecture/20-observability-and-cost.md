# 20 — Observability & Cost Control

## 20.1 Structured logging
- `structlog` JSON lines to stdout; fields: `ts, level, logger, msg, request_id, workspace_id, user_id, run_id, task_id, job_id, platform, duration_ms`.
- Secrets never logged: a processor redacts keys matching `/(token|secret|key|password|authorization)/i` and any value matching known key formats.
- Per-process log context (`contextvars`) so every log line within a request/job carries ids automatically.
- AI request logs: `ai_calls` rows (metadata) + full request/response bodies in MinIO (90-day retention) for debugging; the admin UI links them.
- Agent execution logs: `ai_tasks`/`ai_tool_calls` rows are the log; additionally `logger.info("tool.call", …)` lines for live tailing.

## 20.2 Metrics (Prometheus)
`http_requests_total{route,status}`, `http_request_duration_seconds`, `jobs_total{queue,task,status}`, `job_duration_seconds{task}`, `queue_depth{queue}`, `scheduler_lag_seconds` (now − oldest due scheduled_at), `publish_attempts_total{platform,category}`, `publish_latency_seconds{platform}`, `platform_api_calls_total{platform,endpoint,status}`, `platform_rate_limit_remaining{platform,account}`, `ai_calls_total{provider,model,agent,status}`, `ai_tokens_total{provider,model,direction}`, `ai_cost_usd_total{workspace,agent,model}`, `search_calls_total{provider}`, `media_generations_total{provider}`, `sse_clients`, `outbox_backlog`, `integration_errors_total{integration,kind}`.
Alerts (local: log warnings; VPS: Alertmanager): scheduler lag > 60 s, dead-lettered publish in last hour, outbox backlog > 1000, token expiring with no refresh path, AI error rate > 10%/5 min, budget ≥ 90%.

## 20.3 Tracing
OpenTelemetry SDK with auto-instrumentation for FastAPI, SQLAlchemy, httpx, Redis; manual spans for `orchestrator.run`, `agent.task`, `tool.call`, `provider.complete`, `adapter.publish`. Trace id = `correlation_id` carried through jobs and events. Exporter: console/none locally, OTLP to Tempo/Jaeger on VPS.

## 20.4 Admin / debugging interface (`/w/{ws}/settings/system` → Admin)
Tabs:
- **Jobs**: queue depths, running/failed jobs with args (redacted), retry/cancel, worker heartbeats.
- **Runs**: AI run explorer: plan tree, per-task timing/cost, tool calls with args/results, LLM calls with prompt/response viewers (admin-only), replay.
- **Publishing**: attempts timeline per scheduled post, platform responses, reconciliation outcomes, dead-letter list.
- **Integrations**: per platform: calls/min, error rate, rate-limit headroom, token health, last errors; per AI/search provider: latency, errors, spend.
- **Events**: outbox tail, consumer failures.
- **Costs**: see 20.6.
- **Health**: `/admin/health` (DB, Redis, MinIO, provider reachability, scheduler leader, migrations version).

## 20.5 Cost control
Design levers (all configurable in AI Settings):
1. **Caching** — search results (24 h), fetched documents (24 h), LLM responses for deterministic tools (prompt-hash, 7 d), BrandContext (10 min), provider prompt caching for the stable prefix.
2. **Request deduplication** — identical in-flight runs (same user, same message hash within 60 s) are coalesced; identical research queries reuse a run completed < 6 h ago (user can force refresh).
3. **Result reuse** — sources and chunks are workspace-global; ideation/writer pull from existing research before searching.
4. **Model routing** — cheap/balanced/powerful tiers; planner picks the tier from the agent spec; per-agent override; "economy mode" toggle drops every tier one level.
5. **Token limits** — per-agent context budgets, output caps, max turns/tool calls; sources passed as handles.
6. **Batch processing** — ideation and repurposing batched per call where quality allows (e.g. 10 ideas per call, not 10 calls); analytics analysis runs once daily, not per sync.
7. **Usage budgets** — `usage_budgets` per workspace (day/month) for `ai_cost`, `media_cost`, `search_calls`, `platform_reads`; soft (warn) or hard (block); per-run cap; spend confirmation above a threshold.
8. **Per-workspace limits** — concurrent runs (default 3), research depth cap, media generations/day.
9. **Metered platform reads** — X per-read pricing and YouTube quota tracked in `usage_ledger`; competitor syncs throttle when ≥ 80% of the monthly budget.

## 20.6 Cost dashboard (`/w/{ws}/settings/ai` → Usage, and Admin → Costs)
Cards: spend today/this month vs budget (AI, media, search, platform reads); charts: cost by day, by agent, by model, by provider; table: top runs by cost with links; per-brand split; projected month-end; "what would economy mode save" estimate (recompute last 7 days with routing table swapped). Data source: `usage_ledger` + `ai_calls`; refreshed by a 5-minute aggregation job into `analytics_snapshots(scope=cost)`.

## 20.7 Pricing table
`app/core/pricing.py` ships a versioned table `{provider, model: {input_per_m, output_per_m, cached_per_m}}` and media/search prices; overridable in AI Settings; `ai_calls.cost_usd` is computed at call time with the then-current table (never recomputed historically).
