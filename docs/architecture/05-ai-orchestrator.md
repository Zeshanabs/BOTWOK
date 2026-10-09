# 05 — AI Architecture: the Orchestrator

## 5.1 Overview

```
USER ──► AIService.create_run ──► [queue: ai] ──► ORCHESTRATOR
                                                     │
                     ┌───────────────────────────────┼─────────────────────────────┐
                     ▼                               ▼                             ▼
               IntentRouter                       Planner                      Executor
               (cheap model,                (powerful model,                (DAG runner,
                structured)                  plan schema)                    parallelism)
                                                                                 │
                                        ┌────────────────────────────────────────┤
                                        ▼                                        ▼
                                  AgentRuntime                             ApprovalGate
                            (per task: loop of                         (pauses run, creates
                             LLM ⇄ tools, budgeted)                     approvals, resumes)
                                        │
                     ┌──────────────────┼──────────────────┐
                     ▼                  ▼                  ▼
                 ToolRegistry       MemoryService      BudgetGuard
               (typed tools,      (brand, prefs,      (tokens, cost,
                permissions,       research, content,  model routing)
                side-effect class) performance…)
                     │
          ┌──────────┼──────────────┬───────────────┐
          ▼          ▼              ▼               ▼
      DATABASE   EXTERNAL APIs   MEDIA/SEARCH    (never: platform writes)
          │
          ▼
      RunLedger (ai_runs · ai_tasks · ai_tool_calls · ai_calls) ──► events ──► SSE ──► USER
```

Design rules:
- **Plans are data.** The planner emits a JSON DAG validated against a schema and a capability allowlist; the executor runs it deterministically. The LLM never "decides" to call `publish`; it can only add a `propose_*` step that creates an approval.
- **Agents are narrow.** Each agent has a system prompt, an output schema, a tool allowlist, a model tier, and a budget. Cross-agent work is composed by the plan, not by agents calling each other ad hoc.
- **Everything is a ledger row.** Every LLM call, tool call, and step is persisted before and after execution, so the UI can show progress, the system can resume after a crash, and cost is exact.

## 5.2 Components

### 5.2.1 AIService (entry point)
- `create_run(workspace, brand, user, message, conversation_id, mode)` → inserts `ai_runs(status=queued, input=…)`, appends the user message to `ai_messages`, enqueues `jobs.ai.run(run_id)` in the same transaction, returns `run_id`.
- `cancel_run(run_id)` → sets `cancel_requested=true` and `SETEX botwok:run:{id}:cancel 1 3600` in Redis.
- `resume_run(run_id)` → only valid in `awaiting_approval`/`paused`; re-enqueues.
- Modes: `chat` (conversational, light planning), `task` (full plan), `tool` (single-agent direct invocation used by Studio buttons, e.g. "critique this"), `automation` (invoked by AutomationEngine with a fixed plan template).

### 5.2.2 ContextBuilder
Builds the **RunContext** every component receives:
```python
@dataclass
class RunContext:
    run_id: UUID; workspace_id: UUID; brand_id: UUID | None; user_id: UUID
    brand: BrandContext            # from BrandService (name, audience, voice, pillars, forbidden topics, CTAs, hashtags…)
    preferences: UserPreferences   # writing preferences, approval defaults, timezone
    conversation: list[Message]    # last N turns + rolling summary (conversation memory)
    memory: MemoryBundle           # retrieved research/content/performance/strategy memories (ids + snippets)
    budget: Budget                 # max_cost_usd, max_tokens, max_tool_calls, max_wall_seconds
    settings: AISettings           # model routing table, provider keys (handles only), safety thresholds
    trust_policy: TrustPolicy      # how untrusted content is wrapped
```

### 5.2.3 IntentRouter
One cheap structured call: `{intent: enum, entities: {...}, capabilities: [...], clarification_needed: bool, question?: str}`.
Intent catalog: `research_topic`, `research_competitors`, `find_trends`, `find_news`, `analyze_competitor_content`, `strategy_recommendation`, `generate_ideas`, `write_post`, `repurpose`, `generate_media`, `build_calendar`, `schedule`, `publish`, `analyze_performance`, `report`, `configure_automation`, `question_about_data`, `smalltalk`, `unknown`.
If `clarification_needed`, the run completes with a question (no plan). Intents map to **plan templates** that seed the planner (reduces planner variance and cost).

### 5.2.4 Planner
Powerful model, structured output `Plan`:
```json
{
  "goal": "Research top 5 competitors and find content opportunities",
  "tasks": [
    {"id":"t1","agent":"competitor_intel","action":"resolve_competitors","inputs":{"limit":5},"depends_on":[],"budget":{"max_cost_usd":0.5}},
    {"id":"t2","agent":"research","action":"research","inputs":{"query_from":"t1.competitors[*].website","depth":"standard"},"depends_on":["t1"],"fan_out":"t1.competitors"},
    {"id":"t3","agent":"social_listening","action":"collect_public_posts","inputs":{"competitors_from":"t1"},"depends_on":["t1"],"fan_out":"t1.competitors"},
    {"id":"t4","agent":"competitor_intel","action":"analyze","inputs":{"sources_from":["t2","t3"]},"depends_on":["t2","t3"]},
    {"id":"t5","agent":"competitor_intel","action":"find_gaps","inputs":{"analysis_from":"t4","brand":"$brand"},"depends_on":["t4"]},
    {"id":"t6","agent":"report","action":"compose","inputs":{"kind":"competitor_opportunities","from":["t4","t5"]},"depends_on":["t5"]}
  ],
  "approval_points": [],
  "deliverables": ["t6.report","t5.gaps"]
}
```
Validation (`PlanValidator`): agent ids exist and are enabled; actions exist on that agent; DAG is acyclic; total estimated cost ≤ budget; any task whose agent/action is `side_effect=APPROVAL` is marked `requires_approval=true`; fan-out width ≤ 10 (configurable). Invalid plans are re-prompted once with the validation errors, then the run fails with a readable message.

### 5.2.5 Executor
- Persists tasks to `ai_tasks` (status `pending`), computes readiness, and runs ready tasks concurrently up to `max_parallel` (default 3) using `asyncio.TaskGroup`.
- Resolves input references (`t1.competitors`) from stored task outputs (`ai_tasks.output` JSONB).
- Fan-out: materializes child tasks (`t2.1 … t2.n`) with their own ledger rows; a fan-in task receives the list.
- Checks `cancel_requested` before each task and between tool calls (cooperative cancellation; tools get an `asyncio` timeout).
- On task failure applies the policy (5.5); on run completion writes `ai_runs.result = {deliverables, sources, reasoning_summary, actions}`.
- Crash safety: if a worker dies mid-run, Procrastinate retries the job; the executor resumes from the ledger (tasks already `succeeded` are not re-run; a task in `running` with no heartbeat for 2 min is re-run idempotently because tools are idempotent by `(run_id, task_id, call_index)`).

### 5.2.6 AgentRuntime (the loop)
```python
async def run_task(task, ctx):
    agent = registry[task.agent]                       # prompt, tools, model tier, output schema, limits
    messages = agent.build_messages(ctx, task.inputs)  # system + brand context + memory + inputs (untrusted wrapped)
    for turn in range(agent.max_turns):                # default 8
        BudgetGuard.check(ctx, task)                   # raises BudgetExceeded
        resp = await provider.complete(messages, tools=agent.tools, model=route(agent.tier, ctx),
                                       response_format=agent.output_schema if final else None)
        ledger.record_call(resp.usage, cost)           # ai_calls row
        if resp.tool_calls:
            results = await ToolRunner.run_all(resp.tool_calls, agent, ctx, task)   # permission check, logging, timeouts
            messages += tool_results(results)          # each wrapped as untrusted if it carries external text
            continue
        output = agent.parse(resp.content)             # pydantic validation; on failure → re-prompt with errors (max 2)
        return output
    raise AgentTurnLimit
```
Tool results carrying external text (web pages, social posts) are wrapped: `<untrusted source_id="…">…</untrusted>` plus the standing instruction that content inside is data, never instructions (doc 19).

### 5.2.7 ToolRegistry & ToolRunner
Tool definition:
```python
@tool(name="research.save_source", side_effect=SideEffect.WRITE_INTERNAL, roles={"editor","admin","owner"},
      timeout_s=20, idempotent=True)
async def save_source(ctx: ToolContext, url: HttpUrl, title: str, summary: str, relevance: float, credibility: float) -> SourceRef: ...
```
Side-effect classes: `READ`, `WRITE_INTERNAL` (DB rows inside Botwok), `EXTERNAL_READ` (search/fetch/platform reads), `SPEND` (paid generation beyond threshold), `APPROVAL` (anything that would publish, schedule, delete externally, send messages, or change settings). `APPROVAL` tools never execute the action; they create a **ProposedAction** → `approvals` row and pause the run.
ToolRunner: validates args against the Pydantic signature, checks the agent allowlist and user role, enforces per-tool and per-run rate limits, records `ai_tool_calls(status=running)`, executes with timeout, stores result (truncated to 32 KB; large payloads stored in MinIO with a handle), records duration and errors.

### 5.2.8 ApprovalGate
When a task hits an `APPROVAL` tool: `approvals(kind=ai_action, payload=proposed_action, run_id, task_id, status=pending)`, `ai_runs.status=awaiting_approval`, event `AI_RUN_AWAITING_APPROVAL`, notification to approvers. On `approve`: the gate executes the action via the deterministic service (e.g. `SchedulingService.schedule(...)`), stores the result as the tool result, and resumes. On `reject`: the tool result is `{"rejected": true, "reason": …}` and the agent continues (it can revise or end).
Also supports **batch approvals**: a plan may declare one approval point for N actions ("Schedule 5 posts").

### 5.2.9 MemoryService
Read points: ContextBuilder (brand, preferences, conversation summary, top-k semantic memories for the message), agent-level `memory.search` tool for deeper retrieval. Write points: run end (conversation summary), research completion (research memory), content approval (content memory), analysis completion (performance memory), strategy acceptance (strategy memory), explicit user "remember this" (preferences). See doc 15 for what goes where.

### 5.2.10 BudgetGuard & model routing
- Budgets: per run (default $1.50), per workspace per day/month (`usage_budgets`), per agent per task.
- Pre-call estimate: `tokens_in ≈ count_tokens(messages)`, `tokens_out ≈ agent.expected_out`; refuse if `(estimate_cost + spent) > budget`; emit `BUDGET_THRESHOLD_REACHED` at 80%.
- Routing table (`ai_settings.routing`), defaults:

| Tier | Default | Used by |
|---|---|---|
| cheap | Claude Haiku 4.5 (or local 8B via Ollama) | IntentRouter, ideation, extraction/classification, summaries |
| balanced | Claude Sonnet 5.5 (or GPT-5-class mid model) | research, social_listening, trend, repurposer, visual, critic, fact_check, report |
| powerful | Claude Opus 5.5 (or Grok/GPT top model) | planner, strategy, writer, competitor_intel analysis, performance_analyst |
| embeddings | text-embedding-3-small / nomic-embed-text | MemoryService, research chunks |

Rules: critic must not use the same model family as writer when possible (configurable); any tier can be pinned per agent; fallbacks per tier (`[primary, secondary]`) used on provider errors/429.

### 5.2.11 CitationTracker
Every tool result that originates from a source carries `source_id`s. Agents must output `sources: [source_id]` per claim-bearing section (schema-enforced). On run completion the tracker resolves ids → `research_sources` rows and builds the Sources panel; `content_sources` rows are written when content is created from a run. A post-check flags output URLs not present in the run's sources (hallucinated citation guard).

### 5.2.12 RunLedger & events
Tables: `ai_runs` (status, plan, result, cost, tokens, timings), `ai_tasks` (per plan step), `ai_tool_calls`, `ai_calls` (every LLM call: model, provider, tokens in/out/cached, cost, latency, finish reason, prompt hash). Events: `AI_RUN_STARTED`, `AI_RUN_STEP_COMPLETED` (per task; payload includes step label, duration, sources count, cost), `AI_RUN_AWAITING_APPROVAL`, `AI_RUN_COMPLETED`, `AI_RUN_FAILED`. The SSE stream relays them; the Command Center renders the checklist.

## 5.3 Context management

- **Budget per agent** (input tokens): cheap 16k, balanced 48k, powerful 96k. The builder fills in priority order: system prompt → task inputs → brand context (compact form, ~1.5k tokens) → conversation (last 6 turns + rolling summary) → retrieved memory (top-k by similarity, k=8, each ≤ 400 tokens) → tool results (most recent first, older ones replaced by one-line summaries).
- **Sources are handles.** Agents receive `{source_id, title, domain, date, snippet(≤300 tokens)}`; `research.read_source(source_id, section?)` fetches more on demand. Full documents never enter prompts wholesale.
- **Rolling summaries.** After every 4 tool turns the runtime asks the cheap model to compress tool-result history into a structured "findings so far" block.
- **Conversation memory** is a summary + last turns; raw transcripts stay in `ai_messages`.
- **Prompt caching**: the system prompt + brand context prefix is stable per brand and marked cacheable on providers that support it.

## 5.4 Retries & error handling

| Failure | Policy |
|---|---|
| Provider 429/5xx/timeout | retry 3× with exponential backoff + jitter (1s, 4s, 12s); then fallback model of the same tier; then task fails |
| Invalid structured output | re-prompt with validation errors, max 2; then task fails |
| Tool timeout / error | result returned to the agent as `{error}`; agent may retry a different approach; after 3 tool errors in a task → task fails |
| Budget exceeded | task fails with `BudgetExceeded`; executor marks dependents `skipped`; run completes `failed` with partial deliverables preserved |
| Task failed, `optional=true` in plan | dependents receive `null`; run continues |
| Task failed, required | run → `failed`; partial outputs and sources remain visible; user can "retry from this step" (re-enqueue with `resume_from=task_id`) |
| Worker crash | Procrastinate retry; resume from ledger (idempotent tools) |
| Cancellation | cooperative at task/tool boundaries; status `cancelled`; partial outputs kept |

## 5.5 Human-in-the-loop points

1. Clarification questions (IntentRouter / planner may ask before planning).
2. Approval gates for `APPROVAL` tools (schedule, publish, delete, send, settings).
3. Spend confirmation when a single run's projected cost exceeds `ai_settings.confirm_above_usd` (default $2).
4. Content approval is independent of AI runs: content produced by AI lands as `ai_generated` → `needs_review`; publishing requires `approved`.
5. Automation runs inherit the same gates; an automation can be configured to pause for approval or to stop at "create drafts" (default).

## 5.6 Transparency contract (what the UI must be able to show)

For every run: the plan (steps, agents), live step status with durations, each tool call (name, args summary, result summary, duration, errors), sources used (with credibility/relevance), reasoning summary (agent-written, non-chain-of-thought, 3–8 bullets), generated artifacts (ids, links), proposed actions and their approval status, cost and tokens per step and total, what failed and why, and the final deliverables. All of this is reconstructible from the ledger tables after the fact.

## 5.7 Example: how a chat message becomes work

User: "Find 5 trends in medical billing and create LinkedIn posts."
1. `POST /ai/runs` → run `queued`.
2. Worker: IntentRouter → `find_trends` + `write_post` (multi-intent allowed) with entities `{topic:"medical billing", platform:"linkedin", count:5}`.
3. Planner (seeded by templates `find_trends`, `write_post`): `t1 research(news, 14d)` ‖ `t2 social_listening(x,linkedin public where licensed)` → `t3 trend.detect` → `t4 strategy.select_opportunities(5)` → `t5 writer × 5 (fan-out)` → `t6 critic × 5` → `t7 fact_check × 5` → deliverables.
4. Executor streams: "Researching web ✓ · Checking industry news ✓ · Checking competitors ✓ · Finding trends ✓ · Selecting opportunities ✓ · Generating posts ✓ · Quality checking ✓".
5. Writer outputs create `content_items` (status `ai_generated`) with `content_sources`; critic scores stored in `content_versions.critique`; fact-check verdicts stored per claim.
6. Result panel: Sources (ranked), Reasoning summary, Generated content (5 cards → Open in Studio / Approve / Schedule), Actions (none pending, because scheduling was not requested).
