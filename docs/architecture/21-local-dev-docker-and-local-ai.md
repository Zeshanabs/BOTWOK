# 21 — Local Development, Docker & Local AI

## 21.1 Docker Compose topology

```
docker-compose.yml
services:
  frontend    next dev (3000)          → depends_on api
  api         uvicorn --reload (8000)  → depends_on postgres redis minio
  worker      procrastinate worker --queues ai,research,publishing,analytics,media,automation,notifications,maintenance
  scheduler   python -m app.workers.scheduler
  postgres    pgvector/pgvector:pg16 (5432)      volume pgdata
  redis       redis:7-alpine (6379)             volume redisdata
  minio       minio/minio (9000 api, 9001 console) volume miniodata ; minio-init creates buckets
  mailpit     (optional) SMTP sink for email notifications (8025 UI)
  searxng     (optional, profile=local-search) self-hosted meta-search (8080)
  playwright  (optional, profile=render) browser render service (3001)
  ollama      NOT in compose by default; runs on the host for GPU/Metal access; reached via host.docker.internal:11434
networks:
  internal    (postgres, redis, minio, api, worker, scheduler, frontend)
  egress      (api, worker, playwright, searxng) — the only network with internet access
```
Networking: containers resolve each other by service name on `internal`; the frontend proxies browser requests to `http://api:8000`; workers never accept inbound connections; `playwright` and `searxng` have no route to `postgres`. OAuth callbacks hit `http://localhost:3000/api/v1/social/callback/{platform}` (proxied), or an HTTPS tunnel URL set in `PUBLIC_BASE_URL` for platforms that require HTTPS redirect URIs (Meta, TikTok, LinkedIn require HTTPS; localhost http is accepted by some only in dev mode, verify per platform).

```
Frontend ──► Backend (api) ──► Postgres / Redis / MinIO
                 │
                 └─ enqueue ──► Workers ──► External APIs (AI, search, social) + Postgres/Redis/MinIO
Scheduler ──► Postgres (due rows) ──► enqueue ──► Workers
```

## 21.2 Developer workflow
```
make setup        # copies .env.example → .env, generates BOTWOK_MASTER_KEY, pulls images
make up           # docker compose up -d (infra) ; api/worker/frontend can also run natively for faster reload
make migrate      # alembic upgrade head
make seed         # agents registry, prompts, demo workspace
make dev          # runs api + worker + scheduler + frontend natively with hot reload (uv run / pnpm dev)
make test         # pytest (testcontainers Postgres) + vitest
make e2e          # playwright against compose stack
make tunnel       # cloudflared tunnel → sets PUBLIC_BASE_URL and PUBLIC_MEDIA_BASE_URL for OAuth + media URLs
```
`.env.example` documents every variable: `DATABASE_URL, REDIS_URL, S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY, BOTWOK_MASTER_KEY, PUBLIC_BASE_URL, PUBLIC_MEDIA_BASE_URL, APP_ENV, EMBEDDING_DIMS, provider keys (optional; also settable in UI), platform app ids/secrets (META_APP_ID/SECRET, LINKEDIN_CLIENT_ID/SECRET, X_CLIENT_ID/SECRET, TIKTOK_CLIENT_KEY/SECRET, GOOGLE_CLIENT_ID/SECRET, PINTEREST_APP_ID/SECRET)`.

## 21.3 Images
One backend `Dockerfile` (multi-stage: uv build → slim runtime with ffmpeg, libmagic, fonts); entrypoint chooses `api|worker|scheduler` by `BOTWOK_PROCESS`. One frontend `Dockerfile` (standalone Next output). Same images deploy to the VPS with a `docker-compose.prod.yml` override (no bind mounts, Caddy in front, resource limits, restart policies, log driver).

## 21.4 Local AI option

| Need | Local feasibility | Recommendation |
|---|---|---|
| `cheap` tier (classification, extraction, summaries, ideation) | **Yes.** 7–14B instruct models (e.g. Llama 3.x 8B, Qwen 2.5/3 7–14B, Gemma 3 12B, Mistral Small) are adequate with structured-output prompting | Ollama (Mac Metal / NVIDIA) or vLLM (NVIDIA, higher throughput); OpenAI-compatible endpoint → `OpenAICompatibleProvider` |
| `balanced` tier (research synthesis, repurposing, critic) | **Partially.** 27–70B models (Qwen 3 32B, Llama 3.3 70B, Gemma 3 27B) approach cloud quality but need 24–48 GB VRAM or a 64–128 GB Apple Silicon machine; tool-calling reliability varies | Use cloud by default; local for privacy-sensitive workspaces with adequate hardware |
| `powerful` tier (planning, strategy, long-form writing, analysis) | **Not realistically** at frontier quality on consumer hardware; largest open models (100B+ MoE) need multi-GPU servers | Cloud (Anthropic/OpenAI/xAI/Google) |
| Embeddings | **Yes, easily.** `nomic-embed-text`, `bge-m3`, `mxbai-embed-large` via Ollama; CPU-OK | Default local when Ollama present; dims 768/1024 (set `EMBEDDING_DIMS`) |
| Image generation | **Yes with a GPU.** FLUX.1 [schnell/dev], SDXL via ComfyUI/Diffusers; 8–16 GB VRAM; Apple Silicon works via MLX/diffusers but slower | `LocalDiffusionProvider` (HTTP to ComfyUI); cloud fallback |
| Video generation | **Marginal.** Open models (Wan 2.x, LTX-Video, HunyuanVideo) run on 24 GB+ GPUs, minutes per clip | Cloud providers; `FFmpegTemplateProvider` for deterministic "image + captions + music" videos locally |
| Speech (TTS/STT) | **Yes.** Piper/Kokoro (TTS), faster-whisper (STT) on CPU/GPU | Local by default for subtitles; cloud TTS for premium voices |
| Web search | **Yes** via self-hosted SearXNG (no API cost; quality lower; rate-limited by engines) | SearXNG as zero-cost default; Tavily/Brave when keys exist |

Hardware guidance: Minimum for local `cheap` tier + embeddings: 16 GB RAM Apple Silicon or 8 GB VRAM NVIDIA. Comfortable: 32–64 GB unified memory (M-series Pro/Max) or 24 GB VRAM (RTX 3090/4090) for 14–32B models and FLUX. CPU-only machines: embeddings and Whisper only; use cloud for generation.

Configuration: in AI Settings → "Local models": detect Ollama (`GET /api/tags`), list models, assign to tiers; the routing table then points `cheap`/`embeddings` to `ollama/<model>`. The architecture doesn't change: local inference is just another provider configuration. Switching embedding models re-embeds in the background (`jobs.maintenance.reembed`).

Inference server comparison: **Ollama** (easiest, Mac+Linux+Windows, good for single user), **llama.cpp server** (lowest-level, max control, GGUF), **vLLM** (best throughput and OpenAI-compat on NVIDIA; server/VPS), **LM Studio / MLX** (Mac-friendly). Pick Ollama locally, vLLM on a GPU VPS.
