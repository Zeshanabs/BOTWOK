# 10 — Media Architecture

## 10.1 MediaService

```
MediaService
├── Ingest        upload (presigned PUT to MinIO) → validate (magic bytes, size, dimensions, duration) → strip EXIF → re-encode → media_assets row
├── Processing    Pillow (resize/crop/pad/thumbnail/overlay text/compose carousel), FFmpeg (transcode, trim, concat, captions, audio mix, thumbnails, aspect/pad), rembg (background removal), Whisper (subtitles)
├── Generation    ImageProvider / VideoProvider / SpeechProvider via the provider registry (SPEND-class, budgeted)
├── Transform     platform-specific renditions (aspect ratio, codec, bitrate, max size, duration, safe margins)
└── Catalog       media_assets (originals + derived), content_assets (usage), alt text, labels (ai_generated), lineage (derived_from)
```

Processing runs in `media` queue workers (CPU-bound; concurrency = cores). The API never transcodes inline.

## 10.2 Data model
`media_assets`: `id, workspace_id, brand_id?, kind (image|video|audio|document), source (upload|generated|derived|imported), object_key, bucket, mime, bytes, width, height, duration_ms, fps?, codec?, sha256, alt_text, caption, labels[] , ai_generated bool, provider?, model?, prompt?, seed?, generation_params jsonb, derived_from_id?, transform jsonb, platform_target?, status (processing|ready|failed), error, created_by, created_at`.
Renditions are separate rows with `derived_from_id` so a platform-specific file is traceable to its origin.

## 10.3 Providers (pluggable)

```
ImageProvider     OpenAIImageProvider (gpt-image-*) · XAIImageProvider (grok-image) · GoogleImageProvider (Imagen/Gemini image)
                  · StabilityProvider · ReplicateFalProvider (FLUX etc.) · LocalDiffusionProvider (ComfyUI/Diffusers HTTP)
VideoProvider     RunwayProvider · LumaProvider · KlingProvider · GoogleVeoProvider · OpenAISoraProvider · LocalVideoProvider (Wan/LTX via HTTP) · FFmpegTemplateProvider (deterministic "template videos": Ken Burns over images + captions + music)
SpeechProvider    OpenAISpeechProvider · ElevenLabsProvider · LocalKokoroPiperProvider (TTS) · WhisperLocalProvider / OpenAITranscribe (STT for subtitles)
FFmpeg            always present; used for all deterministic transforms
```
Interface (`ImageProvider`): `generate(prompt, negative, size, n, style, reference_images?) -> [GeneratedImage{bytes, seed, model, cost}]`, `edit(image, mask?, prompt)`, `capabilities()`. Video providers are async: `submit() -> job_id`, `status(job_id)`, `fetch(job_id)`; a `media` worker polls with backoff and writes the asset when done (`MEDIA_GENERATED`).

Provider selection: `ai_settings.media{image: {primary, fallback}, video: {...}, speech: {...}}`; per-call override allowed from the UI. Cost per generation is recorded in `usage_ledger(kind=media)`.

## 10.4 Platform transforms (declarative)
`app/media/platform_specs.py` holds per-platform/format specs (aspect ratios, min/max dimensions, max bytes, codecs, bitrate, max duration, fps, audio requirements, safe zones). `media.transform_for_platform(asset_id, platform, format)` picks the spec, produces a rendition (smart-crop with face/subject detection when available, else center-crop + pad in brand color), validates, and stores it. The publishing adapter uses the rendition, never the original. Specs must be verified against doc 26 and updated when platforms change (they are data, not code).

Examples (illustrative; verify): Instagram feed image JPEG 4:5–1.91:1, ≤ 8 MB; Reels 9:16 MP4 H.264/AAC 3 s–15 min ≤ 300 MB; Stories video 3–60 s ≤ 100 MB; TikTok video ≤ 4 GB chunked; X ≤ 4 media, video ≤ 20 min (8 GB) via v2 chunked upload; LinkedIn video ≤ 5 GB; YouTube Shorts ≤ 3 min vertical/square; Pinterest image 2:3 recommended.

## 10.5 Carousel generation
`media.compose_carousel(content_id, slides[{headline, body, image_asset?|generated prompt, layout}], template)` → renders N slides with Pillow (templates in `app/media/templates/*.json`: brand colors/fonts, safe margins, page counters, logo placement) → one `media_assets` row per slide + a `carousel_group_id`. For LinkedIn a PDF document is also produced (`document` format). The Studio media panel previews slides in order and allows reordering.

## 10.6 Video pipeline
- **Scripted short video**: `visual.video_script` → scenes[{voiceover, on_screen_text, visual: image prompt|asset|stock}] → images generated/selected → TTS → FFmpeg template: Ken Burns + captions (burned-in, from script timing or Whisper alignment) + music bed → MP4 renditions per platform.
- **Generated video**: VideoProvider clip(s) → optional captions/music → renditions.
- **Edited uploads**: trim, crop to 9:16 with subject tracking (optional), add captions (Whisper), add intro/outro/logo.
- Subtitles stored as SRT/VTT assets (`kind=document`) linked by `derived_from_id`; YouTube captions can be uploaded via `captions.insert`.

## 10.7 Safety & compliance
- Uploads: allowlisted MIME types, magic-byte check, size caps, image re-encode (defeats polyglot files), EXIF/GPS stripped, optional ClamAV scan container, SVG rejected for upload (rasterized if needed).
- Generation prompts pass a policy filter (no real identifiable people unless user-provided consent flag, no third-party logos, no medical/financial claim imagery); outputs carry `ai_generated=true`; where a platform exposes an "AI-generated" flag (e.g. Instagram `is_ai_generated`) the adapter sets it.
- Alt text is mandatory before scheduling an image post (critic flags missing alt text; adapter `validateContent()` enforces where platform supports alt text).
