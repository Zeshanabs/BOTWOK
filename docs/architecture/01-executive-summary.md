# 01 — Executive Summary

## What we are building
**Botwok** is a local-first, production-grade AI Social Media Automation Operating System: an application that behaves like an AI social media manager. It researches the web and licensed social sources with citations, builds competitor intelligence from lawfully available data, detects trends, derives a content strategy from brand goals and real performance, writes and adapts content per platform, generates visuals, schedules and publishes through official APIs, collects and normalizes analytics, learns from results, and recommends the next content. It runs on a developer laptop with Docker today and deploys unchanged to a VPS later.

## The five decisions that shape everything
1. **Modular monolith, three process types.** One Python/FastAPI codebase runs as `api`, `worker`, and `scheduler`; a Next.js frontend talks to it through a same-origin proxy. PostgreSQL (+pgvector) is the single source of truth; Redis handles cache/rate limits/realtime; MinIO holds media. No microservices, no Kafka, no dedicated vector database.
2. **Thirteen narrow agents, one orchestrator, deterministic everything else.** Research, social listening, competitor intelligence, trend, strategy, ideation, writer, repurposer, visual, critic, fact-check, performance analyst, and report agents each have their own prompt, tool allowlist, model tier, and evals. Publishing, analytics sync, and automation are deterministic services. The orchestrator turns a request into a validated plan (a DAG), executes it with budgets and a full ledger, streams progress, and pauses at approval gates. **No LLM ever calls a platform write API.**
3. **Exactly-once publishing by construction.** A Postgres-backed queue (Procrastinate) makes "mark post queued" and "enqueue publish job" one transaction; a queueing lock allows one job per post; workers use compare-and-set transitions, persist intermediate platform ids so retries resume, and reconcile with the platform before retrying any ambiguous failure. A partial unique index forbids two live schedules of the same variant to the same account.
4. **Provider independence through ports.** AI, embeddings, image/video/speech, search, extraction, social platforms, storage, queue, and vector store are all protocols with adapters. Two AI adapters (Anthropic and OpenAI-compatible) cover cloud and local models (Ollama/vLLM) alike; switching models is configuration.
5. **Untrusted by default, human in the loop by default.** Every fetched page and social post is untrusted input: sanitized, classified for injection, isolated in prompts, and readable only by agents that have no side-effect tools. AI-generated content always lands in review; publishing requires approval; high-risk content requires an admin; budgets cap spend.

## Honest platform position (verified against official docs, 2026-10-08)
- Publishing works via official APIs for Facebook, Instagram (Professional accounts), Threads, LinkedIn (member self-serve; organization after approval), X (pay-per-use since Feb 2026; URL posts cost $0.20; quote posts Enterprise-only), YouTube (uploads private until audit), Pinterest (private in Trial), TikTok (direct posting requires an audit that explicitly excludes internal team tools; inbox-upload is the fallback), and Google Business Profile (access form; native scheduling).
- Only Facebook, YouTube, and GBP offer native scheduling; Botwok schedules everything itself for uniform behavior.
- Competitor analytics are **not** generally available: Instagram Business Discovery (via Facebook Login), YouTube public stats (30-day storage rule), X (metered), and Threads (after approval) are the lawful sources; LinkedIn, TikTok, Pinterest, and Facebook Pages (without Page Public Content Access) are not. The product labels every data point with its availability class and never scrapes.

## Build plan
- **MVP (Phases 0–7, ~8–10 weeks solo):** brand → cited research → AI drafts with critique and fact-check → Studio → human approval → publish to LinkedIn and X.
- **V1 (Phases 8–10, +6–8 weeks):** calendar and reliable scheduler, six publishing platforms, normalized analytics, AI performance insights, competitor dashboards, media generation, cost dashboard, VPS deployable.
- **V2 (Phases 11–12):** automation engine with a visual builder, multi-agent Command Center with approval gates, trends and social listening, TikTok/Pinterest/GBP, local AI routing.
- **V3+:** strategy auto-tuning, video pipeline, comment workflows, agency features.

## How to read this package
Doc 00 is the canonical vocabulary every other document obeys. Docs 03–23 are the architecture; 24–25 the screens and flows; 26–27 the platform truth; 28–29 failure handling and testing; 30–33 the roadmap, scenarios, build blueprint, and risks. `docs/platforms/` holds the raw verified research with source URLs and the open-questions register.
