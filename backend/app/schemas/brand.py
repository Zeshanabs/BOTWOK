"""Brand schemas: brands, brand_settings sections (validated JSONB), pillars, assets, BrandContext."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.enums import ContentFormat, Platform

HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SECTION_NAMES: tuple[str, ...] = ("audience", "offering", "voice", "policies", "topics", "visual", "platforms", "goals")
BRAND_FIELDS: tuple[str, ...] = ("name", "description", "industry", "sub_industry", "website", "geography", "languages",
                                 "timezone")
DEFAULT_PILLARS: tuple[str, ...] = ("Educational", "Authority", "Promotional", "Engagement", "Storytelling", "Industry News",
                                    "Case Study", "Behind the Scenes", "User Generated Content", "Thought Leadership")
BRAND_ASSET_KINDS = Literal["logo", "logo_dark", "template", "writing_sample", "past_posts_export", "reference_image",
                            "style_guide", "font", "other"]


class _Model(BaseModel):
    """Section models keep unknown keys so the JSONB can evolve without migrations (doc 09 §9.1.1)."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------- audience
class Persona(_Model):
    name: str = Field(min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=200)
    pains: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)


class Audience(_Model):
    summary: str | None = Field(default=None, max_length=1000)
    personas: list[Persona] = Field(default_factory=list)
    demographics: str | None = Field(default=None, max_length=1000)
    geography: list[str] = Field(default_factory=list)
    market: Literal["b2b", "b2c", "b2b2c", "both"] | None = None


# ---------------------------------------------------------------- offering
class Product(_Model):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = None
    price_hint: str | None = Field(default=None, max_length=120)


class Offering(_Model):
    services: list[str] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    proof_points: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- voice
class Tone(_Model):
    """Tone sliders, 0–100: formal (vs casual), playful (vs serious), concise (vs expansive), bold (vs measured)."""
    formal: int | None = Field(default=None, ge=0, le=100)
    playful: int | None = Field(default=None, ge=0, le=100)
    concise: int | None = Field(default=None, ge=0, le=100)
    bold: int | None = Field(default=None, ge=0, le=100)


class WritingSample(_Model):
    text: str = Field(min_length=1, max_length=5000)
    note: str | None = Field(default=None, max_length=500)


class Vocabulary(_Model):
    preferred: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class Voice(_Model):
    tone: Tone = Field(default_factory=Tone)
    style_rules: list[str] = Field(default_factory=list)
    writing_samples: list[WritingSample] = Field(default_factory=list)
    vocabulary: Vocabulary = Field(default_factory=Vocabulary)
    emoji_policy: str | None = Field(default=None, max_length=300)
    humor_policy: str | None = Field(default=None, max_length=300)
    person: Literal["we", "i", "you", "they", "brand"] | None = None
    reading_level: int | None = Field(default=None, ge=1, le=20)

    @field_validator("person", mode="before")
    @classmethod
    def _lower_person(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v


# ---------------------------------------------------------------- policies
class SensitiveTopic(_Model):
    topic: str = Field(min_length=1, max_length=200)
    handling: str | None = Field(default=None, max_length=500)


class Policies(_Model):
    forbidden_topics: list[str] = Field(default_factory=list)
    sensitive_topics: list[SensitiveTopic] = Field(default_factory=list)
    claims_policy: str | None = Field(default=None, max_length=1000)
    legal_disclaimers: list[str] = Field(default_factory=list)
    compliance_tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- topics
class Hashtags(_Model):
    core: list[str] = Field(default_factory=list)
    campaign: list[str] = Field(default_factory=list)
    banned: list[str] = Field(default_factory=list)

    @field_validator("core", "campaign", "banned")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for tag in v:
            t = tag.strip().lstrip("#").strip()
            if not t:
                continue
            if any(c.isspace() for c in t):
                raise ValueError(f"hashtag {tag!r} must not contain whitespace")
            if f"#{t}" not in out:
                out.append(f"#{t}")
        return out


class CTA(_Model):
    text: str = Field(min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=80)
    url: str | None = None


class Topics(_Model):
    preferred_topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    hashtags: Hashtags = Field(default_factory=Hashtags)
    ctas: list[CTA] = Field(default_factory=list)


# ---------------------------------------------------------------- visual
def _check_hex(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not HEX_COLOR.match(v):
        raise ValueError(f"{v!r} is not a hex color like #0B2545")
    return v.upper()


class Colors(_Model):
    primary: str | None = None
    secondary: str | None = None
    accent: str | None = None
    neutral: list[str] = Field(default_factory=list)

    @field_validator("primary", "secondary", "accent")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        return _check_hex(v)

    @field_validator("neutral")
    @classmethod
    def _hex_list(cls, v: list[str]) -> list[str]:
        return [c for c in (_check_hex(x) for x in v) if c]


class Fonts(_Model):
    heading: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, max_length=120)


class Visual(_Model):
    colors: Colors = Field(default_factory=Colors)
    fonts: Fonts = Field(default_factory=Fonts)
    logo_asset_ids: list[UUID] = Field(default_factory=list)
    imagery_style: str | None = Field(default=None, max_length=1000)
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- platforms
class PlatformDefaults(_Model):
    enabled: bool = True
    formats: list[ContentFormat] = Field(default_factory=list)
    cadence_per_week: int | None = Field(default=None, ge=0, le=100)
    tone_adjustments: str | None = Field(default=None, max_length=500)
    hashtag_count: int | None = Field(default=None, ge=0, le=30)
    link_policy: str | None = Field(default=None, max_length=300)
    signature: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=300)


class Platforms(BaseModel):
    """Per-platform defaults keyed by platform code (doc 00 §1). Unknown platform keys are rejected."""
    model_config = ConfigDict(extra="forbid")
    facebook: PlatformDefaults | None = None
    instagram: PlatformDefaults | None = None
    threads: PlatformDefaults | None = None
    linkedin: PlatformDefaults | None = None
    x: PlatformDefaults | None = None
    tiktok: PlatformDefaults | None = None
    youtube: PlatformDefaults | None = None
    pinterest: PlatformDefaults | None = None
    gbp: PlatformDefaults | None = None


# ---------------------------------------------------------------- goals
class Objective(_Model):
    name: str = Field(min_length=1, max_length=200)
    metric: str | None = Field(default=None, max_length=120)
    target: str | float | None = None
    by: str | None = Field(default=None, max_length=40)


class Goals(_Model):
    objectives: list[Objective] = Field(default_factory=list)
    priority_platforms: list[Platform] = Field(default_factory=list)
    funnel_focus: str | None = Field(default=None, max_length=80)


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "audience": Audience, "offering": Offering, "voice": Voice, "policies": Policies, "topics": Topics,
    "visual": Visual, "platforms": Platforms, "goals": Goals,
}


# ---------------------------------------------------------------- settings
class BrandSettingsUpdate(BaseModel):
    """Partial PUT: only the sections present change; each is deep-merged (nested objects key-wise, lists replace)."""
    model_config = ConfigDict(extra="forbid")
    audience: Audience | None = None
    offering: Offering | None = None
    voice: Voice | None = None
    policies: Policies | None = None
    topics: Topics | None = None
    visual: Visual | None = None
    platforms: Platforms | None = None
    goals: Goals | None = None


class BrandSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    brand_id: UUID
    audience: Audience = Field(default_factory=Audience)
    offering: Offering = Field(default_factory=Offering)
    voice: Voice = Field(default_factory=Voice)
    policies: Policies = Field(default_factory=Policies)
    topics: Topics = Field(default_factory=Topics)
    visual: Visual = Field(default_factory=Visual)
    platforms: Platforms = Field(default_factory=Platforms)
    goals: Goals = Field(default_factory=Goals)
    strategy: dict[str, Any] = Field(default_factory=dict)
    context_cache_key: str | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- brands
class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    industry: str | None = Field(default=None, max_length=200)
    sub_industry: str | None = Field(default=None, max_length=200)
    website: HttpUrl | None = None
    geography: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    timezone: str = Field(default="UTC", max_length=64)
    seed_default_pillars: bool = False

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        if v is not None and not SLUG.match(v):
            raise ValueError("slug must be lowercase letters, digits and single hyphens")
        return v


class BrandUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    industry: str | None = Field(default=None, max_length=200)
    sub_industry: str | None = Field(default=None, max_length=200)
    website: HttpUrl | None = None
    geography: list[str] | None = None
    languages: list[str] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    logo_asset_id: UUID | None = None
    status: Literal["active", "archived"] | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        if v is not None and not SLUG.match(v):
            raise ValueError("slug must be lowercase letters, digits and single hyphens")
        return v


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None = None
    industry: str | None = None
    sub_industry: str | None = None
    website: str | None = None
    geography: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    timezone: str
    logo_asset_id: UUID | None = None
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- pillars
class PillarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    share_target: float | None = Field(default=None, ge=0, le=1)
    color: str | None = None
    examples: list[str] = Field(default_factory=list)
    position: int | None = Field(default=None, ge=0)
    status: Literal["active", "paused", "archived"] = "active"

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        return _check_hex(v)


class PillarUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    share_target: float | None = Field(default=None, ge=0, le=1)
    color: str | None = None
    examples: list[str] | None = None
    position: int | None = Field(default=None, ge=0)
    status: Literal["active", "paused", "archived"] | None = None

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        return _check_hex(v)


class PillarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    name: str
    description: str | None = None
    share_target: float | None = None
    color: str | None = None
    examples: list[str] = Field(default_factory=list)
    position: int
    status: str
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- assets / context / import
class BrandAssetCreate(BaseModel):
    kind: BRAND_ASSET_KINDS
    media_asset_id: UUID
    meta: dict[str, Any] = Field(default_factory=dict)


class BrandAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    kind: str
    media_asset_id: UUID | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class BrandContextOut(BaseModel):
    text: str
    token_estimate: int
    mode: Literal["compact", "full"]


class ImportFromWebsiteIn(BaseModel):
    url: HttpUrl


class ImportFromWebsiteOut(BaseModel):
    run_id: UUID
    status_url: str
