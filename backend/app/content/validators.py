"""Deterministic variant validation against the platform-rule table (doc 09 §9.4).

``validate_variant`` never calls the network. The publishing adapter's ``validate_content()`` remains the final
authority at scheduling time; this catches most rejects early. Severity: ``error`` (blocks scheduling),
``warning`` (shown to the user), ``info``.

Variant dict keys understood: ``text``, ``segments`` (list[str | {text, ...}]), ``hashtags`` (list[str]),
``media_plan`` (``{items|slides: [{kind, mime, alt_text, ...}]}``), ``platform_metadata`` (title, tags, link,
poll{options, duration_minutes|duration}, call_to_action, document_title, …) and ``assets`` (attached
``content_assets``: ``[{kind, mime, alt_text, role, position}]``; when present it overrides ``media_plan``).
Hashtags listed in ``hashtags`` but absent from the text are assumed to be appended to the text at publish time,
so they count toward the length limit.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from app.content.platform_rules import rules_for

URL_RE = re.compile(
    r"(?:(?:https?://|www\.)[^\s<>\"']+)"
    r"|(?:\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{1,63})*"
    r"\.(?:com|org|net|io|co|ai|dev|app|edu|gov|us|uk|de|fr|ca|au|in|ly|me|info|biz|tv|gg|xyz)\b(?:/[^\s<>\"']*)?)",
    re.IGNORECASE,
)
HASHTAG_RE = re.compile(r"(?<![\w&#])#(\w[\w]*)", re.UNICODE)
MENTION_RE = re.compile(r"(?<![\w@.])@([A-Za-z0-9_](?:[A-Za-z0-9_.]{0,62}[A-Za-z0-9_])?)")
VALID_TAG_RE = re.compile(r"^\w+$", re.UNICODE)
_TRAILING_PUNCT = ".,;:!?)]}'\""

# X weighting (twitter-text v3): code points in these ranges weigh 1, everything else 2.
_X_LIGHT_RANGES = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
_ZWJ = 0x200D
_VS = (0xFE0E, 0xFE0F)


def _is_emoji_cp(cp: int) -> bool:
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or 0x2190 <= cp <= 0x21FF
            or 0x2300 <= cp <= 0x23FF or cp in (0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D))


def _is_modifier(cp: int) -> bool:
    return cp in _VS or cp == 0x20E3 or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F


def _emoji_sequences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) index spans of emoji sequences (ZWJ joins, modifiers, flags, keycaps)."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if _is_emoji_cp(cp) and not _is_modifier(cp):
            j = i + 1
            if 0x1F1E6 <= cp <= 0x1F1FF and j < n and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF:
                j += 1  # flag pair
            while j < n:
                c = ord(text[j])
                if _is_modifier(c):
                    j += 1
                elif c == _ZWJ and j + 1 < n:
                    j += 2
                else:
                    break
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def find_urls(text: str) -> list[str]:
    out = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(_TRAILING_PUNCT)
        if "@" in text[max(0, m.start() - 1):m.start()]:
            continue  # part of an email address
        out.append(u)
    return out


def _url_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in URL_RE.finditer(text or ""):
        if m.start() > 0 and text[m.start() - 1] == "@":
            continue
        u = m.group(0).rstrip(_TRAILING_PUNCT)
        spans.append((m.start(), m.start() + len(u)))
    return spans


def x_weighted_length(text: str, url_weight: int = 23) -> int:
    """X/Twitter weighted length: URL = 23, emoji sequence = 2, CJK etc. = 2, Latin = 1 (NFC-normalized)."""
    text = unicodedata.normalize("NFC", text or "")
    total = 0
    url_spans = _url_spans(text)
    covered = [False] * len(text)
    for s, e in url_spans:
        total += url_weight
        for k in range(s, e):
            covered[k] = True
    for s, e in _emoji_sequences(text):
        if not any(covered[s:e]):
            total += 2
            for k in range(s, e):
                covered[k] = True
    for idx, ch in enumerate(text):
        if covered[idx]:
            continue
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF:
            continue
        total += 1 if any(lo <= cp <= hi for lo, hi in _X_LIGHT_RANGES) else 2
    return total


def threads_length(text: str) -> int:
    """Threads counts characters, with emoji counted as their UTF-8 byte length."""
    text = text or ""
    total, covered = 0, [False] * len(text)
    for s, e in _emoji_sequences(text):
        total += len(text[s:e].encode("utf-8"))
        for k in range(s, e):
            covered[k] = True
    total += sum(1 for i in range(len(text)) if not covered[i])
    return total


def measure(text: str, unit: str = "chars", url_weight: int = 23) -> int:
    text = text or ""
    if unit == "x_weighted":
        return x_weighted_length(text, url_weight)
    if unit == "utf8_bytes":
        return len(text.encode("utf-8"))
    if unit == "utf16":
        return len(text.encode("utf-16-le")) // 2
    if unit == "threads":
        return threads_length(text)
    return len(text)


def normalize_hashtag(tag: str) -> str:
    return (tag or "").strip().lstrip("#").strip()


def extract_hashtags(text: str) -> list[str]:
    return [m.group(1) for m in HASHTAG_RE.finditer(text or "")]


def extract_mentions(text: str) -> list[str]:
    return [m.group(1) for m in MENTION_RE.finditer(text or "")]


def compose_text(text: str | None, hashtags: Iterable[str] | None) -> str:
    """Text as it will be published: hashtags not already in the text are appended on a new paragraph."""
    text = text or ""
    present = {h.casefold() for h in extract_hashtags(text)}
    missing = []
    for h in hashtags or []:
        t = normalize_hashtag(h)
        if t and t.casefold() not in present:
            missing.append(f"#{t}")
            present.add(t.casefold())
    if not missing:
        return text
    return f"{text}\n\n{' '.join(missing)}" if text else " ".join(missing)


def _segment_text(seg: Any) -> str:
    if isinstance(seg, str):
        return seg
    if isinstance(seg, dict):
        for k in ("text", "body", "caption", "content"):
            if isinstance(seg.get(k), str):
                return seg[k]
    return ""


def _media_items(variant: dict[str, Any]) -> list[dict[str, Any]]:
    assets = variant.get("assets")
    if isinstance(assets, list) and assets:
        skip = ("thumbnail", "cover", "subtitle")
        return [a if isinstance(a, dict) else {} for a in assets if not (isinstance(a, dict) and a.get("role") in skip)]
    plan = variant.get("media_plan") or {}
    if isinstance(plan, list):
        return [x if isinstance(x, dict) else {} for x in plan]
    if isinstance(plan, dict):
        for key in ("items", "slides", "assets", "media"):
            if isinstance(plan.get(key), list):
                return [x if isinstance(x, dict) else {} for x in plan[key]]
    return []


def _kind_of(item: dict[str, Any]) -> str:
    k = str(item.get("kind") or item.get("type") or "").lower()
    if k:
        return k
    mime = str(item.get("mime") or "").lower()
    if mime.startswith("image/gif"):
        return "gif"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime:
        return "document"
    return ""


def _issue(code: str, message: str, field: str | None = None, severity: str = "error") -> dict[str, Any]:
    return {"code": code, "message": message, "field": field, "severity": severity}


def youtube_tags_length(tags: Iterable[str]) -> int:
    """YouTube counts commas between tags and the implied quotes around tags that contain spaces."""
    tags = [t for t in (tags or []) if t]
    n = sum(len(t) + (2 if " " in t else 0) for t in tags)
    return n + max(0, len(tags) - 1)


def validate_variant(platform: Any, format: Any, variant: dict[str, Any], *,
                     banned_hashtags: Iterable[str] | None = None) -> dict[str, Any]:
    """Validate one variant. Returns ``{ok, issues[{code, message, field, severity}], stats}``."""
    r = rules_for(platform, format)
    p, f = r["platform"], r["format"]
    issues: list[dict[str, Any]] = []
    variant = variant or {}
    meta = variant.get("platform_metadata") or {}
    hashtags_list = [normalize_hashtag(h) for h in (variant.get("hashtags") or []) if normalize_hashtag(h)]
    segments = list(variant.get("segments") or [])
    seg_texts = [_segment_text(s) for s in segments]
    raw_text = variant.get("text") or ""
    full_text = compose_text(raw_text, hashtags_list)
    tr = r["text"]
    unit = tr.get("unit", "chars")
    url_weight = r["links"].get("url_weight") or 23
    sg = r.get("segments") or {}

    if not r["supported"]:
        issues.append(_issue("format_not_supported", f"{p} does not support the '{f}' format", "format"))

    # ── text length
    is_thread = bool(sg.get("supported")) and sg.get("kind") in ("thread", "reply_chain") and len(seg_texts) > 0
    text_len = measure(full_text, unit, url_weight)
    limit = tr.get("max")
    if limit == 0 and raw_text.strip():
        issues.append(_issue("text_ignored", f"{p} {f} posts do not carry caption text; it will be ignored", "text",
                             "warning"))
    elif limit and text_len > limit:
        unit_label = {"utf8_bytes": "bytes", "x_weighted": "weighted characters"}.get(unit, "characters")
        code = "description_too_long_bytes" if unit == "utf8_bytes" else "text_too_long"
        sev = "warning" if tr.get("unverified") else "error"
        issues.append(_issue(code, f"{p} {('description' if p == 'youtube' else 'text')} is limited to {limit} "
                                   f"{unit_label} ({text_len})", "text", sev))
    if tr.get("required") and not raw_text.strip() and not seg_texts and f not in ("poll",):
        issues.append(_issue("text_required", f"{p} {f} posts need text", "text"))
    if f == "poll" and not raw_text.strip() and not (meta.get("poll") or {}).get("question"):
        issues.append(_issue("text_required", "Poll posts need a question (text)", "text"))

    # ── segments (threads / reply chains / slides / chapters)
    if seg_texts:
        if not sg.get("supported"):
            issues.append(_issue("segments_not_supported", f"{p} {f} does not use segments; only `text` is published",
                                 "segments", "warning"))
        else:
            mx = sg.get("max")
            if mx and len(seg_texts) > mx:
                issues.append(_issue("too_many_segments", f"{p} allows at most {mx} {sg.get('kind')} segments "
                                                          f"({len(seg_texts)})", "segments",
                                     "warning" if sg.get("unverified") else "error"))
            per = sg.get("per_segment_max")
            if per:
                for i, st in enumerate(seg_texts):
                    seg_full = compose_text(st, hashtags_list) if (i == 0 and not raw_text.strip()) else st
                    n = measure(seg_full, unit, url_weight)
                    if n > per:
                        issues.append(_issue("segment_too_long", f"Segment {i + 1} is {n} > {per}", f"segments[{i}]"))
                    if not st.strip():
                        issues.append(_issue("segment_empty", f"Segment {i + 1} is empty", f"segments[{i}]"))

    all_text = "\n".join([full_text, *seg_texts])

    # ── hashtags
    tags_in_text = extract_hashtags(all_text)
    uniq: dict[str, str] = {}
    for t in [*hashtags_list, *tags_in_text]:
        uniq.setdefault(t.casefold(), t)
    hcount = len(uniq)
    hr = r["hashtags"]
    if hr.get("max") is not None and hcount > hr["max"]:
        issues.append(_issue("too_many_hashtags", f"{p} allows at most {hr['max']} hashtags ({hcount})", "hashtags"))
    elif hr.get("recommended") is not None and hcount > hr["recommended"]:
        issues.append(_issue("hashtags_above_recommended", f"{hcount} hashtags; {hr['recommended']} recommended on {p}",
                             "hashtags", "warning"))
    for i, h in enumerate(hashtags_list):
        if not VALID_TAG_RE.match(h):
            issues.append(_issue("invalid_hashtag", f"'#{h}' contains spaces or punctuation", f"hashtags[{i}]"))
    banned = {normalize_hashtag(b).casefold() for b in (banned_hashtags or []) if normalize_hashtag(b)}
    for key, original in uniq.items():
        if key in banned:
            issues.append(_issue("banned_hashtag", f"#{original} is banned for this brand", "hashtags"))

    # ── mentions
    mentions = set(m.casefold() for m in extract_mentions(all_text))
    mr = r["mentions"]
    if mr.get("max") is not None and len(mentions) > mr["max"]:
        issues.append(_issue("too_many_mentions", f"{p} allows at most {mr['max']} mentions ({len(mentions)})", "text",
                             mr.get("severity", "warning")))

    # ── links
    urls = find_urls(all_text)
    lk = r["links"]
    if urls:
        if lk.get("clickable") is False:
            hint = " — use 'link in bio'" if lk.get("strategy") == "link_in_bio" else (
                " — use platform_metadata.link" if p == "pinterest" else
                " — use the call-to-action button" if p == "gbp" else "")
            issues.append(_issue("link_not_clickable", f"Links in {p} text are not clickable{hint}", "text", "warning"))
        if lk.get("max") and len(urls) > lk["max"]:
            issues.append(_issue("too_many_links", f"{p} allows at most {lk['max']} links ({len(urls)})", "text"))
        if p == "x":
            issues.append(_issue("x_url_cost", "Posts containing a URL cost $0.20 via the X API (vs $0.015)", "text",
                                 "info"))
    if r.get("link_required") and not urls and not meta.get("link") and not meta.get("call_to_action"):
        issues.append(_issue("link_required", f"{p} {f} posts need a link", "platform_metadata.link"))
    link = meta.get("link")
    link_url = link.get("url") if isinstance(link, dict) else link
    if isinstance(link_url, str) and lk.get("link_max_chars") and len(link_url) > lk["link_max_chars"]:
        issues.append(_issue("link_too_long", f"Destination link exceeds {lk['link_max_chars']} characters",
                             "platform_metadata.link"))

    # ── title / tags / secondary fields
    title = meta.get("title")
    if r.get("title"):
        tt = r["title"]
        if tt.get("required") and not (title or "").strip():
            issues.append(_issue("title_required", f"{p} needs a title", "platform_metadata.title"))
        if title and measure(title, tt.get("unit", "chars")) > tt["max"]:
            issues.append(_issue("title_too_long", f"{p} titles are limited to {tt['max']} characters "
                                                   f"({measure(title, tt.get('unit', 'chars'))})",
                                 "platform_metadata.title"))
    if r.get("tags") and meta.get("tags"):
        tl = youtube_tags_length(meta.get("tags") or [])
        if tl > r["tags"]["max_total_chars"]:
            issues.append(_issue("tags_too_long", f"Tags total {tl} > {r['tags']['max_total_chars']} characters",
                                 "platform_metadata.tags"))
    for fc_field in r.get("forbidden_chars_fields") or []:
        val = title if fc_field == "title" else raw_text if fc_field == "text" else meta.get(fc_field)
        if isinstance(val, str):
            bad = sorted({c for c in r["forbidden_chars"] if c in val})
            if bad:
                issues.append(_issue("forbidden_characters", f"{p} {fc_field} cannot contain {' '.join(bad)}",
                                     "platform_metadata.title" if fc_field == "title" else fc_field))
    for req in r.get("platform_metadata_required") or []:
        if not meta.get(req):
            issues.append(_issue("metadata_required", f"platform_metadata.{req} is required for {p} {f}",
                                 f"platform_metadata.{req}", "warning"))

    # ── media
    media = _media_items(variant)
    mr_ = r["media"]
    count = len(media)
    if f == "carousel" and count == 0 and seg_texts and sg.get("kind") == "slides":
        count = len(seg_texts)  # slides planned but not rendered yet
    if mr_.get("max") == 0 and count:
        issues.append(_issue("media_not_allowed", f"{p} {f} posts cannot carry media", "media"))
    else:
        if mr_.get("max") and count > mr_["max"]:
            issues.append(_issue("too_many_media", f"{p} {f} allows at most {mr_['max']} media items ({count})", "media"))
        if count and mr_.get("min") and count < mr_["min"]:
            issues.append(_issue("too_few_media", f"{p} {f} needs at least {mr_['min']} media items ({count})", "media"))
        if mr_.get("required") and count == 0:
            issues.append(_issue("media_required", f"{p} {f} posts need media attached before scheduling", "media",
                                 "warning"))
    allowed_types = set(mr_.get("types") or [])
    image_mimes = set(mr_.get("image_mimes") or [])
    for i, item in enumerate(media):
        kind = _kind_of(item)
        if allowed_types and kind and kind not in allowed_types and not (kind == "gif" and "image" in allowed_types):
            issues.append(_issue("unsupported_media_type", f"{p} {f} does not accept {kind}", f"assets[{i}]"))
        mime = str(item.get("mime") or "").lower()
        if kind == "image" and image_mimes and mime and mime not in image_mimes:
            issues.append(_issue("unsupported_media_type", f"{p} images must be {', '.join(sorted(image_mimes))} ({mime})",
                                 f"assets[{i}]"))
        if kind in ("image", "gif", ""):
            alt = (item.get("alt_text") or "").strip()
            if not alt:
                issues.append(_issue("missing_alt_text", "Alt text required", f"assets[{i}].alt_text",
                                     "error" if mr_.get("alt_text") else "warning"))
            elif mr_.get("alt_text_max") and len(alt) > mr_["alt_text_max"]:
                issues.append(_issue("alt_text_too_long", f"Alt text exceeds {mr_['alt_text_max']} characters",
                                     f"assets[{i}].alt_text"))

    # ── poll
    poll = meta.get("poll")
    if f == "poll" or poll:
        pr = r.get("poll")
        if not pr:
            issues.append(_issue("poll_not_supported", f"{p} does not support polls via API", "platform_metadata.poll"))
        elif not isinstance(poll, dict):
            issues.append(_issue("poll_required", "platform_metadata.poll {options[], duration} is required",
                                 "platform_metadata.poll"))
        else:
            opts = [str(o.get("label") if isinstance(o, dict) else o) for o in (poll.get("options") or [])]
            if not (pr["options_min"] <= len(opts) <= pr["options_max"]):
                issues.append(_issue("poll_invalid_options", f"Polls need {pr['options_min']}–{pr['options_max']} "
                                                             f"options ({len(opts)})", "platform_metadata.poll.options"))
            for i, o in enumerate(opts):
                if not o.strip():
                    issues.append(_issue("poll_option_empty", f"Option {i + 1} is empty",
                                         f"platform_metadata.poll.options[{i}]"))
                elif pr.get("option_max_chars") and len(o) > pr["option_max_chars"]:
                    issues.append(_issue("poll_option_too_long", f"Option {i + 1} exceeds {pr['option_max_chars']} "
                                                                 "characters", f"platform_metadata.poll.options[{i}]"))
            if len(set(o.strip().casefold() for o in opts)) < len(opts):
                issues.append(_issue("poll_duplicate_options", "Poll options must be distinct",
                                     "platform_metadata.poll.options"))
            if pr.get("duration_minutes_min") is not None:
                d = poll.get("duration_minutes")
                if not isinstance(d, int) or not (pr["duration_minutes_min"] <= d <= pr["duration_minutes_max"]):
                    issues.append(_issue("poll_invalid_duration", f"duration_minutes must be "
                                                                  f"{pr['duration_minutes_min']}–{pr['duration_minutes_max']}",
                                         "platform_metadata.poll.duration_minutes"))
            if pr.get("durations"):
                d = poll.get("duration")
                if d not in pr["durations"]:
                    issues.append(_issue("poll_invalid_duration", f"duration must be one of {', '.join(pr['durations'])}",
                                         "platform_metadata.poll.duration"))
            q = poll.get("question") or raw_text
            if pr.get("question_max_chars") and q and len(q) > pr["question_max_chars"]:
                issues.append(_issue("poll_question_too_long", f"Poll question exceeds {pr['question_max_chars']} "
                                                               "characters", "platform_metadata.poll.question"))

    ok = not any(i["severity"] == "error" for i in issues)
    return {"ok": ok, "issues": issues,
            "stats": {"length": text_len, "limit": limit, "unit": unit, "hashtags": hcount, "mentions": len(mentions),
                      "links": len(urls), "segments": len(seg_texts), "media": len(media),
                      "is_thread": is_thread}}


def normalize_for_fingerprint(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fingerprint(text: str | None, media_hashes: Iterable[str] | None = None, account_id: Any = None) -> str:
    """Duplicate-content fingerprint (doc 19 §19.7): normalized text + sorted media hashes + target account."""
    h = hashlib.sha256()
    h.update(normalize_for_fingerprint(text or "").encode("utf-8"))
    h.update(b"\x1f")
    for mh in sorted(str(m).lower() for m in (media_hashes or []) if m):
        h.update(mh.encode())
        h.update(b"\x1e")
    h.update(b"\x1f")
    h.update(str(account_id or "").encode())
    return h.hexdigest()
