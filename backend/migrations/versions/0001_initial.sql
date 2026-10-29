
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

-- ===== ENUMS =====
CREATE TYPE platform_t        AS ENUM ('facebook','instagram','threads','linkedin','x','tiktok','youtube','pinterest','gbp');
CREATE TYPE member_role_t     AS ENUM ('owner','admin','editor','approver','viewer');
CREATE TYPE content_status_t  AS ENUM ('idea','draft','ai_generated','needs_review','approved','rejected','archived');
CREATE TYPE schedule_status_t AS ENUM ('scheduled','queued','publishing','published','failed','cancelled','paused');
CREATE TYPE run_status_t      AS ENUM ('queued','planning','running','awaiting_approval','paused','completed','failed','cancelled');
CREATE TYPE task_status_t     AS ENUM ('pending','ready','running','awaiting_approval','succeeded','failed','skipped','cancelled');
CREATE TYPE approval_status_t AS ENUM ('pending','approved','rejected','expired');
CREATE TYPE account_status_t  AS ENUM ('active','expired','revoked','error','disconnected');
CREATE TYPE content_format_t  AS ENUM ('text','image','carousel','video','short_video','story','article','poll','document','link');
CREATE TYPE content_type_t    AS ENUM ('educational','authority','promotional','engagement','storytelling','industry_news','case_study','behind_the_scenes','ugc','thought_leadership','announcement');
CREATE TYPE availability_t    AS ENUM ('official_api','public_web','search','user_provided','not_collected');
CREATE TYPE risk_level_t      AS ENUM ('low','medium','high');
CREATE TYPE automation_status_t AS ENUM ('running','waiting','awaiting_approval','succeeded','failed','cancelled');

-- ===== IDENTITY & TENANCY =====
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext NOT NULL UNIQUE,
  password_hash text,                              -- NULL when OIDC-only
  full_name text NOT NULL,
  avatar_asset_id uuid,
  preferences jsonb NOT NULL DEFAULT '{}'::jsonb,  -- timezone, locale, notification prefs, editor prefs
  is_active boolean NOT NULL DEFAULT true,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug citext NOT NULL UNIQUE,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,     -- timezone, retention, notification channels, approval policy
  plan text NOT NULL DEFAULT 'local',
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspace_members (
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role member_role_t NOT NULL DEFAULT 'editor',
  invited_by uuid REFERENCES users(id),
  joined_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX ON workspace_members (user_id);

CREATE TABLE invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  email citext NOT NULL,
  role member_role_t NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  invited_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,                 -- sha256 of opaque refresh token
  family_id uuid NOT NULL,                         -- rotation family; reuse detection revokes the family
  user_agent text, ip inet,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON refresh_sessions (user_id, expires_at);

CREATE TABLE api_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name text NOT NULL,
  key_prefix text NOT NULL,                        -- first 8 chars for display
  key_hash text NOT NULL UNIQUE,
  scopes text[] NOT NULL DEFAULT '{}',
  created_by uuid NOT NULL REFERENCES users(id),
  last_used_at timestamptz, expires_at timestamptz, revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== BRAND =====
CREATE TABLE brands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug citext NOT NULL,
  description text,
  industry text, sub_industry text,
  website text,
  geography text[] NOT NULL DEFAULT '{}',
  languages text[] NOT NULL DEFAULT '{en}',
  timezone text NOT NULL DEFAULT 'UTC',
  logo_asset_id uuid,
  status text NOT NULL DEFAULT 'active',
  created_by uuid NOT NULL REFERENCES users(id),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, slug)
);

CREATE TABLE brand_settings (
  brand_id uuid PRIMARY KEY REFERENCES brands(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  audience jsonb NOT NULL DEFAULT '{}'::jsonb,
  offering jsonb NOT NULL DEFAULT '{}'::jsonb,
  voice jsonb NOT NULL DEFAULT '{}'::jsonb,
  policies jsonb NOT NULL DEFAULT '{}'::jsonb,     -- forbidden_topics[], sensitive_topics[], claims_policy, compliance_tags[]
  topics jsonb NOT NULL DEFAULT '{}'::jsonb,       -- preferred_topics[], keywords[], hashtags{core,campaign,banned}, ctas[]
  visual jsonb NOT NULL DEFAULT '{}'::jsonb,
  platforms jsonb NOT NULL DEFAULT '{}'::jsonb,
  goals jsonb NOT NULL DEFAULT '{}'::jsonb,
  strategy jsonb NOT NULL DEFAULT '{}'::jsonb,     -- current strategy version {version, pillars, mix, platform_strategy, rationale, evidence_ids}
  context_cache_key text,                          -- hash of all sections for BrandContext cache invalidation
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (jsonb_typeof(voice)='object' AND jsonb_typeof(policies)='object')
);

CREATE TABLE content_pillars (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text,
  share_target numeric(4,3) CHECK (share_target BETWEEN 0 AND 1),
  color text,
  examples text[] NOT NULL DEFAULT '{}',
  position int NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brand_id, name)
);

CREATE TABLE brand_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  kind text NOT NULL,                              -- logo|logo_dark|template|writing_sample|past_posts_export
  media_asset_id uuid,                             -- FK added after media_assets
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== SOCIAL ACCOUNTS =====
CREATE TABLE social_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  platform platform_t NOT NULL,
  auth_flavor text NOT NULL DEFAULT 'default',     -- instagram: facebook_login|instagram_login ; linkedin: member|organization ; tiktok: direct_post|inbox_upload
  external_id text NOT NULL,                       -- page id / ig user id / org urn / x user id / channel id / open_id / ad account...
  parent_external_id text,                         -- e.g. Facebook Page id for an IG account
  display_name text NOT NULL,
  handle text,
  avatar_url text,
  account_type text,                               -- business|creator|page|member|organization|channel|location
  status account_status_t NOT NULL DEFAULT 'active',
  scopes text[] NOT NULL DEFAULT '{}',
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb, -- probed: formats, limits, native_schedule, audited, verified...
  health jsonb NOT NULL DEFAULT '{}'::jsonb,       -- last probe result, errors
  last_probe_at timestamptz,
  connected_by uuid NOT NULL REFERENCES users(id),
  disconnected_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, platform, external_id)
);
CREATE INDEX ON social_accounts (brand_id, platform) WHERE disconnected_at IS NULL;

CREATE TABLE oauth_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  social_account_id uuid NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
  token_kind text NOT NULL,                        -- access|refresh|page|long_lived_user
  ciphertext bytea NOT NULL,
  nonce bytea NOT NULL,
  key_version int NOT NULL,
  expires_at timestamptz,
  refresh_expires_at timestamptz,
  issued_at timestamptz NOT NULL DEFAULT now(),
  rotated_from uuid REFERENCES oauth_tokens(id),
  revoked_at timestamptz,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (social_account_id, token_kind, revoked_at)   -- one live token per kind (revoked_at NULL)
);
CREATE INDEX ON oauth_tokens (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE oauth_states (
  state text PRIMARY KEY,                          -- random 32 bytes, base64url
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id),
  platform platform_t NOT NULL,
  auth_flavor text NOT NULL,
  code_verifier text,                              -- PKCE
  redirect_uri text NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== COMPETITORS =====
CREATE TABLE competitors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL,
  website text,
  description text,
  industry text,
  tags text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'active',           -- active|paused
  monitoring_frequency text NOT NULL DEFAULT 'weekly', -- none|daily|weekly
  last_synced_at timestamptz,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brand_id, name)
);

CREATE TABLE competitor_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  competitor_id uuid NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
  platform platform_t,                             -- NULL = website/blog/other url
  kind text NOT NULL DEFAULT 'social',             -- social|website|blog|rss|other
  handle text, url text, platform_account_id text,
  availability availability_t NOT NULL DEFAULT 'not_collected',
  followers_count bigint, media_count bigint, bio text,
  profile_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  sync_status text, last_synced_at timestamptz, last_error text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON competitor_profiles (competitor_id);

CREATE TABLE competitor_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  profile_id uuid NOT NULL REFERENCES competitor_profiles(id) ON DELETE CASCADE,
  platform platform_t,
  external_id text, url text,
  posted_at timestamptz,
  format content_format_t,
  text text,
  hashtags text[] NOT NULL DEFAULT '{}', mentions text[] NOT NULL DEFAULT '{}',
  media_urls text[] NOT NULL DEFAULT '{}',
  like_count bigint, comment_count bigint, share_count bigint, view_count bigint,
  availability availability_t NOT NULL,
  content_hash text NOT NULL,
  analysis jsonb NOT NULL DEFAULT '{}'::jsonb,     -- hook, pillar, tone, cta, topics (LLM-labeled)
  embedding vector({DIMS}), embedding_model text,
  retention_until timestamptz,                     -- policy-driven (e.g. YouTube stats 30 d)
  retrieved_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_id, content_hash)
);
CREATE INDEX ON competitor_posts (profile_id, posted_at DESC);
CREATE INDEX ON competitor_posts USING hnsw (embedding vector_cosine_ops);

CREATE TABLE competitor_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  profile_id uuid NOT NULL REFERENCES competitor_profiles(id) ON DELETE CASCADE,
  captured_at timestamptz NOT NULL DEFAULT now(),
  followers_count bigint, posts_last_7d int, posts_last_30d int, avg_engagement numeric(10,4),
  format_mix jsonb, top_hashtags jsonb, posting_hours jsonb, raw jsonb,
  UNIQUE (profile_id, captured_at)
);

CREATE TABLE competitor_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  competitor_ids uuid[] NOT NULL,
  kind text NOT NULL,                              -- single|comparison|monitoring|opportunities
  period_start date, period_end date,
  content jsonb NOT NULL,
  rendered_object_key text,
  ai_run_id uuid,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== RESEARCH =====
CREATE TABLE research_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE SET NULL,
  competitor_id uuid REFERENCES competitors(id) ON DELETE SET NULL,
  query text NOT NULL,
  scope text[] NOT NULL DEFAULT '{web}',
  depth text NOT NULL DEFAULT 'standard',
  params jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued',           -- queued|running|completed|failed|cancelled
  ai_run_id uuid,
  result jsonb,                                    -- findings[], topics[], gaps[], summary
  source_count int NOT NULL DEFAULT 0,
  cost_usd numeric(12,6) NOT NULL DEFAULT 0,
  error text,
  created_by uuid REFERENCES users(id),
  started_at timestamptz, completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON research_runs (workspace_id, created_at DESC);

CREATE TABLE research_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  competitor_id uuid REFERENCES competitors(id) ON DELETE SET NULL,
  canonical_url text NOT NULL,
  final_url text, domain text NOT NULL,
  title text, author text,
  source_kind text NOT NULL DEFAULT 'web',         -- web|news|rss|social|competitor_site|pdf|user_provided
  platform platform_t,
  published_at timestamptz, retrieved_at timestamptz NOT NULL DEFAULT now(),
  language text,
  summary text,
  keywords text[] NOT NULL DEFAULT '{}', topics text[] NOT NULL DEFAULT '{}',
  entities jsonb NOT NULL DEFAULT '{}'::jsonb,
  credibility_score numeric(4,3), credibility_components jsonb,
  citation text,
  content_hash text, simhash bigint,
  content_object_key text,                         -- MinIO full text
  word_count int,
  trust text NOT NULL DEFAULT 'untrusted',         -- untrusted|trusted
  injection_flag boolean NOT NULL DEFAULT false,
  fetch_status text NOT NULL DEFAULT 'ok', error text,
  duplicates_of uuid REFERENCES research_sources(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, canonical_url)
);
CREATE INDEX ON research_sources (workspace_id, domain);
CREATE INDEX ON research_sources (content_hash);
CREATE INDEX ON research_sources USING gin (title gin_trgm_ops);

CREATE TABLE research_run_sources (                -- link table with per-run ranking
  run_id uuid NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
  rank int NOT NULL,
  relevance_score numeric(4,3) NOT NULL,
  query_variant text,
  PRIMARY KEY (run_id, source_id)
);

CREATE TABLE research_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source_id uuid NOT NULL UNIQUE REFERENCES research_sources(id) ON DELETE CASCADE,
  text_object_key text NOT NULL,
  structure jsonb NOT NULL DEFAULT '{}'::jsonb,    -- headings, links, images, claims[]
  extractor text, extracted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE research_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  section text,
  text text NOT NULL,
  token_count int,
  embedding vector({DIMS}), embedding_model text,
  UNIQUE (source_id, chunk_index)
);
CREATE INDEX ON research_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE rss_feeds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  competitor_id uuid REFERENCES competitors(id) ON DELETE CASCADE,
  url text NOT NULL, title text,
  status text NOT NULL DEFAULT 'active', last_polled_at timestamptz, last_etag text, last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, url)
);

CREATE TABLE keywords (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  term citext NOT NULL,
  source text NOT NULL DEFAULT 'user',             -- user|discovered|competitor|trend
  volume_hint int, related text[] NOT NULL DEFAULT '{}',
  frequency jsonb NOT NULL DEFAULT '{}'::jsonb,    -- {date: count}
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, brand_id, term)
);

-- ===== TRENDS =====
CREATE TABLE trends (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  label text NOT NULL, summary text,
  score numeric(6,3) NOT NULL, velocity numeric(8,3),
  status text NOT NULL DEFAULT 'active',           -- emerging|active|fading|dismissed
  platforms platform_t[] NOT NULL DEFAULT '{}', keywords text[] NOT NULL DEFAULT '{}',
  first_seen timestamptz NOT NULL, last_seen timestamptz NOT NULL,
  example_source_ids uuid[] NOT NULL DEFAULT '{}',
  ai_run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON trends (brand_id, status, score DESC);

CREATE TABLE trend_signals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  trend_id uuid REFERENCES trends(id) ON DELETE CASCADE,
  kind text NOT NULL,                              -- news_mention|hashtag|keyword|competitor_post|search_volume
  term text NOT NULL, platform platform_t,
  observed_at timestamptz NOT NULL, value numeric(14,3) NOT NULL,
  source_id uuid REFERENCES research_sources(id) ON DELETE SET NULL,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ON trend_signals (workspace_id, term, observed_at);

-- ===== CONTENT =====
CREATE TABLE campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL, description text, goal text,
  starts_on date, ends_on date,
  color text, status text NOT NULL DEFAULT 'planned',  -- planned|active|completed|archived
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE content_ideas (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
  pillar_id uuid REFERENCES content_pillars(id) ON DELETE SET NULL,
  title text NOT NULL, angle text,
  content_type content_type_t,
  formats content_format_t[] NOT NULL DEFAULT '{}', platforms platform_t[] NOT NULL DEFAULT '{}',
  hooks jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,     -- {source_ids[], trend_id, insight_ids[], research_run_id}
  score numeric(5,3), novelty_score numeric(5,3),
  status text NOT NULL DEFAULT 'new',              -- new|shortlisted|promoted|discarded
  promoted_content_id uuid,
  embedding vector({DIMS}), embedding_model text,
  ai_run_id uuid, created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON content_ideas (brand_id, status, created_at DESC);
CREATE INDEX ON content_ideas USING hnsw (embedding vector_cosine_ops);

CREATE TABLE content_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
  idea_id uuid REFERENCES content_ideas(id) ON DELETE SET NULL,
  pillar_id uuid REFERENCES content_pillars(id) ON DELETE SET NULL,
  title text NOT NULL,
  content_type content_type_t,
  master_format content_format_t NOT NULL DEFAULT 'text',
  status content_status_t NOT NULL DEFAULT 'draft',
  body jsonb NOT NULL DEFAULT '{}'::jsonb,         -- {hook, body_md, cta, hashtags[], keywords[], visual_concept, alt_text, notes}
  language text NOT NULL DEFAULT 'en',
  current_version int NOT NULL DEFAULT 1,
  ai_generated boolean NOT NULL DEFAULT false,
  generation_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  risk_level risk_level_t NOT NULL DEFAULT 'low',
  approval_required boolean NOT NULL DEFAULT true,
  critique jsonb, factcheck jsonb,
  embedding vector({DIMS}), embedding_model text,
  created_by uuid NOT NULL REFERENCES users(id), assigned_to uuid REFERENCES users(id),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON content_items (brand_id, status, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ON content_items (campaign_id);
CREATE INDEX ON content_items USING hnsw (embedding vector_cosine_ops);

CREATE TABLE content_variants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  content_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  platform platform_t NOT NULL,
  format content_format_t NOT NULL,
  social_account_id uuid REFERENCES social_accounts(id) ON DELETE SET NULL,
  text text,
  segments jsonb NOT NULL DEFAULT '[]'::jsonb,     -- thread posts / carousel slides / script scenes
  hashtags text[] NOT NULL DEFAULT '{}',
  media_plan jsonb NOT NULL DEFAULT '{}'::jsonb,
  platform_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  status content_status_t NOT NULL DEFAULT 'draft',
  validation jsonb, critique jsonb, factcheck jsonb,
  changes_made text[] NOT NULL DEFAULT '{}',
  current_version int NOT NULL DEFAULT 1,
  ai_generated boolean NOT NULL DEFAULT false,
  generation_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON content_variants (content_item_id);
CREATE INDEX ON content_variants (social_account_id, status);

CREATE TABLE content_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  target_type text NOT NULL,                       -- item|variant
  target_id uuid NOT NULL,
  version int NOT NULL,
  snapshot jsonb NOT NULL,
  author_type text NOT NULL,                       -- user|agent
  author_id text NOT NULL,                         -- user id or agent id
  ai_call_id uuid,
  diff_summary text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (target_type, target_id, version)
);

CREATE TABLE content_sources (
  content_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
  claim_text text,
  used_for text NOT NULL DEFAULT 'claim',          -- claim|inspiration|data
  PRIMARY KEY (content_item_id, source_id, used_for)
);

CREATE TABLE hashtags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  tag citext NOT NULL,
  platform platform_t,
  uses int NOT NULL DEFAULT 0,
  avg_engagement numeric(10,4),
  banned boolean NOT NULL DEFAULT false,
  last_used_at timestamptz,
  UNIQUE (workspace_id, brand_id, tag, platform)
);

-- ===== MEDIA =====
CREATE TABLE media_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE SET NULL,
  kind text NOT NULL,                              -- image|video|audio|document
  source text NOT NULL,                            -- upload|generated|derived|imported
  bucket text NOT NULL, object_key text NOT NULL,
  mime text NOT NULL, bytes bigint NOT NULL,
  width int, height int, duration_ms int, fps numeric(6,3), codec text,
  sha256 text NOT NULL,
  alt_text text, caption text, labels text[] NOT NULL DEFAULT '{}',
  ai_generated boolean NOT NULL DEFAULT false,
  provider text, model text, prompt text, seed bigint, generation_params jsonb,
  derived_from_id uuid REFERENCES media_assets(id) ON DELETE SET NULL,
  transform jsonb, platform_target text,
  carousel_group_id uuid, position int,
  status text NOT NULL DEFAULT 'ready',            -- processing|ready|failed
  error text,
  created_by uuid REFERENCES users(id),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (bucket, object_key)
);
CREATE INDEX ON media_assets (workspace_id, kind, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ON media_assets (sha256);
ALTER TABLE brand_assets ADD FOREIGN KEY (media_asset_id) REFERENCES media_assets(id) ON DELETE SET NULL;
ALTER TABLE brands ADD FOREIGN KEY (logo_asset_id) REFERENCES media_assets(id) ON DELETE SET NULL;
ALTER TABLE users ADD FOREIGN KEY (avatar_asset_id) REFERENCES media_assets(id) ON DELETE SET NULL;

CREATE TABLE content_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  content_item_id uuid REFERENCES content_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES content_variants(id) ON DELETE CASCADE,
  media_asset_id uuid NOT NULL REFERENCES media_assets(id) ON DELETE RESTRICT,
  role text NOT NULL DEFAULT 'primary',            -- primary|carousel_slide|thumbnail|cover|subtitle
  position int NOT NULL DEFAULT 0,
  alt_text text,
  CHECK (content_item_id IS NOT NULL OR variant_id IS NOT NULL)
);
CREATE INDEX ON content_assets (variant_id);

-- ===== SCHEDULING & PUBLISHING =====
CREATE TABLE recurring_schedules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL,
  rrule text NOT NULL, timezone text NOT NULL,
  kind text NOT NULL,                              -- repost_variant|automation|slot_template
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active',
  next_run_at timestamptz, last_materialized_until timestamptz,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE scheduled_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  content_variant_id uuid NOT NULL REFERENCES content_variants(id) ON DELETE CASCADE,
  social_account_id uuid NOT NULL REFERENCES social_accounts(id) ON DELETE RESTRICT,
  scheduled_at timestamptz NOT NULL,
  timezone text NOT NULL,
  status schedule_status_t NOT NULL DEFAULT 'scheduled',
  priority int NOT NULL DEFAULT 0,
  queued_at timestamptz, publishing_started_at timestamptz, published_at timestamptz,
  attempt_count int NOT NULL DEFAULT 0, max_attempts int NOT NULL DEFAULT 5,
  next_attempt_at timestamptz, last_error text,
  idempotency_root uuid NOT NULL DEFAULT gen_random_uuid(),
  recurring_schedule_id uuid REFERENCES recurring_schedules(id) ON DELETE SET NULL,
  approval_id uuid,
  native_schedule boolean NOT NULL DEFAULT false,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON scheduled_posts (status, scheduled_at);
CREATE INDEX ON scheduled_posts (status, next_attempt_at) WHERE status = 'queued';
CREATE INDEX ON scheduled_posts (brand_id, scheduled_at);
CREATE UNIQUE INDEX scheduled_posts_one_live ON scheduled_posts (content_variant_id, social_account_id)
  WHERE status IN ('scheduled','queued','publishing');

CREATE TABLE publish_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  scheduled_post_id uuid NOT NULL REFERENCES scheduled_posts(id) ON DELETE CASCADE,
  attempt_no int NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'running',          -- running|succeeded|failed|ambiguous|reconciled
  state jsonb NOT NULL DEFAULT '{}'::jsonb,        -- intermediate ids: creation_id, media_ids, publish_id, segment_external_ids[]
  request_fingerprint text NOT NULL,
  error_category text, error_code text, error_message text,
  platform_response jsonb,
  worker_id text, heartbeat_at timestamptz,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  UNIQUE (scheduled_post_id, attempt_no)
);

CREATE TABLE published_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  scheduled_post_id uuid REFERENCES scheduled_posts(id) ON DELETE SET NULL,
  content_variant_id uuid REFERENCES content_variants(id) ON DELETE SET NULL,
  social_account_id uuid NOT NULL REFERENCES social_accounts(id) ON DELETE RESTRICT,
  platform platform_t NOT NULL,
  external_id text NOT NULL, external_url text,
  segments jsonb NOT NULL DEFAULT '[]'::jsonb,
  published_at timestamptz NOT NULL,
  imported boolean NOT NULL DEFAULT false,         -- true for posts pulled from the platform (not published by Botwok)
  raw jsonb,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (social_account_id, external_id)
);
CREATE UNIQUE INDEX published_posts_one_live ON published_posts (scheduled_post_id) WHERE deleted_at IS NULL AND scheduled_post_id IS NOT NULL;
CREATE INDEX ON published_posts (brand_id, published_at DESC);

-- ===== ANALYTICS =====
CREATE TABLE post_metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  published_post_id uuid NOT NULL REFERENCES published_posts(id) ON DELETE CASCADE,
  platform platform_t NOT NULL,
  captured_at timestamptz NOT NULL,
  metric_window text NOT NULL DEFAULT 'lifetime',  -- lifetime|day
  impressions bigint, reach bigint, views bigint, engaged_views bigint,
  likes bigint, comments bigint, shares bigint, saves bigint, clicks bigint, link_clicks bigint, profile_clicks bigint,
  watch_time_s bigint, avg_watch_time_s numeric(10,2), completion_rate numeric(6,4),
  follows_from_post bigint, reposts bigint, replies bigint, quotes bigint, dislikes bigint,
  engagement_rate numeric(8,5), engagement_rate_basis text,
  raw jsonb, availability jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (published_post_id, metric_window, captured_at)
);
CREATE INDEX ON post_metrics (published_post_id, captured_at DESC);

CREATE TABLE account_metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  social_account_id uuid NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
  date date NOT NULL,
  followers bigint, followers_delta bigint, following bigint,
  impressions bigint, reach bigint, views bigint, profile_views bigint, website_clicks bigint,
  posts_count int, engagement_total bigint,
  raw jsonb, availability jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (social_account_id, date)
);

CREATE TABLE analytics_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  scope text NOT NULL,                             -- account|platform|brand|campaign|pillar|format
  scope_id text NOT NULL,
  period text NOT NULL,                            -- day|week|month
  period_start date NOT NULL,
  metrics jsonb NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brand_id, scope, scope_id, period, period_start)
);

CREATE TABLE insights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  period_start date NOT NULL, period_end date NOT NULL,
  statement text NOT NULL,
  kind text NOT NULL,                              -- format|pillar|timing|topic|platform|competitor|audience
  metric text, effect_size numeric(10,4), n int,
  confidence text NOT NULL,                        -- low|medium|high
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  ai_run_id uuid,
  status text NOT NULL DEFAULT 'new',              -- new|acknowledged|dismissed
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON insights (brand_id, created_at DESC);

CREATE TABLE recommendations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  insight_id uuid REFERENCES insights(id) ON DELETE SET NULL,
  action text NOT NULL, rationale text, expected_impact text,
  priority text NOT NULL DEFAULT 'p2',
  target jsonb NOT NULL DEFAULT '{}'::jsonb,       -- {pillar_id|format|time_slot|topic|platform}
  status text NOT NULL DEFAULT 'proposed',         -- proposed|accepted|rejected|applied
  applied_to jsonb, decided_by uuid REFERENCES users(id), decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== AI =====
CREATE TABLE ai_agents (                           -- registry (seeded); per-workspace overrides live in ai_settings
  id text PRIMARY KEY,                             -- 'writer'
  name text NOT NULL, description text,
  tier text NOT NULL,                              -- cheap|balanced|powerful
  tools text[] NOT NULL DEFAULT '{}',
  actions jsonb NOT NULL DEFAULT '{}'::jsonb,
  limits jsonb NOT NULL DEFAULT '{}'::jsonb,       -- max_turns, max_tool_calls, expected_output_tokens
  enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE prompt_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,   -- NULL = global default
  agent_id text NOT NULL REFERENCES ai_agents(id),
  action text,
  version int NOT NULL,
  body text NOT NULL,
  variables text[] NOT NULL DEFAULT '{}',
  model_hints jsonb NOT NULL DEFAULT '{}'::jsonb,
  is_active boolean NOT NULL DEFAULT false,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, agent_id, action, version)
);

CREATE TABLE ai_settings (
  workspace_id uuid PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
  routing jsonb NOT NULL DEFAULT '{}'::jsonb,      -- {cheap:{primary,fallback}, balanced:{...}, powerful:{...}, embeddings:{...}, per_agent:{writer:{...}}}
  providers jsonb NOT NULL DEFAULT '{}'::jsonb,    -- {anthropic:{enabled, key_ref}, openai:{...}, xai:{...}, google:{...}, ollama:{base_url}}  (keys stored encrypted in provider_secrets)
  media jsonb NOT NULL DEFAULT '{}'::jsonb,        -- image/video/speech provider choices
  search jsonb NOT NULL DEFAULT '{}'::jsonb,       -- search provider order
  safety jsonb NOT NULL DEFAULT '{}'::jsonb,       -- auto_approve: never|score_threshold, thresholds, require_fact_check_for[], high_risk_roles[]
  budgets jsonb NOT NULL DEFAULT '{}'::jsonb,      -- default per-run cap, confirm_above_usd
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE provider_secrets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  provider text NOT NULL,                          -- anthropic|openai|xai|google|tavily|brave|exa|elevenlabs|...
  ciphertext bytea NOT NULL, nonce bytea NOT NULL, key_version int NOT NULL,
  last4 text, status text NOT NULL DEFAULT 'active', last_verified_at timestamptz,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, provider)
);

CREATE TABLE ai_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE SET NULL,
  user_id uuid NOT NULL REFERENCES users(id),
  title text, summary text, summary_embedding vector({DIMS}), embedding_model text,
  context_ref jsonb,                               -- {content_item_id} when opened from Studio
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  conversation_id uuid NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
  role text NOT NULL,                              -- user|assistant|system
  content jsonb NOT NULL,                          -- text + attachments + run_id references
  run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ai_messages (conversation_id, created_at);

CREATE TABLE ai_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE SET NULL,
  user_id uuid REFERENCES users(id),
  conversation_id uuid REFERENCES ai_conversations(id) ON DELETE SET NULL,
  mode text NOT NULL,                              -- chat|task|tool|automation
  input jsonb NOT NULL,
  intent jsonb, plan jsonb, result jsonb,
  status run_status_t NOT NULL DEFAULT 'queued',
  cancel_requested boolean NOT NULL DEFAULT false,
  tokens_in bigint NOT NULL DEFAULT 0, tokens_out bigint NOT NULL DEFAULT 0, cached_tokens bigint NOT NULL DEFAULT 0,
  cost_usd numeric(12,6) NOT NULL DEFAULT 0,
  budget jsonb NOT NULL DEFAULT '{}'::jsonb,
  error text, reasoning_summary text,
  automation_run_id uuid,
  queued_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ai_runs (workspace_id, created_at DESC);
CREATE INDEX ON ai_runs (status) WHERE status IN ('queued','running','awaiting_approval');

CREATE TABLE ai_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
  task_key text NOT NULL,                          -- 't2.3'
  parent_key text,
  agent_id text NOT NULL REFERENCES ai_agents(id),
  action text NOT NULL,
  label text NOT NULL,                             -- "Researching web"
  inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
  depends_on text[] NOT NULL DEFAULT '{}',
  requires_approval boolean NOT NULL DEFAULT false,
  status task_status_t NOT NULL DEFAULT 'pending',
  output jsonb, error text,
  tokens_in bigint NOT NULL DEFAULT 0, tokens_out bigint NOT NULL DEFAULT 0, cost_usd numeric(12,6) NOT NULL DEFAULT 0,
  started_at timestamptz, finished_at timestamptz, heartbeat_at timestamptz,
  UNIQUE (run_id, task_key)
);

CREATE TABLE ai_tool_calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
  task_id uuid REFERENCES ai_tasks(id) ON DELETE CASCADE,
  call_index int NOT NULL,
  tool_name text NOT NULL,
  side_effect text NOT NULL,                       -- READ|WRITE_INTERNAL|EXTERNAL_READ|SPEND|APPROVAL
  args jsonb NOT NULL,
  result jsonb, result_object_key text,            -- large results in MinIO
  status text NOT NULL DEFAULT 'running',          -- running|succeeded|failed|denied|awaiting_approval
  error text, duration_ms int,
  approval_id uuid,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  UNIQUE (task_id, call_index)
);

CREATE TABLE ai_calls (                            -- every LLM request
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  run_id uuid REFERENCES ai_runs(id) ON DELETE CASCADE,
  task_id uuid REFERENCES ai_tasks(id) ON DELETE CASCADE,
  agent_id text, provider text NOT NULL, model text NOT NULL,
  prompt_version int, prompt_hash text,
  tokens_in int NOT NULL, tokens_out int NOT NULL, cached_tokens int NOT NULL DEFAULT 0,
  cost_usd numeric(12,6) NOT NULL,
  latency_ms int, finish_reason text, temperature numeric(3,2),
  request_object_key text, response_object_key text,   -- full payloads in MinIO (retention 90 d)
  error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ai_calls (workspace_id, created_at DESC);

CREATE TABLE memories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  kind text NOT NULL,                              -- preference|performance|strategy|conversation_summary|note
  text text NOT NULL,
  embedding vector({DIMS}), embedding_model text,
  importance numeric(4,3) NOT NULL DEFAULT 0.5,
  source_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  expires_at timestamptz, last_used_at timestamptz, use_count int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON memories (brand_id, kind);

-- ===== AUTOMATION =====
CREATE TABLE automation_workflows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  name text NOT NULL, description text,
  status text NOT NULL DEFAULT 'draft',            -- draft|active|paused|archived
  version int NOT NULL DEFAULT 1,
  trigger_summary text,
  autonomous_actions_enabled boolean NOT NULL DEFAULT false,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_run_at timestamptz, next_run_at timestamptz,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workflow_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  workflow_id uuid NOT NULL REFERENCES automation_workflows(id) ON DELETE CASCADE,
  key text NOT NULL,
  type text NOT NULL,
  label text,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  position jsonb NOT NULL DEFAULT '{"x":0,"y":0}'::jsonb,
  UNIQUE (workflow_id, key)
);

CREATE TABLE workflow_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  workflow_id uuid NOT NULL REFERENCES automation_workflows(id) ON DELETE CASCADE,
  from_node_key text NOT NULL, to_node_key text NOT NULL,
  branch text,                                     -- NULL|'true'|'false'|'approved'|'rejected'|'error'
  condition jsonb,
  UNIQUE (workflow_id, from_node_key, to_node_key, branch)
);

CREATE TABLE automation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  workflow_id uuid NOT NULL REFERENCES automation_workflows(id) ON DELETE CASCADE,
  workflow_version int NOT NULL,
  trigger_type text NOT NULL, trigger_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status automation_status_t NOT NULL DEFAULT 'running',
  context jsonb NOT NULL DEFAULT '{}'::jsonb,
  current_node_key text, waiting_until timestamptz, approval_id uuid,
  cost_usd numeric(12,6) NOT NULL DEFAULT 0, error text,
  dry_run boolean NOT NULL DEFAULT false,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
);
CREATE INDEX ON automation_runs (workflow_id, started_at DESC);

CREATE TABLE automation_run_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES automation_runs(id) ON DELETE CASCADE,
  node_key text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  input jsonb, output jsonb, ai_run_id uuid REFERENCES ai_runs(id) ON DELETE SET NULL,
  attempts int NOT NULL DEFAULT 0, error text,
  started_at timestamptz, finished_at timestamptz,
  UNIQUE (run_id, node_key)
);

-- ===== CROSS-CUTTING =====
CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  kind text NOT NULL,                              -- content|ai_action|automation_step|spend
  target_type text NOT NULL, target_id uuid NOT NULL,   -- content_item|content_variant|ai_run|automation_run
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,      -- proposed action(s)
  status approval_status_t NOT NULL DEFAULT 'pending',
  requested_by text NOT NULL,                      -- user id or 'agent:<id>'
  required_roles member_role_t[] NOT NULL DEFAULT '{approver,admin,owner}',
  decided_by uuid REFERENCES users(id), decided_at timestamptz, decision_comment text,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON approvals (workspace_id, status, created_at DESC);
ALTER TABLE scheduled_posts ADD FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE SET NULL;
ALTER TABLE ai_tool_calls ADD FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE SET NULL;
ALTER TABLE automation_runs ADD FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE SET NULL;

CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,   -- NULL = workspace-wide
  kind text NOT NULL,
  title text NOT NULL, body text, link text,
  severity text NOT NULL DEFAULT 'info',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  channels text[] NOT NULL DEFAULT '{in_app}',
  delivered jsonb NOT NULL DEFAULT '{}'::jsonb,    -- {email: ts, slack: ts}
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notifications (user_id, read_at, created_at DESC);

CREATE TABLE audit_logs (
  id bigserial PRIMARY KEY,
  workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
  actor_type text NOT NULL,                        -- user|agent|system|api_key
  actor_id text NOT NULL,
  action text NOT NULL,                            -- 'content.approve', 'social.connect', 'settings.update'
  target_type text, target_id text,
  before jsonb, after jsonb, meta jsonb,
  ip inet, user_agent text, request_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_logs (workspace_id, created_at DESC);
CREATE INDEX ON audit_logs (target_type, target_id);

CREATE TABLE events_outbox (
  id bigserial PRIMARY KEY,
  event_id uuid NOT NULL DEFAULT gen_random_uuid(),
  workspace_id uuid,
  name text NOT NULL,
  payload jsonb NOT NULL,
  actor jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  attempts int NOT NULL DEFAULT 0
);
CREATE INDEX ON events_outbox (published_at) WHERE published_at IS NULL;

CREATE TABLE usage_budgets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  kind text NOT NULL,                              -- ai_tokens|ai_cost|media_cost|search_calls|platform_reads
  period text NOT NULL,                            -- day|month
  limit_value numeric(14,4) NOT NULL,
  hard boolean NOT NULL DEFAULT true,
  UNIQUE (workspace_id, kind, period)
);

CREATE TABLE usage_ledger (
  id bigserial PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  kind text NOT NULL,
  provider text, model text, platform platform_t,
  quantity numeric(14,4) NOT NULL,                 -- tokens, calls, units, dollars
  cost_usd numeric(12,6) NOT NULL DEFAULT 0,
  ref_type text, ref_id uuid,                      -- ai_call|media_asset|research_run|sync job
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON usage_ledger (workspace_id, occurred_at DESC);

CREATE TABLE reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id) ON DELETE CASCADE,
  kind text NOT NULL,
  title text NOT NULL,
  period_start date, period_end date,
  content jsonb NOT NULL,
  rendered_object_key text,
  recipients jsonb NOT NULL DEFAULT '[]'::jsonb,
  ai_run_id uuid, automation_run_id uuid,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE webhooks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  direction text NOT NULL,                         -- outbound|inbound
  name text NOT NULL, url text, secret_ciphertext bytea, secret_nonce bytea, key_version int,
  events text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'active',
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

