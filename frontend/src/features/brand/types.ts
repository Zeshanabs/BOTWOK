/** Brand types mirror backend/app/schemas/brand.py (BrandOut, BrandSettingsOut, PillarOut). */

export interface Brand {
  id: string;
  workspace_id?: string;
  name: string;
  slug?: string;
  description?: string | null;
  industry?: string | null;
  sub_industry?: string | null;
  website?: string | null;
  geography?: string[];
  languages?: string[];
  timezone?: string;
  logo_asset_id?: string | null;
  status?: string;
  created_at?: string;
  updated_at?: string;
}

export interface BrandCreateInput {
  name: string;
  industry?: string | null;
  website?: string | null;
  timezone?: string;
  description?: string | null;
  languages?: string[];
}

export interface Persona { name: string; role?: string | null; pains?: string[]; goals?: string[]; objections?: string[]; channels?: string[] }
export interface Audience { summary?: string | null; personas?: Persona[]; demographics?: string | null; geography?: string[]; market?: "b2b" | "b2c" | "b2b2c" | "both" | null }
export interface Offering { services?: string[]; products?: { name: string; description?: string | null; url?: string | null }[]; differentiators?: string[]; proof_points?: string[] }
export interface Tone { formal?: number | null; playful?: number | null; concise?: number | null; bold?: number | null }
export interface WritingSample { text: string; note?: string | null }
export interface Voice {
  tone?: Tone;
  style_rules?: string[];
  writing_samples?: WritingSample[];
  vocabulary?: { preferred?: string[]; avoid?: string[] };
  emoji_policy?: string | null;
  humor_policy?: string | null;
  person?: "we" | "i" | "you" | "they" | "brand" | null;
  reading_level?: number | null;
}
export interface Policies { forbidden_topics?: string[]; sensitive_topics?: { topic: string; handling?: string | null }[]; claims_policy?: string | null; legal_disclaimers?: string[]; compliance_tags?: string[] }
export interface CTA { text: string; goal?: string | null; url?: string | null }
export interface Topics { preferred_topics?: string[]; keywords?: string[]; hashtags?: { core?: string[]; campaign?: string[]; banned?: string[] }; ctas?: CTA[] }
export interface Visual {
  colors?: { primary?: string | null; secondary?: string | null; accent?: string | null; neutral?: string[] };
  fonts?: { heading?: string | null; body?: string | null };
  logo_asset_ids?: string[];
  imagery_style?: string | null;
  dos?: string[];
  donts?: string[];
}
export interface PlatformDefaults { enabled?: boolean; formats?: string[]; cadence_per_week?: number | null; [k: string]: unknown }
export type PlatformsSection = Partial<Record<string, PlatformDefaults | null>>;
export interface Objective { name: string; metric?: string | null; target?: string | number | null; by?: string | null }
export interface Goals { objectives?: Objective[]; priority_platforms?: string[]; funnel_focus?: string | null }

export interface BrandSettings {
  brand_id?: string;
  audience?: Audience;
  offering?: Offering;
  voice?: Voice;
  policies?: Policies;
  topics?: Topics;
  visual?: Visual;
  platforms?: PlatformsSection;
  goals?: Goals;
  updated_at?: string | null;
}

export type SettingsSection = "audience" | "offering" | "voice" | "policies" | "topics" | "visual" | "platforms" | "goals";
export const SETTINGS_SECTIONS: SettingsSection[] = ["audience", "offering", "voice", "policies", "topics", "visual", "platforms", "goals"];
export type BrandSettingsUpdate = Partial<Pick<BrandSettings, SettingsSection>>;

export interface Pillar {
  id: string;
  brand_id?: string;
  name: string;
  description?: string | null;
  share_target?: number | null; // 0–1
  color?: string | null;
  examples?: string[];
  position?: number;
  status?: string;
  warnings?: string[];
}
export type PillarInput = Partial<Omit<Pillar, "id" | "brand_id" | "warnings">> & { name?: string };

export interface BrandContext { text: string; token_estimate?: number; mode?: string; version?: number }
