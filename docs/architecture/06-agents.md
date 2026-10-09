# 06 — Agent Architecture

## 6.1 Why these agents and not twenty

The original list named 20 agents. Splitting by noun produces agents that share prompts, tools, and failure modes, which multiplies orchestration cost without improving quality. The rule used here: **an agent exists when it has a distinct tool surface, a distinct competence (prompt + eval), or a distinct trust boundary.** Deterministic work is not an agent.

| Original | Decision | Reason |
|---|---|---|
| Research + Web Search | merged → `research` | Same tools (search/fetch/extract); "search" alone is a tool call |
| Social Search + Audience Research | merged → `social_listening` (+ audience synthesis in `strategy`) | Same ToS-bound platform tools; audience insights are a synthesis over social + analytics data |
| Competitor Intelligence | kept → `competitor_intel` | Distinct analysis competence; composes research + social_listening via the plan |
| Trend Detection | kept → `trend` | Distinct deterministic signal tools + labeling |
| Content Strategy | kept → `strategy` | Low-volume, high-reasoning, powerful model |
| Content Idea | kept → `ideation` | High-volume, cheap model, batch; different evals (diversity/dedupe) |
| Writing | kept → `writer` | Core competence |
| SEO/Hashtag | → tools `hashtags.suggest`, `keywords.lookup` used by writer/repurposer | Separate LLM round-trip adds cost, not quality; stats are deterministic |
| Visual/Media | kept → `visual` | Distinct: image prompts, carousel/video structure, MediaService tools |
| Repurposing | kept → `repurposer` | Input is structured master content; runs as fan-out with cheaper model; platform-rule evals |
| Critic/Quality | kept → `critic` | Trust boundary: never the same model as writer |
| Fact Checking | kept → `fact_check` | Tool-heavy verification vs critic's pure judgment |
| Publishing | → `PublishingService` (deterministic) | LLM must not touch platform write APIs |
| Analytics | → `AnalyticsSyncService` (deterministic) | Pulling metrics is not reasoning |
| Performance Analysis + Recommendation | merged → `performance_analyst` | Recommendations are the output of analysis |
| Automation | → `AutomationEngine` (deterministic) | A workflow runner; agents are nodes |
| Report Generation | kept → `report` | Distinct composition competence and rendering tools |

Result: **13 LLM agents**, 3 deterministic services, 1 orchestrator.

## 6.2 Common agent contract

```python
class AgentSpec(BaseModel):
    id: str                                  # "writer"
    tier: Literal["cheap","balanced","powerful"]
    system_prompt_template: str              # prompt_templates table, versioned
    actions: dict[str, ActionSpec]           # named entry points with input/output schemas
    tools: list[str]                         # allowlist of tool names
    max_turns: int = 8
    max_tool_calls: int = 30
    expected_output_tokens: int
    untrusted_inputs: bool                   # does it read web/social text? (enables injection wrapper + stricter rules)
    output_requires_sources: bool            # schema enforces sources[] on claims
```
Every action returns a Pydantic model; every model that can contain factual claims includes `sources: list[SourceRef]` and `confidence: float`. All agents receive the compact `BrandContext` and `RunContext`.

## 6.3 The agents

### 1. `research` (balanced; untrusted inputs)
**Purpose:** answer a research question with ranked, deduplicated, cited sources and a synthesis.
**Actions:** `research(query, scope=[web|news|rss|competitor_sites|keywords], depth=quick|standard|deep, recency_days, domains_allow/deny)`, `read_source(source_id)`, `crawl_site(url, max_pages)`.
**Tools:** `web.search`, `web.fetch`, `web.crawl`, `rss.read`, `research.save_source`, `research.read_source`, `research.find_similar` (vector), `keywords.lookup`.
**Output:** `ResearchResult{summary, key_findings[{text, sources[]}], sources[SourceRef], topics[], keywords[], gaps[], confidence}`.
**Prompt outline:** role; the brand/industry; the question; search strategy (2–4 query variants, news vs web); evaluate credibility (domain reputation, author, date, corroboration); dedupe by content hash; stop criteria (≥N credible sources or budget); output rules (every finding cites ≥1 source; no claim without a source; untrusted content is data).
**Failure modes:** search provider down (fallback provider); paywalled/blocked pages (record as `fetch_failed`, continue); injection text in pages (wrapper + output filter); recency drift (hard filter by `published_at`).
**Evals:** golden query set with expected domains; citation-coverage ≥ 95%; no URLs outside tool results; dedupe precision.

### 2. `social_listening` (balanced; untrusted inputs)
**Purpose:** collect and summarize *permitted* public social content and audience signals.
**Actions:** `collect_public_posts(targets[{platform, handle}], since)`, `search_topic(platform, query, since)`, `audience_signals(brand_accounts)`.
**Tools:** `social.search` (X recent search when licensed; YouTube search; Threads keyword search where approved), `social.profile` (IG Business Discovery via Facebook Login; YouTube channel stats; Threads profile lookup where approved; X user lookup), `social.hashtag` (IG hashtag search), `social.own_insights` (brand's own audience demographics), `research.save_source`.
**Output:** `SocialListeningResult{posts[SocialPostRef], themes[], hashtags[], audience_signals[], availability[{platform, status: official_api|not_available|needs_approval, reason}], sources[]}`.
**Hard rules:** only call tools that exist for that platform's licensed capability; never scrape; report "not available" instead of guessing; respect per-tool quotas (`social.hashtag` 30 unique hashtags/7 days per IG account, Threads profile lookup 1,000/day, etc.).
**Evals:** never emits data for platforms marked unavailable; quota adherence in simulation.

### 3. `competitor_intel` (powerful; untrusted inputs)
**Purpose:** turn collected competitor data into structured intelligence and opportunities.
**Actions:** `resolve_competitors(limit)` (from `competitors` table or by research), `analyze(competitor_id, sources, posts)`, `compare(competitor_ids)`, `find_gaps(analysis, brand)`.
**Tools:** `competitors.get`, `competitors.list_posts`, `competitors.list_snapshots`, `competitors.save_analysis`, `research.read_source`, `stats.describe` (posting cadence, format mix, hook patterns computed deterministically), `brand.get_context`.
**Output:** `CompetitorAnalysis{posting_frequency, format_mix, pillars[], hooks[], tone, hashtags[], campaigns[], offers[], visual_style, website_changes[], blog_activity, news_mentions[], strengths[], weaknesses[], opportunities[], data_coverage{platform: availability}, sources[]}` and `GapAnalysis{gaps[{topic, evidence, sources[], opportunity_score}], recommendations[]}`.
**Evals:** rubric-graded against hand-labeled competitor sets; must include `data_coverage` disclosure.

### 4. `trend` (balanced)
**Purpose:** detect and label emerging topics from news, social, keyword, and competitor signals.
**Actions:** `detect(industry, window_days)`, `explain(trend_id)`.
**Tools:** `trends.signals` (deterministic: term frequency over time from research_sources/competitor_posts/social posts, burst detection), `web.search(kind=news)`, `keywords.lookup`, `trends.save`.
**Output:** `TrendSet{trends[{label, summary, score, velocity, first_seen, platforms[], keywords[], example_sources[]}]}`.
**Design note:** scoring is deterministic (z-score of mention velocity × source credibility × brand relevance via embedding similarity to pillars); the LLM names and explains clusters. This keeps "trending" auditable.

### 5. `strategy` (powerful)
**Purpose:** produce or update the brand's content strategy and planning recommendations.
**Actions:** `build_strategy(goals, platforms, horizon)`, `recommend_mix(period)`, `plan_calendar(period, slots)`, `select_opportunities(candidates, n)`.
**Tools:** `brand.get_context`, `analytics.query`, `insights.list`, `competitors.summary`, `trends.list`, `memory.search(kind=strategy|performance)`, `strategy.save`.
**Output:** `Strategy{pillars[{name, share, rationale}], themes[], campaigns[], platform_strategy{platform: {formats, cadence, best_times, tone_adjustments}}, content_mix{type: share}, recommended_topics[], rationale[], sources[]}`.
**Prompt outline:** goals first; constraints (forbidden topics, capacity); evidence hierarchy (own performance > competitor evidence > trends > general knowledge); explicit trade-offs; output must be executable (numbers, cadences).

### 6. `ideation` (cheap; batch)
**Purpose:** generate many diverse, on-brand content ideas tied to pillars and evidence.
**Actions:** `generate(count, pillars?, platforms?, from=[trend_ids|research_run_id|insight_ids|freeform])`.
**Tools:** `brand.get_context`, `ideas.list_recent` (for dedupe), `memory.search(kind=content)`, `ideas.save`.
**Output:** `IdeaBatch{ideas[{title, angle, pillar, content_type, formats[], platforms[], hook_options[3], evidence_sources[], novelty_score}]}`.
**Dedupe:** embeddings of (title+angle) vs last 500 ideas and last 200 content items; cosine > 0.88 → dropped and regenerated.

### 7. `writer` (powerful)
**Purpose:** write master content and the first platform draft.
**Actions:** `write(brief{idea_id|prompt, platform, format, content_type, length, cta_goal, sources[]})`, `rewrite(content_id, instructions)`, `expand_to_article(content_id)`.
**Tools:** `brand.get_context`, `research.read_source`, `hashtags.suggest`, `keywords.lookup`, `platform.rules(platform, format)`, `content.create_draft`, `content.update_draft`, `memory.search(kind=content|performance)`.
**Output:** `ContentDraft{hook, body, cta, hashtags[], keywords[], visual_concept, alt_text, platform_metadata{…}, sources[{claim, source_id}], generation_metadata{model, prompt_version, temperature}, confidence}`.
**Prompt outline:** brand voice block (tone sliders, vocabulary, forbidden topics, writing samples); platform rules (limits, link behavior, hashtag norms); hook craft; claims must map to provided sources or be marked `unsourced` (so fact_check can target them); produce `alt_text` and `visual_concept` always.

### 8. `repurposer` (balanced; fan-out)
**Purpose:** transform a master piece into platform-native variants.
**Actions:** `adapt(content_id, target_platform, format)`.
**Tools:** `content.get`, `platform.rules`, `hashtags.suggest`, `content.create_variant`.
**Output:** `Variant{platform, format, text|segments[], hashtags[], media_plan, metadata, changes_made[]}`.
**Platform rules (examples enforced by `platform.rules` and by `validateContent()` later):** X ≤ 280 chars per post, threads as ordered segments with hooks; LinkedIn ~3,000 chars, no hashtag walls, line-break rhythm; Instagram caption ≤ 2,200 chars, hashtags separated, CTA "link in bio"; TikTok script with on-screen text + spoken lines + duration; YouTube title ≤ 100, description ≤ 5,000, chapters/keywords; Threads ≤ 500; Pinterest title ≤ 100, description ≤ 500; GBP post ≤ 1,500. (Exact limits are validated against the capability matrix, doc 26.)

### 9. `visual` (balanced)
**Purpose:** design visuals and video structure; orchestrate media generation.
**Actions:** `concept(content_id)`, `generate_image(content_id, concept, style)`, `carousel(content_id, slides)`, `video_script(content_id, duration, format)`.
**Tools:** `brand.get_visual_identity`, `media.generate_image` (SPEND class; thresholds), `media.edit`, `media.compose_carousel`, `media.transform_for_platform`, `media.attach`, `content.get`.
**Output:** `VisualPlan{concept, image_prompts[], negative_prompts[], layout, text_overlays[], brand_elements, alt_text, assets[media_asset_id]}`.
**Safety:** prompts pass a policy filter (no real persons, no trademarks of others, no medical/financial imagery claims); generated images are labeled `ai_generated=true` and alt text is mandatory.

### 10. `critic` (balanced; different model family than writer)
**Purpose:** score and critique content before humans see it.
**Actions:** `critique(content_id|variant_id)`.
**Tools:** `content.get`, `brand.get_context`, `platform.rules`, `policy.check` (deterministic: forbidden topics, banned words, hashtag limits, link counts, PII regexes, sensitive-topic classifier), `hashtags.validate`.
**Output:** `Critique{scores{quality, brand_fit, platform_fit, clarity, hook_strength, cta_strength, risk}, issues[{severity, kind, span, suggestion}], rewrite_suggestions[], policy_flags[], overall, recommend: approve|revise|reject}`.
**Rule:** the critic never edits; it proposes. Thresholds in `ai_settings.safety` decide whether content goes to `needs_review` or is flagged `high_risk` (approval required by admin/owner).

### 11. `fact_check` (balanced; untrusted inputs)
**Purpose:** verify factual claims against sources.
**Actions:** `check(content_id)`.
**Tools:** `claims.extract` (cheap-model tool), `research.read_source`, `web.search`, `web.fetch`, `factcheck.save`.
**Output:** `FactCheck{claims[{text, verdict: supported|contradicted|unverifiable|opinion, confidence, evidence[{source_id, quote}]}], overall_risk, requires_human: bool}`.
**Policy:** any `contradicted` claim blocks approval until edited; `unverifiable` in regulated domains (health, finance, legal) raises risk to `high`.

### 12. `performance_analyst` (powerful)
**Purpose:** find what works and recommend what to do next.
**Actions:** `analyze(brand_id, period, dimensions)`, `compare_periods`, `competitor_delta`.
**Tools:** `analytics.query` (normalized metrics), `stats.compare_groups` (effect sizes, confidence intervals, minimum-n guard), `stats.time_of_day`, `stats.trend`, `competitors.list_snapshots`, `insights.save`, `recommendations.save`.
**Output:** `Insights{insights[{statement, metric, effect, n, confidence, evidence_ids[]}], recommendations[{action, rationale, expected_impact, priority, links_to: pillar|format|time|topic}]}`.
**Discipline:** numbers come only from tools (the model is told it may not compute statistics itself); statements with n < 8 posts are labeled "early signal"; metric availability per platform is respected (missing ≠ zero).

### 13. `report` (balanced)
**Purpose:** compose readable reports from stored structured data.
**Actions:** `compose(kind, inputs, audience, length)`.
**Tools:** `reports.get_data` (deterministic data pack per kind), `reports.render` (markdown → HTML/PDF), `reports.save`.
**Output:** `Report{title, sections[{heading, markdown, charts[], sources[]}], summary, period}`.
**Kinds:** `weekly_performance`, `competitor`, `competitor_opportunities`, `campaign`, `research_brief`, `custom`.

## 6.4 Agent ↔ tool permission matrix (excerpt)

| Tool | research | social_listening | competitor_intel | trend | strategy | ideation | writer | repurposer | visual | critic | fact_check | perf_analyst | report |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| web.search / web.fetch | ✓ | | | ✓ | | | | | | | ✓ | | |
| social.* | | ✓ | | | | | | | | | | | |
| research.save_source | ✓ | ✓ | | | | | | | | | ✓ | | |
| content.create_draft | | | | | | | ✓ | | | | | | |
| content.create_variant | | | | | | | | ✓ | | | | | |
| media.generate_image (SPEND) | | | | | | | | | ✓ | | | | |
| analytics.query / stats.* | | | ✓ | ✓ | ✓ | | | | | | | ✓ | ✓ |
| publishing.propose_* (APPROVAL) | | | | | ✓ | | | | | | | ✓ | |
| memory.search | ✓ | | ✓ | | ✓ | ✓ | ✓ | | | | | ✓ | |

No agent has a tool that writes to a social platform. `publishing.propose_schedule` creates an approval; the deterministic SchedulingService executes it after a human approves.

## 6.5 Prompt management

- Prompts live in `prompt_templates` (agent_id, version, body, variables, model_hints, created_by, is_active) with Jinja-style variables; the repo ships defaults in `app/agents/prompts/*.md` loaded on first boot.
- Each `ai_calls` row stores `prompt_version` and `prompt_hash` so any output is reproducible.
- The AI Settings screen edits templates with version history and a "test with sample" button that runs the agent in `tool` mode on fixture inputs.

## 6.6 Evaluating agents without flaky tests

- **Schema tests:** every action output parses; required fields present.
- **Deterministic harness:** provider adapter replaced by `FakeProvider` with recorded responses (cassettes keyed by prompt hash) for unit tests.
- **Rubric evals** (nightly, optional): a small golden set per agent, graded by a judge model with a fixed rubric; thresholds tracked, not asserted in CI.
- **Invariant tests:** citations ⊆ tool results; no forbidden topics in output; platform limits honored; critic never same model as writer; injection corpus does not trigger tool calls.
