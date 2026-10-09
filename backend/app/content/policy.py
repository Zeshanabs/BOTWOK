"""Deterministic content policy checks + risk scoring (doc 19 §19.6–19.7).

``policy_check`` runs without any LLM: forbidden topics, banned words, a keyword-based sensitive-topic classifier,
claims policy (guarantee language), PII and secret regexes, link policy, missing disclaimers and instruction leakage.
``risk_from`` combines the deterministic policy result with critic and fact-check output into ``low|medium|high``.

Flag shape: ``{code, category, severity: block|high|medium|low, message, match}``. ``block`` means a policy
violation: content is routed to ``rejected`` with reasons (doc 19 §19.7) and can be revised by an editor.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from app.content.validators import extract_hashtags, find_urls

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "block": 3}
REGULATED_CATEGORIES = {"health_medical", "financial_advice", "legal"}
REGULATED_COMPLIANCE_HINTS = ("health", "hipaa", "medical", "pharma", "financ", "finra", "sec", "invest", "legal", "law",
                              "insurance", "gdpr")

# ── sensitive-topic classifier: category → keyword patterns (word-boundary, case-insensitive)
SENSITIVE_KEYWORDS: dict[str, list[str]] = {
    "health_medical": [r"cure[sd]?", r"treatments?", r"diagnos\w*", r"disease", r"symptoms?", r"vaccines?",
                       r"prescription", r"medication", r"FDA", r"clinical(ly)?", r"cancer", r"diabetes", r"weight loss",
                       r"supplements?", r"therapy", r"anxiety", r"depression", r"covid", r"immune system", r"detox"],
    "financial_advice": [r"invest(ing|ment|ments)?", r"stock market", r"stocks to buy", r"crypto(currency)?",
                         r"bitcoin", r"investment returns?", r"ROI", r"portfolio", r"trading", r"financial advice", r"retirement", r"passive income",
                         r"get rich", r"double your money", r"interest rates?", r"loans?", r"credit score"],
    "legal": [r"legal advice", r"lawsuits?", r"sue", r"attorney", r"lawyer", r"liabilit(y|ies)", r"in court",
              r"legally", r"compliance requirement", r"regulation(s)?", r"contract law"],
    "politics": [r"election", r"vote for", r"democrats?", r"republicans?", r"candidate", r"senator", r"congress(man|woman)?",
                 r"parliament", r"political part(y|ies)", r"left[- ]wing", r"right[- ]wing", r"impeach\w*", r"ballot"],
    "minors": [r"children", r"kids", r"minors?", r"under 1[3-8]", r"teen(s|agers?)?", r"toddlers?", r"school ?kids"],
    "violence": [r"shootings?", r"weapons?", r"guns?", r"bomb(s|ing)?", r"murder", r"assault",
                 r"terroris\w+", r"massacre", r"stab(bing|bed)?"],
    "hate": [r"subhuman", r"inferior race", r"ethnic cleansing", r"go back to your country", r"hate speech",
             r"white power", r"racial purity"],
    "adult": [r"porn\w*", r"nsfw", r"xxx", r"nude(s)?", r"explicit content", r"onlyfans", r"sexual(ly)?", r"erotic"],
}
_SENSITIVE_RE = {cat: re.compile(r"\b(?:" + "|".join(pats) + r")\b", re.IGNORECASE) for cat, pats in SENSITIVE_KEYWORDS.items()}
_CATEGORY_SEVERITY = {"health_medical": "medium", "financial_advice": "medium", "legal": "medium", "politics": "medium",
                      "minors": "medium", "violence": "high", "hate": "block", "adult": "high"}

# claims policy: outcome guarantees / absolute claims
GUARANTEE_RE = re.compile(
    r"\b(guarantee[sd]?|guaranteeing|100\s?%|risk[- ]free|no risk|zero risk|always works|never fails|proven to|"
    r"clinically proven|scientifically proven|miracle|instant results|overnight results|promise[sd]?|"
    r"best in the world|world'?s best|#1|number one|cure[sd]? for|permanent(ly)? (fix|cure))\b", re.IGNORECASE)
HEALTH_CLAIM_RE = re.compile(r"\b(cures?|heals?|prevents?|treats?|reverses?|eliminates?)\b[^.!?\n]{0,60}"
                             r"\b(disease|cancer|diabetes|anxiety|depression|covid|virus|infection|pain|illness)\b",
                             re.IGNORECASE)
FINANCIAL_CLAIM_RE = re.compile(r"\b(guaranteed|assured|risk[- ]free)\b[^.!?\n]{0,40}\b(returns?|profits?|income|gains?)\b"
                                r"|\b(\d{2,4}\s?%)\s+(returns?|profit|gains?)\b", re.IGNORECASE)

# PII
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<![\w/])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3,4}[\s.-]\d{3,4}(?![\w/])")
SSN_RE = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")

# secrets (doc 19 §19.6 output filters)
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_key": re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{20,}"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "stripe_key": re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "botwok_api_key": re.compile(r"\bbw_live_[A-Za-z0-9]+_[A-Za-z0-9]{16,}"),
    "bearer_token": re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._\-]{24,}"),
    "password_assignment": re.compile(r"\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|client[_-]?secret)"
                                      r"\s*[:=]\s*\S{6,}", re.IGNORECASE),
}

LINK_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly",
                   "shorturl.at", "tiny.cc", "rb.gy", "t.ly", "s.id"}
INSTRUCTION_LEAK_RE = re.compile(r"\b(ignore (all |any )?(previous|prior) instructions|system prompt|as an ai (language )?"
                                 r"model|i am an ai|you are now|developer mode|<\/?untrusted)\b", re.IGNORECASE)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _flag(code: str, category: str, severity: str, message: str, match: str | None = None) -> dict[str, Any]:
    return {"code": code, "category": category, "severity": severity, "message": message,
            "match": (match[:80] if match else None)}


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [v]


def _topic_pattern(topic: str) -> re.Pattern[str] | None:
    topic = (topic or "").strip()
    if not topic:
        return None
    if len(topic) > 2 and topic.startswith("/") and topic.endswith("/"):
        try:
            return re.compile(topic[1:-1], re.IGNORECASE)
        except re.error:
            return None
    if topic.lower().startswith("re:"):
        try:
            return re.compile(topic[3:], re.IGNORECASE)
        except re.error:
            return None
    return re.compile(r"(?<!\w)" + re.escape(topic) + r"(?!\w)", re.IGNORECASE)


def _domain(url: str) -> str:
    u = url if "://" in url else f"http://{url}"
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def policies_from_brand_settings(bs: Any) -> dict[str, Any]:
    """Flatten ``brand_settings`` (ORM row or dict) into the dict ``policy_check`` expects."""
    def sect(name: str) -> dict[str, Any]:
        if bs is None:
            return {}
        v = bs.get(name) if isinstance(bs, dict) else getattr(bs, name, None)
        return v if isinstance(v, dict) else {}

    policies, voice, topics, offering = sect("policies"), sect("voice"), sect("topics"), sect("offering")
    vocab = voice.get("vocabulary") or {}
    tags = topics.get("hashtags") or {}
    out = dict(policies)
    out["banned_words"] = list({*map(str, _as_list(policies.get("banned_words"))), *map(str, _as_list(vocab.get("avoid")))})
    out["banned_hashtags"] = [str(t) for t in _as_list(tags.get("banned"))]
    allowed = [str(d) for d in _as_list(policies.get("allowed_link_domains"))]
    for key in ("website", "url"):
        if isinstance(offering.get(key), str):
            allowed.append(_domain(offering[key]))
    for cta in _as_list(topics.get("ctas")):
        if isinstance(cta, dict) and isinstance(cta.get("url"), str):
            allowed.append(_domain(cta["url"]))
    if allowed:
        out["allowed_link_domains"] = sorted({d for d in allowed if d})
    return out


def policy_check(text: str, brand_policies: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic policy scan. Returns ``{flags[], risk, categories[], blocked}``."""
    text = text or ""
    pol = brand_policies or {}
    flags: list[dict[str, Any]] = []
    categories: set[str] = set()

    for topic in _as_list(pol.get("forbidden_topics")):
        t = topic.get("topic") if isinstance(topic, dict) else str(topic)
        pat = _topic_pattern(t or "")
        if pat and (m := pat.search(text)):
            flags.append(_flag("forbidden_topic", "brand_policy", "block", f"Mentions forbidden topic '{t}'", m.group(0)))
            categories.add("forbidden_topic")

    for st in _as_list(pol.get("sensitive_topics")):
        t = st.get("topic") if isinstance(st, dict) else str(st)
        handling = st.get("handling") if isinstance(st, dict) else None
        pat = _topic_pattern(t or "")
        if pat and (m := pat.search(text)):
            msg = f"Brand-sensitive topic '{t}'" + (f": {handling}" if handling else "")
            flags.append(_flag("brand_sensitive_topic", "brand_policy", "medium", msg, m.group(0)))
            categories.add("brand_sensitive_topic")

    for w in _as_list(pol.get("banned_words")):
        pat = _topic_pattern(str(w))
        if pat and (m := pat.search(text)):
            flags.append(_flag("banned_word", "brand_policy", "medium", f"Uses banned word '{w}'", m.group(0)))
            categories.add("banned_word")

    banned_tags = {str(b).lstrip("#").casefold() for b in _as_list(pol.get("banned_hashtags"))}
    for tag in extract_hashtags(text):
        if tag.casefold() in banned_tags:
            flags.append(_flag("banned_hashtag", "brand_policy", "medium", f"Uses banned hashtag #{tag}", f"#{tag}"))
            categories.add("banned_hashtag")

    for cat, rx in _SENSITIVE_RE.items():
        m = rx.search(text)
        if m:
            categories.add(cat)
            flags.append(_flag("sensitive_topic", cat, _CATEGORY_SEVERITY[cat], f"Sensitive topic: {cat.replace('_', ' ')}",
                               m.group(0)))

    claims_strict = bool(pol.get("claims_policy")) or bool(_as_list(pol.get("compliance_tags")))
    for m in GUARANTEE_RE.finditer(text):
        regulated = bool(categories & REGULATED_CATEGORIES)
        sev = "high" if (regulated or claims_strict) else "medium"
        flags.append(_flag("guarantee_claim", "claims", sev, "Absolute/guarantee language", m.group(0)))
        categories.add("claims")
        break
    if (m := HEALTH_CLAIM_RE.search(text)):
        flags.append(_flag("health_claim", "health_medical", "high", "Health outcome claim", m.group(0)))
        categories.update({"claims", "health_medical"})
    if (m := FINANCIAL_CLAIM_RE.search(text)):
        flags.append(_flag("financial_claim", "financial_advice", "high", "Financial return claim", m.group(0)))
        categories.update({"claims", "financial_advice"})

    # PII
    for m in EMAIL_RE.finditer(text):
        flags.append(_flag("pii_email", "pii", "medium", "Contains an email address", m.group(0)))
        categories.add("pii")
    for m in SSN_RE.finditer(text):
        flags.append(_flag("pii_ssn", "pii", "block", "Contains an SSN-like number", m.group(0)))
        categories.add("pii")
    card_spans: list[tuple[int, int]] = []
    for m in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits) and len(set(digits)) > 1:
            flags.append(_flag("pii_card", "pii", "block", "Contains a payment-card-like number", m.group(0).strip()))
            categories.add("pii")
            card_spans.append(m.span())
    for m in PHONE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in card_spans):
            continue
        digits = re.sub(r"\D", "", m.group(0))
        raw = m.group(0).strip()
        if _THOUSANDS_RE.fullmatch(raw) or SSN_RE.fullmatch(raw):
            continue
        if 7 <= len(digits) <= 15:
            flags.append(_flag("pii_phone", "pii", "medium", "Contains a phone number", m.group(0)))
            categories.add("pii")
    for m in IBAN_RE.finditer(text):
        flags.append(_flag("pii_iban", "pii", "high", "Contains a bank account (IBAN-like) number", m.group(0)))
        categories.add("pii")

    # secrets
    for name, rx in SECRET_PATTERNS.items():
        if (m := rx.search(text)):
            flags.append(_flag("secret_" + name, "secrets", "block", f"Contains a secret ({name.replace('_', ' ')})",
                               m.group(0)[:12] + "…"))
            categories.add("secrets")

    # links
    allowed = {d.lower().lstrip(".") for d in _as_list(pol.get("allowed_link_domains")) if d}
    for url in find_urls(text):
        d = _domain(url)
        if d in LINK_SHORTENERS:
            flags.append(_flag("link_shortener", "links", "medium", f"Link shorteners are not allowed ({d})", url))
            categories.add("links")
        elif allowed and not any(d == a or d.endswith("." + a) for a in allowed):
            flags.append(_flag("unapproved_link", "links", "low", f"Link to a domain not in the brand allowlist ({d})", url))
            categories.add("links")

    # disclaimers for compliance tags
    disclaimers = [str(d) for d in _as_list(pol.get("legal_disclaimers")) if d]
    if _as_list(pol.get("compliance_tags")) and disclaimers:
        low = text.casefold()
        if not any(d.casefold()[:60] in low for d in disclaimers):
            flags.append(_flag("missing_disclaimer", "compliance", "medium",
                               "Compliance-tagged brand: required disclaimer not found", None))
            categories.add("compliance")

    if (m := INSTRUCTION_LEAK_RE.search(text)):
        flags.append(_flag("instruction_leakage", "injection", "high", "Possible prompt/instruction leakage", m.group(0)))
        categories.add("injection")

    worst = max((SEVERITY_ORDER[f["severity"]] for f in flags), default=0)
    blocked = worst >= SEVERITY_ORDER["block"]
    risk = "high" if worst >= SEVERITY_ORDER["high"] else "medium" if worst >= SEVERITY_ORDER["medium"] else "low"
    return {"flags": flags, "risk": risk, "categories": sorted(categories), "blocked": blocked}


# ── risk combination ────────────────────────────────────────────────────────────

_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def _unit(v: Any) -> float | None:
    """Normalize a score to 0..1 (accepts 0..1, 0..10 or 0..100)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        if isinstance(v, str) and v.lower() in _RISK_RANK:
            return _RISK_RANK[v.lower()] / 2
        return None
    if x <= 1:
        return max(0.0, x)
    if x <= 10:
        return x / 10
    return min(1.0, x / 100)


def is_regulated(compliance_tags: Iterable[str] | None, categories: Iterable[str] | None = None) -> bool:
    tags = [str(t).lower() for t in (compliance_tags or [])]
    if any(h in t for t in tags for h in REGULATED_COMPLIANCE_HINTS):
        return True
    return bool(set(categories or []) & REGULATED_CATEGORIES)


def risk_from(critique: dict[str, Any] | None, factcheck: dict[str, Any] | None, policy: dict[str, Any] | None,
              compliance_tags: Iterable[str] | None = None) -> str:
    """Combine signals into low|medium|high (doc 19 §19.7).

    high: policy blocked/high · any contradicted claim or fact-check ``blocking`` · unverifiable claim in a regulated
          domain · critic risk ≥ 0.7, risk_level=high, a blocker issue or recommend=reject · fact-check overall_risk high.
    medium: policy medium · unverifiable claims · critic risk ≥ 0.4, risk_level=medium, recommend=revise or
            quality < 0.5 · fact-check overall_risk medium / requires_human.
    """
    level = 0
    policy = policy or {}
    if policy.get("blocked") or policy.get("risk") == "high":
        return "high"
    if policy.get("risk") == "medium":
        level = max(level, 1)
    categories = policy.get("categories") or []
    regulated = is_regulated(compliance_tags, categories)

    fc = factcheck or {}
    claims = fc.get("claims") or []
    verdicts = [str(c.get("verdict", "")).lower() for c in claims if isinstance(c, dict)]
    if "contradicted" in verdicts or fc.get("blocking"):
        return "high"
    if "unverifiable" in verdicts:
        regulated_claim = any(isinstance(c, dict) and str(c.get("verdict", "")).lower() == "unverifiable"
                              and c.get("regulated_domain") for c in claims)
        if regulated or regulated_claim:
            return "high"
        level = max(level, 1)
    fr = str(fc.get("overall_risk") or "").lower()
    if fr in _RISK_RANK:
        level = max(level, _RISK_RANK[fr])
    if fc.get("requires_human") and any(v not in ("supported", "opinion") for v in verdicts):
        level = max(level, 1)

    cr = critique or {}
    scores = cr.get("scores") or {}
    r = _unit(scores.get("risk")) if isinstance(scores, dict) else None
    if r is not None:
        level = max(level, 2 if r >= 0.7 else 1 if r >= 0.4 else 0)
    crl = str(cr.get("risk_level") or "").lower()
    if crl in _RISK_RANK:
        level = max(level, _RISK_RANK[crl])
    for iss in cr.get("issues") or []:
        sev = str(iss.get("severity") if isinstance(iss, dict) else "").lower()
        if sev in ("blocker", "block"):
            level = 2
    rec = str(cr.get("recommend") or "").lower()
    if rec == "reject":
        level = max(level, 2)
    elif rec == "revise":
        level = max(level, 1)
    q = _unit(scores.get("quality")) if isinstance(scores, dict) else None
    if q is not None and q < 0.5:
        level = max(level, 1)
    for pf in cr.get("policy_flags") or []:
        sev = str(pf.get("severity") if isinstance(pf, dict) else "").lower()  # plain-string flags carry no severity
        if sev in ("high", "block"):
            level = 2
        elif sev == "medium":
            level = max(level, 1)
    return ("low", "medium", "high")[min(level, 2)]


def has_contradicted_claims(factcheck: dict[str, Any] | None) -> bool:
    return any(isinstance(c, dict) and str(c.get("verdict", "")).lower() == "contradicted"
               for c in (factcheck or {}).get("claims") or [])
