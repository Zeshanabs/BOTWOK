"""BrandContext rendering (pure) + brand settings section validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.errors import ProblemError
from app.schemas.brand import DEFAULT_PILLARS, BrandSettingsUpdate, Platforms, Voice
from app.services.brand_service import (
    compute_context_cache_key,
    estimate_tokens,
    pillar_share_warnings,
    render_brand_context,
    slugify,
    validate_section,
)

BRAND = {"name": "Acme Billing", "industry": "healthcare", "sub_industry": "revenue-cycle services",
         "geography": ["US"], "languages": ["en"], "description": "Revenue-cycle management for small clinics.",
         "website": "https://acme.example"}


def _settings() -> dict:
    return {
        "audience": validate_section("audience", {
            "summary": "practice managers at 5–50 provider clinics", "market": "b2b",
            "personas": [{"name": "Pat", "role": "Practice manager", "pains": ["denials", "AR days"],
                          "goals": ["faster cash"], "objections": ["switching cost"], "channels": ["linkedin"]}]}),
        "voice": validate_section("voice", {
            "tone": {"formal": 70, "playful": 20, "concise": 80, "bold": 40}, "person": "we",
            "emoji_policy": "no emojis except ✅ in lists", "reading_level": 9,
            "style_rules": ["cite sources for regulatory claims"], "vocabulary": {"avoid": ["cheap", "guarantee"]},
            "writing_samples": [{"text": "Denials are a process problem,\n not a people problem.", "note": "LinkedIn hook"}]}),
        "policies": validate_section("policies", {"claims_policy": "never promise collection rates"}),
        "topics": validate_section("topics", {
            "hashtags": {"core": ["RevenueCycle", "#MedicalBilling"], "banned": ["followme"]},
            "ctas": [{"text": "Book a 15-min audit", "goal": "lead"},
                     {"text": "Download the denial checklist", "goal": "nurture", "url": "https://acme.example/dl"}],
            "preferred_topics": ["denial management"], "keywords": ["medical billing"]}),
        "visual": validate_section("visual", {
            "colors": {"primary": "#0b2545", "secondary": "#13A89E"}, "fonts": {"heading": "Inter", "body": "Inter"},
            "imagery_style": "clean, documentary photography", "donts": ["stock handshakes"]}),
        "platforms": validate_section("platforms", {
            "linkedin": {"cadence_per_week": 3, "formats": ["text"], "notes": "long-form"},
            "instagram": {"cadence_per_week": 3, "formats": ["carousel", "short_video"]},
            "x": {"cadence_per_week": 5, "formats": ["text"], "notes": "threads"}}),
        "goals": validate_section("goals", {"objectives": [{"name": "LinkedIn followers", "target": "+20%", "by": "Q1"},
                                                           {"name": "demo requests/mo", "target": 10}]}),
    }


PILLARS = [{"name": n, "share_target": s, "position": i, "status": "active"} for i, (n, s) in enumerate(
    [("Educational", 0.35), ("Authority", 0.2), ("Industry News", 0.2), ("Case Study", 0.15),
     ("Behind the Scenes", 0.1)])]

EXPECTED_COMPACT = """\
BRAND: Acme Billing (healthcare revenue-cycle services, US, EN)
AUDIENCE: practice managers at 5–50 provider clinics; B2B; pains: denials, AR days; goals: faster cash
VOICE: formal 70 / playful 20 / concise 80 / bold 40; we-voice; no emojis except ✅ in lists; reading level 9
RULES: never promise collection rates; cite sources for regulatory claims; avoid "cheap", "guarantee"
PILLARS: Educational 35% · Authority 20% · Industry News 20% · Case Study 15% · Behind the Scenes 10%
HASHTAGS core: #RevenueCycle #MedicalBilling; banned: #followme
CTAS: "Book a 15-min audit" (lead) · "Download the denial checklist" (nurture)
VISUAL: primary #0B2545, secondary #13A89E; Inter; clean, documentary photography; don't: stock handshakes
PLATFORMS: linkedin 3/wk text (long-form); instagram 3/wk carousel/short_video; x 5/wk text (threads)
GOALS: +20% LinkedIn followers by Q1; 10 demo requests/mo"""


def test_compact_snapshot_matches_doc_shape():
    assert render_brand_context(BRAND, _settings(), PILLARS, "compact") == EXPECTED_COMPACT


def test_rendering_is_deterministic():
    a = render_brand_context(BRAND, _settings(), PILLARS, "full")
    b = render_brand_context(dict(BRAND), _settings(), list(reversed(PILLARS)), "full")
    assert a == b  # pillar order comes from `position`, not input order


def test_full_mode_adds_samples_personas_and_details():
    full = render_brand_context(BRAND, _settings(), PILLARS, "full")
    assert full.startswith(EXPECTED_COMPACT.splitlines()[0])
    assert "WRITING SAMPLES:\n- \"Denials are a process problem, not a people problem.\" — LinkedIn hook" in full
    assert "PERSONAS:\n- Pat (Practice manager): pains: denials, AR days; goals: faster cash; " \
           "objections: switching cost; channels: linkedin" in full
    assert "DESCRIPTION: Revenue-cycle management for small clinics." in full
    assert "TOPICS: denial management" in full
    assert '"Download the denial checklist" (nurture) → https://acme.example/dl' in full
    compact = render_brand_context(BRAND, _settings(), PILLARS, "compact")
    assert "WRITING SAMPLES" not in compact and "PERSONAS" not in compact
    assert estimate_tokens(full) > estimate_tokens(compact)


def test_empty_brand_renders_only_brand_line_and_skips_inactive_pillars():
    pillars = [{"name": "Promotional", "share_target": 0.2, "position": 0, "status": "archived"}]
    assert render_brand_context({"name": "New Co"}, {}, pillars) == "BRAND: New Co"


def test_compact_caps_long_lists():
    s = _settings()
    s["topics"]["hashtags"]["core"] = [f"#tag{i}" for i in range(30)]
    compact = render_brand_context(BRAND, s, PILLARS, "compact")
    full = render_brand_context(BRAND, s, PILLARS, "full")
    assert "#tag9" in compact and "#tag10" not in compact
    assert "#tag29" in full


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        render_brand_context(BRAND, {}, [], "verbose")  # type: ignore[arg-type]


def test_cache_key_changes_with_any_section_or_pillar():
    s = _settings()
    k1 = compute_context_cache_key(BRAND, s, PILLARS)
    assert k1 == compute_context_cache_key(dict(BRAND), _settings(), [dict(p) for p in PILLARS])
    s2 = _settings()
    s2["goals"]["funnel_focus"] = "awareness"
    assert compute_context_cache_key(BRAND, s2, PILLARS) != k1
    p2 = [dict(p) for p in PILLARS]
    p2[0]["share_target"] = 0.4
    assert compute_context_cache_key(BRAND, s, p2) != k1
    assert len(k1) == 64


def test_section_validation_errors_are_problem_422():
    with pytest.raises(ProblemError) as ei:
        validate_section("voice", {"tone": {"formal": 150}})
    assert ei.value.status_code == 422
    assert ei.value.errors[0]["field"].startswith("voice.tone.formal")
    with pytest.raises(ProblemError):
        validate_section("visual", {"colors": {"primary": "navy"}})


def test_hashtags_normalized_and_platform_keys_checked():
    topics = validate_section("topics", {"hashtags": {"core": ["a", "#a", " #B "]}})
    assert topics["hashtags"]["core"] == ["#a", "#B"]
    with pytest.raises(ValidationError):
        Platforms.model_validate({"myspace": {"cadence_per_week": 1}})
    with pytest.raises(ValidationError):
        Platforms.model_validate({"linkedin": {"formats": ["hologram"]}})
    assert Voice.model_validate({"person": "WE"}).person == "we"


def test_partial_settings_update_tracks_provided_sections():
    upd = BrandSettingsUpdate.model_validate({"voice": {"tone": {"formal": 10}}})
    assert upd.model_fields_set == {"voice"}
    assert upd.voice is not None and upd.voice.model_dump(exclude_unset=True) == {"tone": {"formal": 10}}
    with pytest.raises(ValidationError):
        BrandSettingsUpdate.model_validate({"strategy": {}})


def test_pillar_share_sum_is_a_warning_and_helpers():
    assert pillar_share_warnings([{"share_target": 0.6}, {"share_target": 0.5}])
    assert not pillar_share_warnings([{"share_target": 0.6}, {"share_target": 0.5, "status": "archived"}])
    assert len(DEFAULT_PILLARS) == 10
    assert slugify("Acme Billing, Inc.") == "acme-billing-inc"
    assert slugify("Ünïcödé Café") == "unicode-cafe"


def test_deep_merge_for_partial_settings_updates():
    from app.services.brand_service import deep_merge
    current = {"tone": {"formal": 70, "playful": 20}, "style_rules": ["a", "b"], "emoji_policy": "none"}
    merged = deep_merge(current, {"tone": {"formal": 60}, "style_rules": ["c"], "emoji_policy": None})
    assert merged == {"tone": {"formal": 60, "playful": 20}, "style_rules": ["c"], "emoji_policy": None}
    assert current["tone"]["formal"] == 70  # input untouched
    assert "emoji_policy" not in validate_section("voice", merged)  # explicit null clears
