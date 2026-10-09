/** Competitor types (doc 17 §Competitors; backend/app/models/competitor.py). */
import type { Availability } from "@/components/data/availability-badge";

export interface CompetitorProfile {
  id: string;
  platform?: string | null;
  kind?: string | null;
  handle?: string | null;
  url?: string | null;
  availability: Availability | string;
  availability_reason?: string | null;
  reason?: string | null;
  followers_count?: number | null;
  media_count?: number | null;
  posts_per_week?: number | null;
  bio?: string | null;
  sync_status?: string | null;
  last_synced_at?: string | null;
  last_error?: string | null;
}

export interface Competitor {
  id: string;
  brand_id?: string;
  name: string;
  website?: string | null;
  description?: string | null;
  industry?: string | null;
  tags?: string[];
  status?: string;
  monitoring_frequency?: string;
  last_synced_at?: string | null;
  sync_status?: string | null;
  sync_progress?: number | null;
  last_error?: string | null;
  profiles?: CompetitorProfile[];
  posts_per_week?: number | null;
  followers_total?: number | null;
  followers_delta_30d?: number | null;
  cadence?: number[] | null;
  created_at?: string;
}

export interface CompetitorCreateInput {
  brand_id: string;
  name: string;
  website?: string | null;
  profiles: { platform: string; handle?: string; url?: string }[];
  monitoring_frequency: string;
}

export interface CompetitorPost {
  id: string;
  profile_id?: string;
  platform?: string | null;
  url?: string | null;
  posted_at?: string | null;
  format?: string | null;
  text?: string | null;
  hashtags?: string[];
  media_urls?: string[];
  like_count?: number | null;
  comment_count?: number | null;
  share_count?: number | null;
  view_count?: number | null;
  availability?: string | null;
  analysis?: Record<string, unknown> | null;
  retrieved_at?: string | null;
}

export interface CompetitorSnapshot {
  id: string;
  profile_id?: string;
  platform?: string | null;
  captured_at: string;
  followers_count?: number | null;
  posts_last_7d?: number | null;
  posts_last_30d?: number | null;
  avg_engagement?: number | string | null;
  format_mix?: Record<string, number> | null;
  top_hashtags?: Record<string, number> | null;
  posting_hours?: Record<string, number> | null;
}

export interface ReportItem { title?: string; topic?: string; name?: string; description?: string; detail?: string; share?: number; examples?: string[]; evidence?: string[] }

export interface CompetitorReport {
  id: string;
  report_id?: string | null;
  kind?: string;
  status?: string | null;
  title?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  content?: {
    summary?: string;
    pillars?: ReportItem[];
    hooks?: ReportItem[];
    tone?: ReportItem[] | string[] | string;
    visual?: ReportItem[] | string[] | string;
    palettes?: string[];
    gaps?: ReportItem[];
    opportunities?: ReportItem[];
    [k: string]: unknown;
  } | null;
  ai_run_id?: string | null;
  created_at?: string;
}

export interface CompareResponse {
  columns: (string | { id?: string; name?: string; kind?: string })[];
  rows: { metric: string; label?: string; values: (number | string | null)[]; availability?: (string | null)[] }[];
}
