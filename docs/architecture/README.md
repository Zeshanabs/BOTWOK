# Botwok — Architecture Package

A complete, implementable architecture for a local-first AI social media automation operating system. Start with `00-canonical-vocabulary.md` (names every document obeys) and `01-executive-summary.md`.

## Required output sections → files

| # | Required section | File |
|---|---|---|
| 1 | Executive Summary | `01-executive-summary.md` |
| 2 | Product Definition | `02-product-definition-and-feature-matrix.md` §2.1–2.4 |
| 3 | Feature Matrix (P0–P3) | `02-product-definition-and-feature-matrix.md` §2.5 |
| 4 | Recommended Technology Stack (+ ADRs) | `03-technology-stack-and-adrs.md` |
| 5 | System Architecture (full diagram) | `04-system-architecture.md` |
| 6 | AI Architecture (orchestrator) | `05-ai-orchestrator.md` |
| 7 | Agent Architecture | `06-agents.md` |
| 8 | Research Architecture | `07-research-engine.md` |
| 9 | Competitor Architecture | `08-competitor-intelligence.md` |
| 10 | Content Architecture (brand, strategy, generation, repurposing) | `09-brand-strategy-content.md` |
| 11 | Media Architecture | `10-media-architecture.md` |
| 12 | Publishing Architecture | `11-publishing-architecture.md` |
| 13 | Scheduling Architecture | `12-scheduling-architecture.md` |
| 14 | Analytics Architecture (+ AI performance analysis) | `13-analytics-and-performance.md` |
| 15 | Automation Architecture | `14-automation-engine.md` |
| 16 | Database Architecture (DDL + ER) | `16-database-schema.md` (memory/storage map in `15-memory-and-storage.md`) |
| 17 | API Architecture | `17-api-architecture.md` (+ route catalog in `00` §14) |
| 18 | Event Architecture | `18-event-architecture.md` |
| 19 | Security Architecture (+ AI safety / risk control) | `19-security-architecture.md` |
| 20 | Local Development Architecture | `21-local-dev-docker-and-local-ai.md` |
| 21 | Docker Architecture | `21-local-dev-docker-and-local-ai.md` §21.1–21.3 |
| 22 | Complete Repository Structure | `22-repository-structure.md` |
| 23 | UI/UX Architecture (design system, command center) | `23-ui-ux-design-system.md` |
| 24 | Every Screen Wireframe (24 screens) | `24-wireframes.md` |
| 25 | User Flows (A–Q) | `25-user-flows.md` |
| 26 | Platform Capability Matrix | `26-platform-capability-matrix.md` |
| 27 | API Integration Strategy (per platform) | `27-api-integration-strategy.md` |
| 28 | Failure Handling | `28-failure-handling.md` |
| 29 | Testing Strategy | `29-testing-strategy.md` |
| 30–33 | MVP, V1, V2, V3 | `30-roadmap-mvp-and-phases.md` §30.1 |
| 34 | Development Roadmap (Phases 0–13) | `30-roadmap-mvp-and-phases.md` §30.2 |
| 35 | Build Order | `30-roadmap-mvp-and-phases.md` §30.3 and `32-build-blueprint.md` |
| 36 | Risks | `33-risks-and-future.md` §33.1 |
| 37 | Future Improvements | `33-risks-and-future.md` §33.3 |
| — | Sample end-to-end scenarios (brief §45–47) | `31-end-to-end-scenarios.md` |
| — | Observability & cost control (brief §30–31) | `20-observability-and-cost.md` |
| — | AI memory (brief §20) | `15-memory-and-storage.md` |
| — | Local AI option (brief §34) | `21-local-dev-docker-and-local-ai.md` §21.4 |
| — | THE EXACT BUILD BLUEPRINT (brief §55) | `32-build-blueprint.md` |

## Supporting material
- `../platforms/meta-facebook-instagram-threads.md`, `../platforms/linkedin-x-pinterest-gbp.md`, `../platforms/tiktok-youtube.md` — verified platform research (2026-10-08) with source URLs.
- `../platforms/open-questions.md` — facts that must be verified before enabling a feature.

## Stated assumptions
- Product name "Botwok" (from the repository folder); rename freely.
- One developer, Python/FastAPI proficiency, AI-assisted coding; estimates in doc 30 reflect that.
- Cloud AI APIs first; local models via the same provider abstraction.
- Default policy: AI-generated content always requires human approval; autonomous publishing is opt-in per workflow in V2.
- Platform facts are dated; the capability matrix must be re-verified every release.
