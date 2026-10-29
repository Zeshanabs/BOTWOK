# 09 — Content Architecture: Brand Intelligence, Strategy Engine, Generation, Repurposing

## 9.1 Brand Knowledge System

### 9.1.1 Data model
`brands`: `id, workspace_id, name, slug, description, industry, sub_industry, website, geography[], languages[], timezone, logo_asset_id, status, created_by`.

`brand_settings` (one row per brand, JSONB sections validated by Pydantic models so they can evolve without migrations):

| Section | Fields |
|---|---|
| `audience` | personas[{name, role, pains[], goals[], objections[], channels[]}], demographics, geography, b2b/b2c |
| `offering` | services[], products[{name, description, url, price_hint}], differentiators[], proof_points[] |
| `voice` | tone sliders (formal↔casual, serious↔playful, concise↔expansive, bold↔measured), style rules[], writing_samples[{text, note}], vocabulary{preferred[], avoid[]}, emoji_policy, humor_policy, person (we/I), reading_level |
| `policies` | forbidden_topics[], sensitive_topics[{topic, handling}], claims_policy (e.g. "no outcome guarantees"), legal_disclaimers[], compliance_tags[] (e.g. HIPAA-adjacent, financial) |
| `topics` | preferred_topics[], content_pillars (also normalized in `content_pillars`), keywords[], hashtags{core[], campaign[], banned[]}, ctas[{text, goal, url}] |
| `visual` | colors{primary, secondary, accent, neutral[]}, fonts{heading, body}, logo variants (asset ids), imagery style, do/don't, templates[] |
| `platforms` | per-platform defaults: formats, cadence, tone adjustments, hashtag count, link policy, signature |
| `goals` | objectives[{name, metric, target, by}], priority platforms, funnel stage focus |
| `competitors` | competitor ids (normalized in `competitors`) |

`content_pillars`: `id, brand_id, name, description, share_target (0–1), color, examples[], status`.
`brand_assets`: logos, templates, past-post exports (used by "Learn from my past posts").

### 9.1.2 BrandContext (what every agent receives)
`BrandService.build_context(brand_id, mode=compact|full)` renders a deterministic, cacheable block (~1.5k tokens compact / ~5k full):
```
BRAND: Acme Billing (healthcare revenue-cycle services, US, EN)
AUDIENCE: practice managers at 5–50 provider clinics; pains: denials, AR days…
VOICE: formal 70 / playful 20 / concise 80 / bold 40; we-voice; no emojis except ✅ in lists; reading level 9
RULES: never promise collection rates; cite sources for regulatory claims; avoid "cheap", "guarantee"
PILLARS: Educational 35% · Authority 20% · Industry News 20% · Case Study 15% · Behind the Scenes 10%
HASHTAGS core: #RevenueCycle #MedicalBilling … banned: #followme
CTAS: "Book a 15-min audit" (lead) · "Download the denial checklist" (nurture)
VISUAL: navy #0B2545, teal #13A89E; Inter; clean, documentary photography, no stock handshakes
PLATFORMS: linkedin 3/wk long-form; instagram 3/wk carousel/reel; x 5/wk threads; …
GOALS: +20% LinkedIn followers by Q1; 10 demo requests/mo
```
The prompt-cache prefix is this block, so repeated runs for the same brand are cheap. `full` mode adds writing samples and persona detail (used by `writer` and `strategy`).

### 9.1.3 How a brand gets filled
- Manual form (Brand Settings).
- **Import from website**: `research.crawl_site(website, 30 pages)` → cheap-LLM extraction of description, offerings, audience, tone candidates, CTAs, colors/fonts from CSS → user confirms each proposed field (nothing is saved without confirmation).
- **Learn from past posts**: after connecting accounts, pull the brand's own last 50–200 posts via official APIs (own-account data) → voice analysis → proposed tone sliders, vocabulary, top hashtags, pillars.
- **Learned preferences**: when users edit AI drafts, the diff is summarized into `memories(kind=preference)` ("prefers shorter hooks", "never uses 'leverage'").

## 9.2 Content Strategy Engine

Inputs: BrandContext (goals, audience, platforms), industry research (latest run), competitor analyses + gaps, trends (active), historical performance (insights/recommendations), capacity (posts/week the user can approve), calendar constraints (campaigns, holidays).

Process (`strategy.build_strategy`):
1. Evidence pack (deterministic): top insights by effect size, top competitor gaps, top trends by relevance, current pillar shares vs targets, cadence per platform, best times from `account_metrics`.
2. LLM reasoning (powerful) with the evidence hierarchy rule: own performance > competitor evidence > trends > priors.
3. Output `Strategy` (doc 06 §5) persisted to `memories(kind=strategy)` and surfaced as a versioned "Strategy" object on the brand (stored in `brand_settings.strategy` with `version`, `rationale`, `evidence_ids`).

Outputs: content pillars (with shares), themes, content ideas (handoff to `ideation`), campaigns (`campaigns` rows proposed, created on accept), posting recommendations (frequency per platform, best windows), platform strategy (formats and tone adjustments), recommended topics.

Default pillar vocabulary (seed list, editable): Educational, Authority, Promotional, Engagement, Storytelling, Industry News, Case Study, Behind the Scenes, User Generated Content, Thought Leadership.

Content-mix recommendation: start from the brand's targets; adjust by performance (pillars with engagement index > 1.2 gain share, < 0.8 lose share, max ±10 pts per cycle); never below 5% for a pillar tied to a goal; promotional capped (default 20%). The rule set is deterministic (`strategy.mix_adjust`) and the LLM explains it.

## 9.3 Content Generation Engine

### 9.3.1 Data model
- `content_ideas`: `brand_id, title, angle, pillar_id, content_type, formats[], platforms[], hooks jsonb, evidence (source ids, trend id, insight id), score, status (new|shortlisted|promoted|discarded), embedding`
- `content_items` (master): `brand_id, campaign_id?, idea_id?, title, content_type, pillar_id, master_format, status, body jsonb (hook, body_md, cta, hashtags[], keywords[], visual_concept, alt_text, notes), language, current_version, ai_generated bool, risk_level (low|medium|high), approval_required bool, created_by, assigned_to`
- `content_variants` (per platform/format): `content_item_id, platform, format, social_account_id?, text, segments jsonb (threads/carousel slides/script scenes), hashtags[], media_plan jsonb, platform_metadata jsonb (title, description, tags, privacy, first_comment, link, poll, location, collaborators…), status (mirrors item until scheduled), validation jsonb (adapter validateContent result), critique jsonb, factcheck jsonb, current_version`
- `content_versions`: immutable snapshots per item/variant edit: `target_type, target_id, version, snapshot jsonb, author (user|agent:writer), ai_call_id?, diff_summary`
- `content_sources`: `content_item_id, research_source_id, claim_text?, used_for (claim|inspiration|data)`
- `content_assets`: `variant_id|content_item_id, media_asset_id, role (primary|carousel_slide|thumbnail|cover), position, alt_text`

### 9.3.2 Generated item contract
Every generated item contains: hook · body · CTA · hashtags · keywords · visual concept · alt text · platform metadata · source references (claim-level) · AI generation metadata (`model, provider, prompt_version, temperature, ai_call_id, run_id, cost_usd`). Missing any of these fails schema validation and triggers a re-prompt.

### 9.3.3 Supported platforms × formats (generation side; publishing limits in doc 26)

| Format | instagram | facebook | linkedin | x | tiktok | youtube | threads | pinterest | gbp |
|---|---|---|---|---|---|---|---|---|---|
| text post | — (caption only) | ✓ | ✓ | ✓ | — | — | ✓ | — | ✓ |
| caption + image | ✓ | ✓ | ✓ | ✓ | — | — | ✓ | ✓ | ✓ |
| thread/segments | — | — | — | ✓ | — | — | ✓ (reply chain) | — | — |
| carousel | ✓ (≤10) | ✓ (multi-photo) | document PDF (carousel-like) · multi-image | ✓ (≤4 media) | photo post (≤35) | — | ✓ (2–20) | ✓ (2–5) | — |
| reel / short video | ✓ | ✓ (Reels) | video | video | ✓ | Shorts | video | video pin | — |
| long video | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| story | ✓ | ✓ (no API scheduling) | — | — | — | — | — | — | — |
| article/long-form | — | — | ✓ (article share) | — | — | description | — | — | — |
| poll | — | UNVERIFIED | ✓ | ✓ | — | — | ✓ | — | — |
| event/offer | — | — | — | — | — | — | — | — | ✓ |

Generation covers text posts, captions, threads, carousels, reels/short-video scripts, long-video outlines, stories, articles, polls, promotional/educational/announcement/case-study post types.

### 9.3.4 Generation flow in Studio
`POST /content/{id}/generate {mode: write|rewrite|shorten|expand|change_tone|regenerate, instructions, platform, format, sources[]}` → `AIService.create_run(mode=tool, agent=writer)` → draft saved as a new `content_versions` row and item status `ai_generated` → automatic `critic` pass (and `fact_check` when the draft contains claims or the brand has `compliance_tags`) → UI shows scores and verdicts → user edits (new version, `author=user`) → `needs_review` → approval.

## 9.4 Multi-platform repurposing

```
Master Content (content_items, master_format=article|post)
      │  POST /content/{id}/repurpose {targets:[{platform, format, account_id}]}
      ▼
RepurposePlan: for each target → repurposer.adapt(content_id, platform, format)   (fan-out, balanced model)
      │  each agent call receives: master body, brand context, platform.rules(platform, format), hashtags.suggest
      ▼
content_variants (one per target) + critic per variant + validateContent() per variant (adapter, deterministic)
      ▼
Studio navigator shows master + variants; each variant editable, schedulable independently
```
Targets available: LinkedIn post · Facebook post · Instagram caption (+carousel slides) · X post · X thread · TikTok script · YouTube title + description (+chapters, tags) · Carousel (slides JSON for the media composer) · Email (subject + body) · Blog idea (outline) · Threads post · Pinterest pin (title/description/board) · GBP post (summary + CTA).

Platform-rule engine (`app/content/platform_rules.py`): a declarative table (limits, hashtag norms, link behavior, hook conventions, media constraints, tone defaults) used both to **instruct** the repurposer and to **validate** results deterministically (character counts, segment counts, hashtag counts, forbidden characters, URL handling). Adapter `validateContent()` is the final authority at scheduling time; the rule engine prevents most rejects early.

Changes are recorded per variant (`changes_made[]`), so the user sees *why* the X version differs ("cut to 3 points; moved link to final post; replaced 'learn more' with question hook").
