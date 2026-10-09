# 02 — Product Definition & Feature Matrix

## 2.1 What Botwok is
A **local-first AI social media operating system**: a single application (Docker on a laptop today, a VPS later) that acts as an AI social media manager for one or more brands. It researches the web and licensed social sources, watches competitors within what platforms allow, detects trends, builds content strategy, writes and adapts content per platform, generates visuals, schedules and publishes through official APIs with human approval, collects analytics, learns from performance, and recommends what to do next. Autonomous workflows are possible, but every externally visible action passes through policy checks and human approval gates by default.

## 2.2 What it is not
- Not a scheduler with a chat box: research, strategy, generation, and learning are first-class.
- Not a scraper: no logged-in surfaces, no API circumvention; unavailable data is labeled as such.
- Not a single giant agent: 13 narrow agents orchestrated by a planner with ledgers and gates.
- Not cloud-dependent: runs fully locally; cloud AI/search are pluggable providers, local models are supported.

## 2.3 Users and jobs-to-be-done
- **Solo founder / consultant** (MVP persona): "Keep my LinkedIn and X active with credible, on-brand posts without spending my evenings."
- **In-house marketer** (V1): "Plan a month, get approvals, publish everywhere, and show what worked."
- **Agency account manager** (V2): "Run 10 brands with competitor reports and automations, with client approvals."
- **Approver** (role): "See exactly what will go out, why, and the evidence, then approve in one click."

## 2.4 Core capabilities (from the vision)
Research · Competitor intelligence · Trend detection · Audience insights · Content strategy · Idea generation · Writing · SEO/hashtags · Visuals (images, carousels, video scripts) · Repurposing · Critique & fact-check · Calendar · Approval · Scheduling · Publishing · Analytics · Performance analysis & recommendations · Automations · Reports · Command Center with full transparency.

## 2.5 Feature matrix (P0 = MVP required · P1 = V1 · P2 = V2 · P3 = V3/Future)

| Area | Feature | Priority |
|---|---|---|
| Identity | Email/password auth, sessions, RBAC (5 roles), workspace isolation (RLS), audit log | P0 |
| Identity | Invitations, team page, API keys | P1 |
| Identity | OIDC login, TOTP 2FA, brand-level permissions | P2 |
| Brand | Brand profile, voice, policies, pillars, hashtags/CTAs, visual identity, goals; BrandContext | P0 |
| Brand | Import from website; learn from past posts; learned preferences | P1 |
| Social | Connect LinkedIn (member), X, Facebook Page, Instagram (Facebook Login), YouTube; token vault; health probes | P0 (LinkedIn+X), P1 (rest) |
| Social | Threads, LinkedIn organization, Instagram Login flavor | P1 |
| Social | TikTok (inbox/direct), Pinterest, GBP | P2 |
| Research | Web/news search, extraction, dedupe, credibility, citations, history, RSS | P0 |
| Research | Site crawling, keyword research, PDF, Playwright render, hosted extractors | P1 |
| Research | Licensed social listening (X search, IG hashtags, YouTube search, Threads search) | P2 |
| Competitors | Profiles with availability classes, website/blog/news collection, IG Business Discovery, YouTube stats, X timelines, LinkedIn follower count | P1 |
| Competitors | Analysis (pillars, hooks, tone, cadence), comparison, gap detection, reports | P1 |
| Competitors | Monitoring automation + alerts | P2 |
| Trends | Signal ingestion, scoring, labeled trends, "create ideas from trend" | P2 |
| Strategy | Pillar/mix recommendations, platform strategy, calendar plan | P2 (manual pillars P0) |
| Ideas | Manual ideas; AI ideation with dedupe; promote to Studio | P0 |
| Content | Items/variants/versions/sources; statuses; platform rules & validation | P0 |
| Content | Writer, critic, fact-check agents; generation metadata; risk routing | P0 |
| Content | Repurposing to LinkedIn/X/Instagram/Facebook/Threads/YouTube/TikTok script/email/blog idea | P0 (LinkedIn/X/IG), P1 (rest) |
| Media | Upload, validation, transforms, platform renditions, alt text | P0 |
| Media | AI image generation, carousel composer, background removal | P1 |
| Media | Video pipeline (scripted/generated), subtitles, TTS | P3 |
| Studio | Editor, AI panel, sources, critic, approval, schedule, previews, versions | P0 (minimal), P1 (full) |
| Calendar | Month/week/day/list/board, filters, DnD, tray | P1 |
| Approvals | Inbox, approve/reject/request changes, policies (AI content requires approval) | P0 |
| Scheduling | Publish now / at time | P0 |
| Scheduling | Reliable scheduler, retries, pause/resume/cancel, dead-letter, best-time, recurring | P1 |
| Publishing | LinkedIn member + X with exactly-once semantics | P0 |
| Publishing | Instagram, Facebook, Threads, LinkedIn org, YouTube; delete; reconciliation; webhooks | P1 |
| Publishing | TikTok, Pinterest, GBP; native scheduling hand-off | P2 |
| Analytics | Sync, normalized metrics with availability, dashboards, breakdowns, snapshots | P1 |
| Insights | Performance analyst, insights/recommendations, learning loop, weekly report | P1 |
| Reports | Competitor and performance reports, export, email/Slack delivery | P1 |
| Automation | Workflow builder, triggers, node catalog, runs, templates | P2 |
| AI platform | Provider abstraction (Anthropic + OpenAI-compatible), routing tiers, budgets, cost tracking, prompt versioning | P0 |
| AI platform | Google provider, local models UI, economy mode, cost dashboard | P1 |
| AI platform | Multi-agent planner, approval gates for proposed actions, memory (8 types), conversation memory | P2 (tool mode P0) |
| Command Center | Single-agent runs with step timeline, sources, cost | P0 |
| Command Center | Full plan checklist, reasoning, content, actions panels, history | P2 |
| Security | Token encryption, SSRF guard, CSRF, rate limits, input validation, injection defenses, audit | P0 |
| Security | Media scanning (ClamAV), outbound webhook signing, data-retention jobs | P1 |
| Observability | Structured logs, health, run ledger UI | P0 |
| Observability | Metrics, tracing, admin dashboards, alerts | P1 |
| Deployment | Docker Compose local | P0 |
| Deployment | VPS profile (Caddy, backups, monitoring) | P1 |
| Deployment | Multi-node/managed services, Temporal option | P3 |

## 2.6 Success criteria
- MVP: a solo user produces 10 approved, cited posts/week and publishes to LinkedIn + X with zero duplicate publishes over 30 days.
- V1: ≥ 6 platforms publishing; analytics coverage ≥ 90% of published posts; weekly insights with n-labeled statements; AI spend ≤ $20/month for a solo brand on default routing.
- V2: automations run unattended for a week with all side effects gated; Command Center completes multi-step requests with visible plan/sources/actions.
