/** Content idea types (doc 17 §Ideas; backend/app/models/content.py ContentIdea). */

export type IdeaStatus = "new" | "shortlisted" | "promoted" | "discarded";
export const IDEA_STATUSES: IdeaStatus[] = ["new", "shortlisted", "promoted", "discarded"];

export interface Idea {
  id: string;
  brand_id?: string;
  title: string;
  angle?: string | null;
  content_type?: string | null;
  formats?: string[];
  format?: string | null;
  platforms?: string[];
  hooks?: (string | { text?: string })[];
  evidence?: {
    trend_ids?: string[];
    research_source_ids?: string[];
    insight_ids?: string[];
    report_id?: string;
    urls?: string[];
    rationale?: string;
    [k: string]: unknown;
  } | null;
  score?: number | string | null;
  novelty_score?: number | null;
  status: IdeaStatus | string;
  pillar_id?: string | null;
  pillar?: { id: string; name: string } | null;
  promoted_content_id?: string | null;
  ai_run_id?: string | null;
  similar_to?: string | null;
  created_by?: string | null;
  created_at?: string;
}

export interface GenerateIdeasInput {
  brand_id: string;
  count?: number;
  pillars?: string[];
  platforms?: string[];
  from?: { trend_ids?: string[]; research_run_id?: string; insight_ids?: string[]; report_id?: string; prompt?: string };
}
