# 15 — AI Memory & Storage Architecture

## 15.1 Memory types → where they live

| Memory | Content | Primary store | Vector? | Written by | Read by |
|---|---|---|---|---|---|
| 1. Brand memory | brand profile, voice, pillars, policies, visual identity, strategy versions | Postgres (`brands`, `brand_settings`, `content_pillars`) | no (structured) | user, import flows, strategy agent (versions) | every agent via `BrandContext` |
| 2. User preferences | editing preferences learned from diffs, approval defaults, timezone, favorite formats | Postgres (`memories kind=preference`, `users.preferences`) | yes (small; semantic lookup of preference notes) | diff summarizer, explicit "remember" | ContextBuilder |
| 3. Conversation memory | messages, rolling summaries per conversation | Postgres (`ai_conversations`, `ai_messages`) | summaries embedded for recall across conversations | AIService | ContextBuilder |
| 4. Research memory | sources, documents, chunks, run findings | Postgres (`research_*`) + MinIO (full text) | **yes** (`research_chunks.embedding`) | ResearchService | research, fact_check, ideation, writer |
| 5. Competitor memory | profiles, posts, snapshots, analyses | Postgres (`competitor_*`) | yes (`competitor_posts.embedding` for gap clustering) | CompetitorService | competitor_intel, strategy |
| 6. Content memory | items, variants, versions, critiques, what was approved/rejected and why | Postgres (`content_*`) | yes (`content_items.embedding` for dedupe/similar) | ContentService | ideation (dedupe), writer (style continuity), repurposer |
| 7. Performance memory | normalized metrics, insights, recommendations, accepted/rejected | Postgres (`post_metrics`, `insights`, `recommendations`) | insights embedded (`memories kind=performance`) | AnalyticsSync, InsightService | performance_analyst, strategy, ideation |
| 8. Strategy memory | strategy versions, rationale, accepted mixes | Postgres (`brand_settings.strategy`, `memories kind=strategy`) | yes (rationale text) | strategy agent on accept | strategy, planner |

Rule: **structured facts live in relational tables; vectors exist only for things that need semantic recall** (chunks of text, past ideas, insight statements, preference notes). Nothing is stored *only* as a vector.

## 15.2 `memories` table
`id, workspace_id, brand_id?, user_id?, kind (preference|performance|strategy|conversation_summary|note), text, embedding vector(dims), embedding_model, importance (0–1), source_ref jsonb (run id, insight id…), expires_at?, created_at, last_used_at, use_count`.
Retrieval: `MemoryService.search(query, kinds, k=8, brand_id)` → cosine via pgvector HNSW filtered by workspace/brand/kind; results re-ranked by `0.7*similarity + 0.2*importance + 0.1*recency`. Written memories are deduped (similarity > 0.92 → merge, bump importance). Forgetting: `expires_at` for conversation summaries (90 days), unused preferences decay after 180 days of no use.

## 15.3 Storage map

**PostgreSQL** — all relational data (doc 16), JSONB for flexible sections, pgvector embeddings (`research_chunks`, `content_items`, `content_ideas`, `competitor_posts`, `memories`), Procrastinate job tables, outbox, audit log. One database, schemas: `public` (app), `procrastinate`.

**pgvector specifics** — HNSW indexes (`m=16, ef_construction=64`), `vector_cosine_ops`; each table records `embedding_model`; a migration job re-embeds when the model changes; dimension is fixed per table version (1536 for cloud small models, 768 for nomic) — tables created with the configured dimension at setup; switching dimension = new column + backfill.

**Redis** — API rate-limit counters, platform rate-limit token buckets, SSE pub/sub channels (`ws:{workspace_id}`), run cancel flags, short-lived caches (BrandContext render 10 min, capability probes 1 h, search results 24 h keyed by normalized query+provider, LLM response cache keyed by prompt hash for deterministic tool calls), distributed locks for OAuth state and connect flows. Nothing in Redis is a source of truth; losing it causes at most cache misses and a reconnect of SSE clients.

**MinIO (S3)** — buckets: `media` (originals, renditions, generated), `documents` (research full text, PDFs), `reports` (rendered HTML/PDF), `exports` (workspace exports), `tmp` (chunked uploads, lifecycle 1 day). Keys: `{workspace_id}/{kind}/{yyyy}/{mm}/{uuid}.{ext}`. Presigned URLs for browser upload/download; public renditions only through `MediaPublicURLService`.

**Local filesystem** — none in production paths (only FFmpeg scratch in the worker container's tmpfs).

## 15.4 Caching strategy (cost control hooks)
- Research fetch reuse: canonical URL fetched < 24 h → reuse document.
- Search cache: 24 h per normalized query/provider (configurable; `news` 1 h).
- LLM cache: identical prompt hash + temperature 0 → cached result (7 days) for extraction/classification tools.
- Prompt caching at the provider: stable prefix (system + BrandContext).
- Analytics snapshots precomputed per period; dashboards never aggregate raw rows at request time beyond 90 days.

## 15.5 Retention defaults (configurable per workspace)
Raw platform payloads 30 d · research documents without links 180 d · YouTube other-channel stats 30 d (policy) · competitor posts 365 d · ai_calls prompts/responses 90 d (metadata kept forever) · audit logs forever · notifications 180 d · exports 7 d.
