# 33 — Risks & Future Improvements

## 33.1 Risks (with mitigations)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Platform API churn** (Meta versions every ~6 months, X pricing/policy changes, YouTube quota model changed twice in 2026) | High | High | Adapters pinned + `VERIFIED_AT` gate; capability probes; declarative specs; quarterly verification task; feature flags per capability |
| 2 | **App review / audit rejections** (Meta App Review, LinkedIn Community Management legal-entity requirement, TikTok rejecting internal tools, YouTube audit) | High | Medium–High | MVP on self-serve paths (LinkedIn member, X, Meta dev mode); plan reviews early (Phase 3); fallbacks (TikTok inbox upload, YouTube private uploads); clear UI messaging |
| 3 | **Competitor data expectations vs reality** (users expect LinkedIn/TikTok competitor analytics) | High | Medium | Availability classes everywhere; onboarding explains limits; invest in web/news/search-based intelligence and Instagram/YouTube/X where allowed |
| 4 | **Duplicate or lost publishes** | Low (with design) | Very high | Transactional queue, locks, CAS, resume, reconciliation, unique indexes, late-tolerance hold; publishing test suite covers every error class |
| 5 | **Prompt injection via research content** | Medium | High | Untrusted wrapping, allowlisted tools for reading agents, no side effects without approval, canary, classifier, evals |
| 6 | **AI cost blowups** (loops, deep research, media) | Medium | Medium | Budgets per run/day/month, pre-call estimates, turn/tool caps, caching/dedupe, cheap-tier routing, spend confirmations |
| 7 | **Hallucinated or non-compliant content in regulated industries** | Medium | High | Fact-check agent, claim-level sources, risk routing, admin approval for high risk, never auto-publish, brand policies |
| 8 | **Local-first constraints** (public media URLs for IG/Threads/TikTok/GBP, HTTPS OAuth callbacks) | High | Medium | `MediaPublicURLService` + tunnel; bytes-upload platforms unaffected; clear setup docs; VPS path removes the issue |
| 9 | **LinkedIn 60-day tokens without refresh** | Certain | Medium | Expiry notifications 7 days ahead; block scheduling beyond expiry; one-click reconnect |
| 10 | **X pay-per-use costs** (URL posts $0.20; reads $0.005) | Certain | Low–Medium | Per-post cost display; monthly budgets; warn on URLs; competitor reads throttled |
| 11 | **Solo-developer scope creep** | High | High | Strict MVP; phases; P0–P3 matrix; "deterministic over LLM" rule reduces surface area |
| 12 | **Vendor lock-in to one AI provider** | Low | Medium | Ports/adapters; two adapters cover most models; evals run across providers |
| 13 | **Postgres as queue at higher scale** | Low (V1–V2) | Low | `JobQueue` port; swap to Dramatiq/Redis if > ~50 jobs/s |
| 14 | **Security of stored tokens on a laptop** | Medium | High | Envelope encryption with a master key outside the DB; OS keychain integration (V2); disk encryption recommended in docs |
| 15 | **Data-retention policy breaches** (LinkedIn 24/48 h, YouTube 30 d) | Medium | Medium | Retention job per platform; tests; audit |
| 16 | **Model quality drift** after provider updates | Medium | Medium | Pinned model ids; nightly evals; prompt versioning; replay |
| 17 | **Platform spam/automation policy violations** | Low | High | Human approval default; posting caps; no engagement automation; duplicate blocking |

## 33.2 Open questions tracked for verification (`docs/platforms/open-questions.md`)
Facebook `attached_media` multi-photo parameter; Facebook alt text and polls; Facebook Stories max video length (60 vs 90 s); Instagram `follower_count`/`online_followers` metrics; Threads Business Verification requirement; LinkedIn text max length and approval turnaround; X refresh-token lifetime and self-reply thread exemption; Pinterest video specs; GBP post length/media count and OAuth verification for `business.manage`; YouTube scope sensitivity classification and `batchGetStats` id limit; TikTok inbox upload for non-private accounts without audit; TikTok Business API photo/scheduling/delete.

## 33.3 Future improvements
- **Strategy auto-tuning**: closed-loop mix adjustment with guardrails and A/B variants (hook A vs B on X/Threads).
- **Comment & mention workflows**: monitoring via official APIs (Meta, Threads, YouTube, LinkedIn org), AI-drafted replies with approval, sentiment trends.
- **Native scheduling hand-off** toggles (Facebook, YouTube, GBP).
- **Video pipeline** maturity: scripted videos with brand templates, auto-captions, platform renditions; generated B-roll providers.
- **Local-first privacy mode**: all tiers local (when hardware allows), encrypted at-rest DB, OS keychain for master key.
- **Durable workflows on Temporal** behind the `WorkflowRunner` port when automations grow.
- **Collaboration**: comments on content, @mentions, presence, CRDT co-editing.
- **Agency features**: multi-workspace admin, client approval portals, white-label reports.
- **Ads bridge**: boost best organic posts via Meta/LinkedIn ads APIs (separate approvals).
- **Listening expansion**: Reddit/forums via licensed APIs, podcast/YouTube transcript research, newsletter ingestion.
- **Brand-voice fine-tuning** or style adapters trained on approved content (opt-in, local).
- **Marketplace** of workflow and prompt templates; import/export of brand kits.
