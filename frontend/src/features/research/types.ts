/** Research types (doc 17 §Research; backend/app/models/research.py). */

export type ResearchScope = "web" | "news" | "rss" | "competitor_sites";
export type ResearchDepth = "quick" | "standard" | "deep";

export interface ResearchRunInput {
  query: string;
  scope: ResearchScope[];
  depth: ResearchDepth;
  recency_days?: number | null;
  brand_id?: string | null;
  competitor_id?: string | null;
}

export interface ResearchSourceRef {
  id: string;
  title?: string | null;
  url?: string | null;
  canonical_url?: string | null;
  domain?: string | null;
  source_kind?: string | null;
  published_at?: string | null;
  relevance?: number | string | null;
  relevance_score?: number | string | null;
  credibility?: number | string | null;
  credibility_score?: number | string | null;
  summary?: string | null;
  keywords?: string[];
  injection_flag?: boolean;
  saved?: boolean;
  rank?: number;
}

export interface ResearchFinding { text: string; source_ids?: string[] }

export interface ResearchRun {
  id: string;
  query: string;
  scope?: string[];
  depth?: string;
  params?: { recency_days?: number | null; [k: string]: unknown };
  recency_days?: number | null;
  status: string;
  brand_id?: string | null;
  competitor_id?: string | null;
  ai_run_id?: string | null;
  result?: { summary?: string | null; findings?: ResearchFinding[]; topics?: string[]; gaps?: string[]; partial_failures?: string[] } | null;
  sources?: ResearchSourceRef[];
  source_count?: number;
  cost_usd?: number | string | null;
  error?: string | null;
  created_at?: string;
  completed_at?: string | null;
}

export interface ResearchSourceDetail extends ResearchSourceRef {
  canonical_url?: string | null;
  final_url?: string | null;
  author?: string | null;
  retrieved_at?: string | null;
  language?: string | null;
  topics?: string[];
  content_hash?: string | null;
  citation?: string | null;
  word_count?: number | null;
  fetch_status?: string | null;
  trust?: string | null;
  text?: string | null;
  extracted_text?: string | null;
  content?: string | null;
  credibility_components?: Record<string, unknown> | null;
  competitor_id?: string | null;
}

export const ACTIVE_RESEARCH = ["queued", "running", "planning", "fetching", "ranking", "summarizing"];
export const relevanceOf = (s: ResearchSourceRef) => s.relevance ?? s.relevance_score ?? null;
export const credibilityOf = (s: ResearchSourceRef) => s.credibility ?? s.credibility_score ?? null;
