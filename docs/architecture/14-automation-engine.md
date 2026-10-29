# 14 — Automation Architecture

## 14.1 Model

A workflow is a directed graph of typed nodes. The engine is deterministic; AI appears only inside `ai_agent`/`research`/`generate`/`transform(ai)` nodes, which call the orchestrator in `automation` mode with a fixed plan template. Every run is a resumable state machine persisted per step.

```
WHEN  trigger(news_detected, relevance ≥ 80)
THEN  research(topic)  →  generate(ideas, 5)  →  generate(linkedin_post)  →  approve  →  schedule(best_time)
```

## 14.2 Node catalog

| Node type | Config | Output | Side-effect class |
|---|---|---|---|
| `trigger.cron` | rrule/cron, timezone | `{fired_at}` | — |
| `trigger.event` | event name + filter (e.g. `TREND_DETECTED`, `ANALYTICS_UPDATED`, `CONTENT_APPROVED`) | event payload | — |
| `trigger.webhook` | secret, schema | request body | — |
| `trigger.manual` | — | user input | — |
| `condition` | expression over context (safe expression language, see 14.5) | branch `true`/`false` | — |
| `ai_agent` | agent id, action, input mapping, budget | agent output | per agent |
| `research` | query template, scope, depth | research run id + findings | EXTERNAL_READ |
| `generate` | kind: ideas|post|variants|image|report; params | content/idea/media ids | WRITE_INTERNAL / SPEND |
| `transform` | mode: `template` (Jinja over context) or `ai` (cheap-model mapping) | mapped value | — |
| `approve` | approvers (roles/users), timeout, what to show | `approved|rejected` + comment | APPROVAL (pauses run) |
| `schedule` | account(s), time strategy (fixed|best_time|next_slot), variant ids from context | scheduled_post ids | APPROVAL by default (configurable to auto when content already approved) |
| `publish` | publish-now for already-approved variants | attempt ids | APPROVAL by default |
| `wait` | duration or until (expression) | — | — (run → `waiting`) |
| `webhook` | URL (allowlisted hosts), method, body template, signing | response | EXTERNAL_WRITE (requires admin enable) |
| `notification` | channel(s), template | — | WRITE_INTERNAL |
| `analytics` | query spec (dimension, metric, period) or `insights.analyze` | data | — |
| `action` | built-in service actions: `content.set_status`, `ideas.add_to_planner`, `competitors.sync`, `report.generate`, `memory.write` | result | WRITE_INTERNAL |

Guardrails: `publish`/`schedule`/`webhook` nodes are disabled unless an admin enables "autonomous actions" for the workflow; even then the global policy "AI-generated content requires human approval" (doc 19) applies without exception in V1. Per-workflow relaxation (for specific low-risk formats, with a recorded reason and audit entry) is a post-V1 option that follows the `auto_approve` threshold design in doc 19 §19.7.

## 14.3 Storage

```
automation_workflows   id, workspace_id, brand_id, name, description, status (draft|active|paused|archived), version, trigger_summary,
                       autonomous_actions_enabled bool, settings jsonb (timeout, max_cost_usd, on_error: stop|continue|notify), created_by
workflow_nodes         id, workflow_id, key (string, unique per workflow), type, config jsonb, position jsonb {x,y}, label
workflow_edges         id, workflow_id, from_node_key, to_node_key, branch (null|'true'|'false'|'approved'|'rejected'|'error'), condition jsonb?
automation_runs        id, workflow_id, workflow_version, trigger_type, trigger_payload jsonb, status, context jsonb (variables),
                       started_at, finished_at, cost_usd, error, current_node_key, waiting_until, approval_id
automation_run_steps   id, run_id, node_key, status (pending|running|waiting|awaiting_approval|succeeded|failed|skipped), input jsonb,
                       output jsonb, ai_run_id?, started_at, finished_at, attempts, error
```
Saving from the builder is a single `PUT /automations/{id}` with `{nodes[], edges[]}`; the server validates (one trigger, acyclic except explicit `wait` loops bounded by `max_iterations`, every node reachable, configs valid per node schema), bumps `version`, and stores. Runs pin `workflow_version` so edits don't change in-flight runs.

Example serialized workflow (abridged):
```json
{"name":"Industry news → LinkedIn post",
 "nodes":[
  {"key":"t","type":"trigger.event","config":{"event":"TREND_DETECTED","filter":{"min_score":80,"kinds":["news"]}}},
  {"key":"r","type":"research","config":{"query":"{{ trigger.trend.label }}","scope":["news","web"],"depth":"standard"}},
  {"key":"i","type":"generate","config":{"kind":"ideas","count":5,"from":"{{ steps.r.research_run_id }}"}},
  {"key":"p","type":"generate","config":{"kind":"post","platform":"linkedin","idea":"{{ steps.i.ideas[0].id }}"}},
  {"key":"a","type":"approve","config":{"approvers":{"roles":["approver","admin"]},"timeout_hours":48}},
  {"key":"s","type":"schedule","config":{"account":"{{ brand.default_accounts.linkedin }}","strategy":"best_time","variant":"{{ steps.p.variant_id }}"}}],
 "edges":[{"from":"t","to":"r"},{"from":"r","to":"i"},{"from":"i","to":"p"},{"from":"p","to":"a"},
          {"from":"a","to":"s","branch":"approved"}]}
```

## 14.4 Execution

```
trigger fires (scheduler cron / EventBus consumer / webhook / manual)
→ AutomationEngine.start(workflow, payload): automation_runs(status=running, context={trigger, brand, workspace})
→ enqueue jobs.automation.execute(run_id)
worker: loop
   node = next ready node (edges satisfied, branch matched)
   step = run_steps(status=running); executor = registry[node.type]
   result = await executor.run(node.config rendered with context, run)
     - ai nodes → AIService.create_run(mode=automation) and await completion (job yields; resumed by AI_RUN_COMPLETED consumer)
     - approve → approvals row; run.status=awaiting_approval; stop (resumed by ApprovalService hook)
     - wait → run.status=waiting; waiting_until; stop (resumed by scheduler)
   context.steps[node.key] = result; step.status=succeeded; AUTOMATION_STEP_COMPLETED
   on error: per settings.on_error (stop → run failed + AUTOMATION_FAILED + notify; continue → follow 'error' edge if present)
until no ready nodes → run succeeded → AUTOMATION_COMPLETED
```
Idempotency: each step execution records `attempts`; executors are idempotent per `(run_id, node_key)` (e.g. a `generate` node reuses the ids it already produced if re-run after a crash). Concurrency: one active run per workflow by default (`queueing_lock=automation:{workflow_id}`); configurable.

## 14.5 Expression language
Conditions and templates use a **sandboxed** expression evaluator (no Python `eval`): Jinja2 `SandboxedEnvironment` for templates and a small boolean expression grammar (`a.b >= 80 and "news" in kinds`) compiled to an AST with a whitelist of operators and functions (`len`, `lower`, `contains`, `date_diff`). Context exposes `trigger`, `brand`, `steps`, `now`, `env.workspace`.

## 14.6 Builder (frontend)
React Flow canvas; node palette by category; node config side panel generated from each node type's JSON schema (`GET /automations/node-types`); inline validation; "Test run" executes with a sample payload and `dry_run=true` (AI nodes run, side-effect nodes are simulated); run history with per-step logs and links to AI runs. The example in the brief renders as Trigger → Condition → Research → Generate(5 ideas) → Generate(LinkedIn post) → Approve → Schedule.

## 14.7 Built-in templates
Weekly industry research + ideas to planner (scenario in doc 31) · Weekly competitor monitoring + report · Daily news watch → draft posts · Post-publish 7-day performance check → notify · Monthly strategy review.
