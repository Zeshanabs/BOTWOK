# 07 — Research Architecture

## 7.1 Scope

The research engine turns a question into **saved, ranked, deduplicated, cited sources** plus a synthesis. It serves the `research`, `social_listening`, `trend`, `competitor_intel`, and `fact_check` agents, and the Research screen. It is the only component that fetches arbitrary web content, so it is also the primary **untrusted-input boundary**.

Capabilities: web search · news search · webpage extraction · bounded website crawling · RSS · public social content (via licensed APIs only; see doc 26) · X search (via X API recent search or xAI Live Search, both paid) · competitor website research · industry/topic/keyword research · trend discovery (signals handed to `trend`) · source ranking · duplicate removal · credibility scoring · citations · research history.

## 7.2 Pipeline

```
ResearchRequest {query, scope[], depth, recency_days, domains_allow[], domains_deny[], brand_id, competitor_id?}
      │
      ▼
① Query planning (LLM, cheap)            → 2–6 query variants per scope (web/news/rss/site:)
      │
      ▼
② Search fan-out (SearchProvider port)    → SearchHit{url, title, snippet, published_at?, provider, rank}
      │   providers: Tavily | Brave | Exa | SearXNG | xAI Live Search (X/news) | RSS reader | site crawler
      ▼
③ URL normalization + pre-dedupe          → canonical URL (strip utm/fbclid, lowercase host, drop fragments), skip deny-list, skip known-bad hosts
      │
      ▼
④ Fetch (ResilientClient, SSRF guard)     → raw HTML/PDF/text, status, final_url, headers, content_type, size cap 5 MB, 15 s timeout
      │   per-host concurrency 2, per-host rate 1 req/s, robots.txt honored for crawling, UA identifies Botwok
      ▼
⑤ Extract (ExtractorProvider)             → Document{title, author?, published_at?, text, language, links[], images[], meta}
      │   trafilatura → readability fallback → PDF via pypdf/pdfminer → optional Playwright render (flagged)
      ▼
⑥ Content hashing + exact/near dedupe     → sha256(normalized_text) exact; SimHash/MinHash (64-bit, Hamming ≤ 3) near-dup; canonical <link rel=canonical>
      │
      ▼
⑦ Enrichment (cheap LLM + deterministic)  → summary (≤120 words), keywords[], topics[], entities[], claims[] (for fact_check), language, content_kind (article|press|blog|forum|product|doc)
      │
      ▼
⑧ Scoring                                 → relevance (embedding sim to query + brand pillars, keyword overlap, recency), credibility (see 7.4)
      │
      ▼
⑨ Persist                                 → research_sources (one per canonical URL per workspace), research_documents (full text in MinIO + metadata),
      │                                       research_chunks (chunked text + embeddings), research_runs ↔ sources link with per-run rank
      ▼
⑩ Synthesis (research agent)              → findings with citations → stored on research_runs.result; RESEARCH_COMPLETED
```

Depth presets: `quick` (1 variant/scope, top 8 hits, no crawl), `standard` (3 variants, top 20, crawl competitor sites 1 level), `deep` (6 variants, top 50, crawl 2 levels, PDF allowed, Playwright allowed).

## 7.3 Stored record (what every source carries)

`research_sources`: `id`, `workspace_id`, `canonical_url`, `final_url`, `domain`, `title`, `source_kind` (web|news|rss|social|competitor_site|pdf|user_provided), `platform?` (for social), `author`, `published_at`, `retrieved_at`, `language`, `summary`, `keywords[]`, `topics[]`, `entities jsonb`, `relevance_score` (0–1, per-run copy stored on the link table), `credibility_score` (0–1), `citation` (pre-formatted "Author. Title. Domain, date. URL"), `content_hash` (sha256), `simhash` (bigint), `content_object_key` (MinIO), `word_count`, `trust` (always `untrusted` for fetched content; `trusted` only for user-provided notes), `fetch_status`, `error`.

`research_documents`: extracted text + structural metadata; `research_chunks`: ~400-token chunks with `embedding vector(1536)` (dimension per embedding model; model id stored), `chunk_index`, `section`.

`research_runs`: `query`, `scope[]`, `depth`, `params jsonb`, `status`, `ai_run_id?`, `result jsonb` (findings, gaps, topics), `source_count`, `cost_usd`, `started_at`, `completed_at`.

## 7.4 Credibility scoring (deterministic, explainable)

```
credibility = clamp( 0.35*domain_prior + 0.15*author_present + 0.15*date_present
                   + 0.15*corroboration + 0.10*https_and_no_spam_signals + 0.10*content_quality , 0, 1)
```
- `domain_prior`: maintained table `domain_reputation` (seeded: gov/edu/major outlets/official vendor docs high; content farms low; user can pin per workspace).
- `corroboration`: fraction of the run's other sources sharing ≥2 named entities/claims.
- `content_quality`: length ≥ 300 words, low ad/boilerplate ratio (from extractor), readable structure.
Scores and their components are stored so the UI can explain "why 0.82".

## 7.5 Ranking & dedupe

Final rank per run: `0.55*relevance + 0.30*credibility + 0.15*recency_decay` with per-domain diversity (max 3 per domain in top 20). Dedupe: exact hash → drop; near-dup → keep highest credibility, link the others as `duplicates_of`. Cross-run reuse: if a canonical URL was fetched < 24 h ago, reuse the stored document (no refetch) and only re-score relevance for the new query; this is the main cost saver.

## 7.6 Source families and legality

| Family | Method | Allowed? |
|---|---|---|
| Open web pages | search → fetch → extract, robots.txt honored for crawling, no login walls | Yes |
| News | news-capable search provider, RSS feeds, publisher sitemaps | Yes |
| RSS | `rss_feeds` table (user-added + auto-discovered from competitor sites), polled hourly | Yes |
| Competitor websites/blogs | bounded crawl (≤ 200 pages, 2 levels, change detection via content hash) | Yes (robots respected) |
| X public posts | X API v2 recent/full-archive search (pay-per-use), or xAI Live Search | Yes, licensed, metered |
| Instagram competitor data | Business Discovery + Hashtag Search via Facebook Login path only | Yes, limited fields and quotas |
| Threads public data | keyword search + profile lookup (needs Meta approval for non-own data) | Yes once approved |
| YouTube public data | Data API search/videos/channels statistics (quota units) | Yes |
| LinkedIn competitor posts | not available via API | **No** (only org follower count) |
| TikTok competitor data | Research API is academic-only; Display API is own-account only | **No** for commercial tools |
| Facebook other Pages | Page Public Content Access (App Review + Business Verification) | Only after approval |
| Pinterest other accounts | not available | **No** |
| Scraping logged-in or API-gated social surfaces | — | **Never** |

Where a family is unavailable the research result records `availability[{platform, status, reason}]` so the UI and agents say "not collected (platform restriction)" instead of guessing.

## 7.7 Keyword & topic research

- `keywords` table: term, workspace, source (user|discovered|competitor|trend), volume_hint (from provider if available, else null), related[], first_seen, last_seen, frequency over time (from sources/chunks).
- Topic clustering: embeddings of source summaries → HDBSCAN/agglomerative per run → cheap-LLM labels; cluster ids are stored on sources (`topics[]`).
- Keyword providers are pluggable (`KeywordProvider`: none by default; optional DataForSEO/Semrush adapters later). Without a provider, "volume" is shown as "relative frequency in collected sources", clearly labeled.

## 7.8 Research history & reuse

Research screen lists runs with query, scope, depth, source count, cost, status, and lets users re-run, extend (`deep`), or pin sources to the brand. Sources are workspace-global (shared across runs/brands) and can be attached to content (`content_sources`) and competitors (`competitor_id` on the link). Retention: documents older than 180 days with no links are pruned (configurable); metadata rows are kept.

## 7.9 Untrusted content handling (summary; full detail in doc 19)

Fetched text is stored with `trust=untrusted`; prompts wrap it in `<untrusted>` blocks; the extraction step strips scripts/hidden text/zero-width characters; an injection classifier flags documents with instruction-like patterns (`ignore previous`, `you are`, `send`, `curl`, base64 blobs) and those are shown with a warning badge and excluded from automation runs unless a human includes them.
