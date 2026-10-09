"""Declarative platform-rule engine (doc 09 §9.3.3 / §9.4, doc 26).

One table drives both the repurposer prompt (``describe_rules``) and deterministic validation
(``app.content.validators``). Values marked ``unverified`` come from doc 26 "?" cells and must be
re-checked against official documentation before being enforced as hard errors.

Shape of a resolved rule set (``rules_for(platform, format)``)::

    {
      "platform", "format", "supported", "support_note",
      "text": {"field", "max", "unit", "required", "unverified"},
      "title": {"max", "unit", "required"} | None,
      "description": {"max", "unit"} | None,           # secondary long text (YouTube/Pinterest/TikTok photo)
      "tags": {"max_total_chars"} | None,               # YouTube tags
      "hashtags": {"max", "recommended", "placement", "note"},
      "mentions": {"max", "severity"},
      "links": {"allowed", "clickable", "max", "url_weight", "strategy", "note"},
      "segments": {"supported", "kind", "max", "per_segment_max"} ,
      "media": {"required", "min", "max", "types", "image_mimes", "alt_text", "alt_text_max", "notes"},
      "poll": {...} | None,
      "forbidden_chars": [...], "forbidden_chars_fields": [...],
      "hook", "tone", "notes": [...],
    }
"""
from __future__ import annotations

import copy
from enum import Enum
from typing import Any

PLATFORMS = ("facebook", "instagram", "threads", "linkedin", "x", "tiktok", "youtube", "pinterest", "gbp")
FORMATS = ("text", "image", "carousel", "video", "short_video", "story", "article", "poll", "document", "link")

# Text-length units understood by validators.measure():
#   chars      – Unicode code points
#   x_weighted – X/Twitter weighted length (URLs = 23, CJK/emoji = 2)
#   utf8_bytes – UTF-8 byte length (YouTube description)
#   utf16      – UTF-16 code units (TikTok "runes")
#   threads    – characters, but emoji counted as their UTF-8 byte length

# ── Generation-side support matrix (doc 09 §9.3.3). True = supported; str = supported with a note;
#    False = not supported. Anything missing is unsupported.
SUPPORT: dict[str, dict[str, bool | str]] = {
    "instagram": {"image": True, "carousel": "up to 10 items (JPEG images)", "short_video": "Reels",
                  "story": True, "text": False, "video": False, "article": False, "poll": False, "document": False,
                  "link": False},
    "facebook": {"text": True, "image": True, "carousel": "multi-photo (attached_media param unverified)",
                 "short_video": "Reels 3–90 s, 9:16", "video": True, "story": "no API scheduling",
                 "poll": False, "link": True, "article": False, "document": False},
    "linkedin": {"text": True, "image": True, "carousel": "multi-image 2–20 (organic) or document PDF",
                 "short_video": True, "video": True, "article": "article share (supply title/description/thumbnail)",
                 "poll": True, "document": "PDF ≤ 100 MB / 300 pages", "link": True, "story": False},
    "x": {"text": True, "image": True, "carousel": "≤ 4 media", "short_video": True, "video": True,
          "poll": True, "link": "URL posts cost more via API", "story": False, "article": False, "document": False},
    "tiktok": {"carousel": "photo post ≤ 35 images (verified domain)", "short_video": True, "video": True,
               "text": False, "image": False, "story": False, "article": False, "poll": False, "document": False,
               "link": False},
    "youtube": {"short_video": "Shorts (≤ 3 min, vertical/square)", "video": True, "text": False, "image": False,
                "carousel": False, "story": False, "article": False, "poll": False, "document": False, "link": False},
    "threads": {"text": True, "image": True, "carousel": "2–20 items", "short_video": True, "video": True,
                "poll": True, "link": True, "story": False, "article": False, "document": False},
    "pinterest": {"image": True, "carousel": "2–5 images", "short_video": "video pin", "text": False, "video": False,
                  "story": False, "article": False, "poll": False, "document": False, "link": False},
    "gbp": {"text": "STANDARD post (EVENT/OFFER via platform_metadata.topic_type)", "image": True, "link": "CTA button URL",
            "carousel": False, "video": False, "short_video": False, "story": False, "article": False, "poll": False,
            "document": False},
}

_NO_POLL = None

# ── Platform defaults (apply to every format of the platform, overridden by FORMAT_OVERRIDES).
PLATFORM_DEFAULTS: dict[str, dict[str, Any]] = {
    "x": {
        "text": {"field": "text", "max": 280, "unit": "x_weighted", "required": True},
        "hashtags": {"max": 5, "recommended": 3, "placement": "inline or end",
                     "note": "1–3 hashtags perform best; 5 is Botwok's hard cap to avoid spam signals"},
        "mentions": {"max": 10, "severity": "warning"},
        "links": {"allowed": True, "clickable": True, "max": None, "url_weight": 23, "strategy": "inline",
                  "note": "Every URL counts as 23 characters. API posts containing a URL cost $0.20 vs $0.015 — "
                          "prefer one link, ideally in the last post of a thread."},
        "segments": {"supported": True, "kind": "thread", "max": 25, "per_segment_max": 280},
        "media": {"required": False, "min": 0, "max": 4, "types": ["image", "video", "gif"], "alt_text": True,
                  "alt_text_max": 1000},
        "poll": {"options_min": 2, "options_max": 4, "option_max_chars": 25, "duration_minutes_min": 5,
                 "duration_minutes_max": 10080},
        "hook": "Lead with the payoff in the first line (stat, contrarian take or promise). Threads: post 1 is the "
                "hook + promise, number posts '1/', end with a takeaway and a soft CTA.",
        "tone": "Punchy, conversational, one idea per post; short sentences; no hashtag walls.",
    },
    "linkedin": {
        "text": {"field": "text", "max": 3000, "unit": "chars", "required": True, "unverified": True},
        "hashtags": {"max": None, "recommended": 5, "placement": "end",
                     "note": "3–5 relevant hashtags at the end; never a hashtag wall"},
        "mentions": {"max": 20, "severity": "warning"},
        "links": {"allowed": True, "clickable": True, "max": None, "strategy": "inline or first comment",
                  "note": "No link scraping: supply article title/description/thumbnail in platform_metadata.link."},
        "segments": {"supported": False},
        "media": {"required": False, "min": 0, "max": 1, "types": ["image", "video", "document"], "alt_text": True,
                  "alt_text_max": 4086},
        "poll": {"options_min": 2, "options_max": 4, "option_max_chars": 30, "question_max_chars": 140,
                 "durations": ["ONE_DAY", "THREE_DAYS", "SEVEN_DAYS", "FOURTEEN_DAYS"]},
        "hook": "First two lines must earn the 'see more' click (~210 chars visible). Use line-break rhythm, short "
                "paragraphs, a clear point of view; close with a question or CTA.",
        "tone": "Professional but human; first person or brand 'we'; insight-led; minimal emoji.",
    },
    "instagram": {
        "text": {"field": "text", "max": 2200, "unit": "chars", "required": False},
        "hashtags": {"max": 30, "recommended": 5, "placement": "end of caption or first comment",
                     "note": "Hard limit 30; 3–5 targeted hashtags recommended, separated from the caption body"},
        "mentions": {"max": 20, "severity": "error"},
        "links": {"allowed": False, "clickable": False, "max": None, "strategy": "link_in_bio",
                  "note": "Links in captions are not clickable — write 'link in bio' instead of pasting URLs."},
        "segments": {"supported": False},
        "media": {"required": True, "min": 1, "max": 1, "types": ["image", "video"], "image_mimes": ["image/jpeg"],
                  "alt_text": True, "alt_text_max": None,
                  "notes": "JPEG only, aspect 4:5–1.91:1, ≤ 8 MB, public URL; alt text supported on images only"},
        "poll": _NO_POLL,
        "hook": "First 125 characters show before 'more' — open with the hook, not the brand name. Save/share prompts "
                "work well; CTA 'link in bio'.",
        "tone": "Visual-first, warm, scannable; line breaks; emoji only if the brand voice allows.",
    },
    "threads": {
        "text": {"field": "text", "max": 500, "unit": "threads", "required": False},
        "hashtags": {"max": None, "recommended": 1, "placement": "inline",
                     "note": "Threads links a single topic tag per post; use at most one"},
        "mentions": {"max": 10, "severity": "warning"},
        "links": {"allowed": True, "clickable": True, "max": 5, "strategy": "inline",
                  "note": "At most 5 links per post; text-only posts can carry a link_attachment preview."},
        "segments": {"supported": True, "kind": "reply_chain", "max": 25, "per_segment_max": 500,
                     "unverified": True},
        "media": {"required": False, "min": 0, "max": 1, "types": ["image", "video"], "alt_text": True,
                  "alt_text_max": None},
        "poll": {"options_min": 2, "options_max": 4, "option_max_chars": 25, "unverified": True},
        "hook": "Conversational opener; one thought per post; invite replies.",
        "tone": "Casual, conversational, lightly opinionated.",
    },
    "facebook": {
        "text": {"field": "text", "max": 63206, "unit": "chars", "required": False},
        "hashtags": {"max": None, "recommended": 3, "placement": "end", "note": "Hashtags matter little on Facebook; 0–3"},
        "mentions": {"max": 20, "severity": "warning"},
        "links": {"allowed": True, "clickable": True, "max": None, "strategy": "inline (preview auto-scraped)",
                  "note": "Link preview is scraped from the URL; custom preview overrides are unsupported."},
        "segments": {"supported": False},
        "media": {"required": False, "min": 0, "max": 1, "types": ["image", "video"], "alt_text": False,
                  "notes": "Alt text on Page photos is unverified via API"},
        "poll": _NO_POLL,
        "hook": "Open with a relatable question or story; keep the key message in the first 2 lines (~80 chars "
                "visible on mobile).",
        "tone": "Friendly, community-oriented, conversational.",
    },
    "tiktok": {
        "text": {"field": "text", "max": 2200, "unit": "utf16", "required": False},
        "hashtags": {"max": None, "recommended": 5, "placement": "end of caption",
                     "note": "3–5 niche + broad hashtags inside the caption limit"},
        "mentions": {"max": 10, "severity": "warning"},
        "links": {"allowed": False, "clickable": False, "max": None, "strategy": "link_in_bio",
                  "note": "Caption links are not clickable; point to the profile link."},
        "segments": {"supported": True, "kind": "script_scenes", "max": 60, "per_segment_max": None},
        "media": {"required": True, "min": 1, "max": 1, "types": ["video"], "alt_text": False},
        "poll": _NO_POLL,
        "hook": "Hook in the first 1–2 seconds (on-screen text + spoken line); pattern interrupt; payoff before 15 s.",
        "tone": "Native, energetic, creator-style; no corporate voice; no watermarks/promotional overlays.",
    },
    "youtube": {
        "text": {"field": "text", "max": 5000, "unit": "utf8_bytes", "required": False},
        "title": {"max": 100, "unit": "chars", "required": True},
        "tags": {"max_total_chars": 500},
        "hashtags": {"max": 15, "recommended": 3, "placement": "description (first 3 show above the title)",
                     "note": "More than 15 hashtags makes YouTube ignore all of them"},
        "mentions": {"max": 20, "severity": "warning"},
        "links": {"allowed": True, "clickable": True, "max": None, "strategy": "description",
                  "note": "Clickable links in descriptions may need channel verification."},
        "segments": {"supported": True, "kind": "chapters", "max": 100, "per_segment_max": None},
        "media": {"required": True, "min": 1, "max": 1, "types": ["video"], "alt_text": False},
        "poll": _NO_POLL,
        "forbidden_chars": ["<", ">"],
        "forbidden_chars_fields": ["title", "text"],
        "hook": "Title: specific benefit + curiosity, front-load keywords (≤ 70 chars visible). Description: 2-line "
                "summary with keywords, then chapters (00:00 …), links, hashtags.",
        "tone": "Clear, keyword-aware, viewer-benefit focused.",
    },
    "pinterest": {
        "text": {"field": "text", "max": 800, "unit": "chars", "required": False},
        "title": {"max": 100, "unit": "chars", "required": False},
        "hashtags": {"max": 20, "recommended": 5, "placement": "end of description",
                     "note": "Keywords matter more than hashtags on Pinterest"},
        "mentions": {"max": 0, "severity": "warning"},
        "links": {"allowed": True, "clickable": False, "max": None, "strategy": "destination link",
                  "link_max_chars": 2048,
                  "note": "Put the URL in platform_metadata.link (destination); links in descriptions are not clickable."},
        "segments": {"supported": False},
        "media": {"required": True, "min": 1, "max": 1, "types": ["image", "video"], "alt_text": True,
                  "alt_text_max": 500},
        "poll": _NO_POLL,
        "hook": "Keyword-rich, search-style title; description answers 'why save this?'.",
        "tone": "Inspirational, practical, search-optimized.",
    },
    "gbp": {
        "text": {"field": "text", "max": 1500, "unit": "chars", "required": True, "unverified": True},
        "hashtags": {"max": None, "recommended": 0, "placement": "none", "note": "Hashtags have no function on GBP posts"},
        "mentions": {"max": 0, "severity": "warning"},
        "links": {"allowed": True, "clickable": False, "max": None, "strategy": "cta_button",
                  "note": "Use platform_metadata.call_to_action {action_type, url}; inline URLs are not clickable."},
        "segments": {"supported": False},
        "media": {"required": False, "min": 0, "max": 1, "types": ["image"], "alt_text": False,
                  "notes": "Media by public URL only; multi-image count unverified"},
        "poll": _NO_POLL,
        "hook": "Lead with the local offer/news and a concrete reason to act now.",
        "tone": "Local, helpful, direct; include the CTA button.",
    },
}

# ── (platform, format) overrides — deep-merged over PLATFORM_DEFAULTS.
FORMAT_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("x", "text"): {"media": {"max": 0}},
    ("x", "image"): {"media": {"min": 1, "max": 4, "types": ["image", "gif"]}, "text": {"required": False}},
    ("x", "carousel"): {"media": {"min": 2, "max": 4, "types": ["image", "gif"]}, "text": {"required": False}},
    ("x", "video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"]}, "text": {"required": False}},
    ("x", "short_video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"]}, "text": {"required": False}},
    ("x", "poll"): {"media": {"max": 0}, "poll_required": True},
    ("x", "link"): {"link_required": True},
    ("linkedin", "text"): {"media": {"max": 0}},
    ("linkedin", "image"): {"media": {"required": True, "min": 1, "max": 1, "types": ["image"]}},
    ("linkedin", "carousel"): {"media": {"required": True, "min": 2, "max": 20, "types": ["image"],
                                          "notes": "MultiImage 2–20 (organic only); for swipeable PDFs use format=document"}},
    ("linkedin", "document"): {"media": {"required": True, "min": 1, "max": 1, "types": ["document"],
                                          "notes": "PDF/PPT/DOC ≤ 100 MB and ≤ 300 pages"},
                               "platform_metadata_required": ["document_title"]},
    ("linkedin", "video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"], "notes": "≤ 5 GB"}},
    ("linkedin", "short_video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"]}},
    ("linkedin", "article"): {"link_required": True},
    ("linkedin", "link"): {"link_required": True},
    ("linkedin", "poll"): {"media": {"max": 0}, "poll_required": True},
    ("instagram", "image"): {"media": {"min": 1, "max": 1, "types": ["image"]}},
    ("instagram", "carousel"): {"media": {"min": 2, "max": 10, "types": ["image", "video"]},
                                "segments": {"supported": True, "kind": "slides", "max": 10, "per_segment_max": None}},
    ("instagram", "short_video"): {"media": {"min": 1, "max": 1, "types": ["video"], "alt_text": False,
                                              "notes": "Reels 3 s–15 min, ≤ 300 MB"}},
    ("instagram", "story"): {"media": {"min": 1, "max": 1, "types": ["image", "video"], "alt_text": False,
                                        "notes": "Image JPEG ≤ 8 MB 9:16; video 3–60 s ≤ 100 MB"},
                             "text": {"max": 0}, "hashtags": {"max": 0, "recommended": 0}},
    ("threads", "image"): {"media": {"required": True, "min": 1, "max": 1, "types": ["image"]}},
    ("threads", "carousel"): {"media": {"required": True, "min": 2, "max": 20, "types": ["image", "video"]}},
    ("threads", "video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"], "notes": "≤ 5 min, ≤ 1 GB"}},
    ("threads", "short_video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"]}},
    ("threads", "text"): {"text": {"required": True}, "media": {"max": 0}},
    ("threads", "poll"): {"poll_required": True, "media": {"max": 0}},
    ("threads", "link"): {"link_required": True},
    ("facebook", "image"): {"media": {"required": True, "min": 1, "max": 1, "types": ["image"]}},
    ("facebook", "carousel"): {"media": {"required": True, "min": 2, "max": None, "types": ["image"],
                                          "notes": "multi-photo; max count unverified"}},
    ("facebook", "short_video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"],
                                             "notes": "Reels 3–90 s 9:16, 30 per 24 h"}},
    ("facebook", "video"): {"media": {"required": True, "min": 1, "max": 1, "types": ["video"]}},
    ("facebook", "story"): {"media": {"required": True, "min": 1, "max": 1, "types": ["image", "video"],
                                       "notes": "video ≤ 60 s; stories cannot be natively scheduled"},
                            "text": {"max": 0}},
    ("facebook", "text"): {"text": {"required": True}, "media": {"max": 0}},
    ("facebook", "link"): {"link_required": True},
    ("tiktok", "carousel"): {
        "text": {"field": "text", "max": 4000, "unit": "utf16", "required": False},
        "title": {"max": 90, "unit": "utf16", "required": False},
        "media": {"required": True, "min": 1, "max": 35, "types": ["image"],
                  "notes": "PULL_FROM_URL from a verified domain, ≤ 20 MB each"},
        "segments": {"supported": True, "kind": "slides", "max": 35, "per_segment_max": None},
    },
    ("tiktok", "video"): {"media": {"notes": "≤ 4 GB"}},
    ("youtube", "short_video"): {"media": {"notes": "Shorts: ≤ 3 min, vertical or square"}},
    ("pinterest", "carousel"): {"media": {"min": 2, "max": 5, "types": ["image"]},
                                "segments": {"supported": True, "kind": "slides", "max": 5, "per_segment_max": None}},
    ("pinterest", "short_video"): {"media": {"types": ["video"], "notes": "video pin; specs unverified"}},
    ("gbp", "image"): {"media": {"required": True, "min": 1}},
    ("gbp", "link"): {"platform_metadata_required": ["call_to_action"]},
}

GENERIC_HOOKS = ("question", "contrarian statement", "surprising stat (sourced)", "promise/benefit", "story opener",
                 "list teaser ('3 ways…')")


def _norm(v: Any) -> str:
    if isinstance(v, Enum):
        v = v.value
    return str(v or "").strip().lower()


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def support_of(platform: Any, format: Any) -> bool | str:
    return SUPPORT.get(_norm(platform), {}).get(_norm(format), False)


def rules_for(platform: Any, format: Any) -> dict[str, Any]:
    """Resolved rules for a (platform, format) pair. Unknown platforms return a permissive generic rule set."""
    p, f = _norm(platform), _norm(format) or "text"
    base = PLATFORM_DEFAULTS.get(p)
    if base is None:
        base = {"text": {"field": "text", "max": None, "unit": "chars", "required": False},
                "hashtags": {"max": None, "recommended": None}, "mentions": {"max": None, "severity": "warning"},
                "links": {"allowed": True, "clickable": True, "max": None}, "segments": {"supported": False},
                "media": {"required": False, "min": 0, "max": None, "alt_text": False}, "poll": None,
                "hook": "", "tone": ""}
    r = _merge(base, FORMAT_OVERRIDES.get((p, f), {}))
    support = support_of(p, f)
    r.setdefault("title", None)
    r.setdefault("description", None)
    r.setdefault("tags", None)
    r.setdefault("forbidden_chars", [])
    r.setdefault("forbidden_chars_fields", [])
    r.setdefault("poll_required", False)
    r.setdefault("link_required", False)
    r.setdefault("platform_metadata_required", [])
    r.update({"platform": p, "format": f, "supported": bool(support),
              "support_note": support if isinstance(support, str) else None})
    notes: list[str] = []
    if r["text"].get("unverified"):
        notes.append(f"{p} text limit {r['text']['max']} is unverified (doc 26 '?')")
    if r.get("segments", {}).get("unverified"):
        notes.append(f"{p} segment chain limits are unverified")
    r["notes"] = notes
    return r


_UNIT_LABEL = {"chars": "characters", "x_weighted": "weighted characters (URLs = 23, emoji/CJK = 2)",
               "utf8_bytes": "UTF-8 bytes", "utf16": "UTF-16 characters", "threads": "characters (emoji count as bytes)"}


def describe_rules(platform: Any, format: Any) -> str:
    """Prompt-ready rule block for the writer/repurposer/critic."""
    r = rules_for(platform, format)
    p, f = r["platform"], r["format"]
    lines = [f"PLATFORM RULES — {p} / {f}"]
    if not r["supported"]:
        lines.append(f"- NOT SUPPORTED: {p} does not support format '{f}'. Choose a supported format.")
        return "\n".join(lines)
    if r["support_note"]:
        lines.append(f"- Format note: {r['support_note']}")
    t = r["text"]
    if t.get("max") == 0:
        lines.append("- No caption text for this format.")
    elif t.get("max"):
        unit = _UNIT_LABEL.get(t.get("unit", "chars"), t.get("unit"))
        lines.append(f"- Text ({t.get('field', 'text')}): max {t['max']} {unit}"
                     f"{' (required)' if t.get('required') else ''}{' [limit unverified]' if t.get('unverified') else ''}.")
    if r.get("title"):
        lines.append(f"- Title (platform_metadata.title): max {r['title']['max']} "
                     f"{_UNIT_LABEL.get(r['title'].get('unit', 'chars'))}{' (required)' if r['title'].get('required') else ''}.")
    if r.get("tags"):
        lines.append(f"- Tags (platform_metadata.tags): ≤ {r['tags']['max_total_chars']} characters in total "
                     "(commas count; tags with spaces count their quotes).")
    h = r["hashtags"]
    if h.get("max") == 0:
        lines.append("- Hashtags: none for this format.")
    else:
        hard = f"hard max {h['max']}" if h.get("max") else "no hard max"
        lines.append(f"- Hashtags: recommended {h.get('recommended')} ({hard}); placement: {h.get('placement', 'end')}. "
                     f"{h.get('note', '')}".rstrip())
    lk = r["links"]
    link_line = f"- Links: {lk.get('note', '')}"
    if lk.get("max"):
        link_line += f" Max {lk['max']} links."
    lines.append(link_line)
    sg = r.get("segments") or {}
    if sg.get("supported"):
        per = f", each ≤ {sg['per_segment_max']}" if sg.get("per_segment_max") else ""
        lines.append(f"- Segments ({sg.get('kind')}): up to {sg.get('max')}{per}; put them in `segments` in order.")
    m = r["media"]
    if m.get("max") == 0:
        lines.append("- Media: none for this format.")
    else:
        rng = f"{m.get('min', 0)}–{m['max']}" if m.get("max") else f"≥ {m.get('min', 0)}"
        lines.append(f"- Media: {rng} item(s), types {', '.join(m.get('types', []))}"
                     f"{' (required)' if m.get('required') else ''}. {m.get('notes', '')}".rstrip())
        if m.get("alt_text"):
            lines.append("- Alt text: required for every image (describe the image; no keyword stuffing).")
    if r.get("poll") and (f == "poll" or r.get("poll_required")):
        pl = r["poll"]
        lines.append(f"- Poll (platform_metadata.poll): {pl.get('options_min')}–{pl.get('options_max')} options, each ≤ "
                     f"{pl.get('option_max_chars')} chars"
                     + (f"; duration {pl['duration_minutes_min']}–{pl['duration_minutes_max']} minutes"
                        if pl.get("duration_minutes_min") else "")
                     + (f"; duration one of {', '.join(pl['durations'])}" if pl.get("durations") else "") + ".")
    if r.get("forbidden_chars"):
        lines.append(f"- Forbidden characters in {', '.join(r['forbidden_chars_fields'])}: "
                     f"{' '.join(r['forbidden_chars'])}.")
    if r.get("platform_metadata_required"):
        lines.append(f"- Required platform_metadata: {', '.join(r['platform_metadata_required'])}.")
    if r.get("hook"):
        lines.append(f"- Hook convention: {r['hook']}")
    if r.get("tone"):
        lines.append(f"- Tone default: {r['tone']} (brand voice overrides).")
    for n in r["notes"]:
        lines.append(f"- Note: {n}")
    return "\n".join(lines)


def supported_formats(platform: Any) -> list[str]:
    return [f for f, v in SUPPORT.get(_norm(platform), {}).items() if v]
