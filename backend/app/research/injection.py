"""Untrusted-content sanitization and prompt-injection classifier (doc 19 §19.6 rules 1–2).

``sanitize(text)`` strips zero-width / bidi / tag characters and control chars and NFC-normalizes.
``classify(text)`` runs regex rules plus a small heuristic scorer on an aggressively normalized copy (NFKC, invisible
characters removed, whitespace collapsed) so that obfuscated variants ("ｉｇｎｏｒｅ", "ig​nore") are caught too.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ZERO_WIDTH = "​‌‍⁠⁡⁢⁣⁤﻿᠎­͏ᅟᅠㅤﾠ"
BIDI_CONTROLS = "‪‫‬‭‮⁦⁧⁨⁩"
BIDI_MARKS = "‎‏؜"
_TAG_CHARS_RE = re.compile("[\U000e0000-\U000e007f]")
_INVISIBLE_RE = re.compile(f"[{re.escape(ZERO_WIDTH + BIDI_CONTROLS + BIDI_MARKS)}]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SUSPICIOUS_ZW_RE = re.compile(r"[​⁠-⁤᠎͏]|(?<=[A-Za-z])[‌‍­﻿](?=[A-Za-z])")
_BIDI_OVERRIDE_RE = re.compile(f"[{BIDI_CONTROLS}]")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    weight: float
    skip_if_negated: bool = False


def _r(name: str, pattern: str, weight: float = 1.0, *, skip_if_negated: bool = False) -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE | re.DOTALL | re.MULTILINE), weight, skip_if_negated)


_NEGATION_RE = re.compile(r"\b(never|not|don'?t|do\s+not|avoid|should\s+not|shouldn'?t|must\s+not)\b[\w\s,]{0,20}$", re.I)
_TOOL_NAMES = (r"web\.(search|fetch|crawl)|research\.(save_source|read_source|find_similar)|rss\.read|keywords\.lookup|"
               r"content\.(create_draft|create_variant|update_draft)|publishing\.propose_\w+|media\.generate_image|"
               r"competitors\.\w+|trends\.(save|signals|list)|memory\.(search|write)|brand\.get_context")

RULES: tuple[Rule, ...] = (
    _r("ignore_previous", r"\b(ignore|disregard|forget|override)\b[\w\s,'-]{0,30}?\b(previous|prior|above|earlier|preceding|"
       r"original|initial|system|developer)\s+(instructions?|prompts?|messages?|rules|directions|directives|guidelines|"
       r"commands?)"),
    _r("forget_everything", r"\b(forget|ignore|disregard)\s+(everything|all\s+(of\s+)?(that|this|the\s+above))\b"),
    _r("new_instructions", r"\b(new|updated|real|actual|revised)\s+(system\s+)?instructions?\s*[:\-]"),
    _r("system_prompt", r"\bsystem\s*prompt\b", 0.7),
    _r("reveal_prompt", r"\b(reveal|print|show|output|repeat|leak|disclose)\b[\w\s]{0,20}\b(system|hidden|initial|secret)\s+"
       r"(prompt|instructions?|message)"),
    _r("you_are_now", r"\byou\s+are\s+now\s+(no\s+longer|free\b|unrestricted|unfiltered|uncensored|jailbroken|operating|"
       r"acting|in\s+(developer|god|admin|dan)\s+mode|dan\b|called|named|my\b)"),
    _r("you_are_now_weak", r"\byou\s+are\s+now\s+an?\s+(ai|assistant|bot|agent|model|expert|pirate|character|different)\b", 0.6),
    _r("role_switch", r"\b(act|behave|respond)\s+as\s+(an?\s+)?(unrestricted|jailbroken|evil|uncensored|different)\s+"
       r"(ai|assistant|model|chatbot|llm)"),
    _r("jailbreak_mode", r"\b(dan\s+mode|developer\s+mode\s+(enabled|activated|on)|do\s+anything\s+now)\b"),
    _r("jailbreak_word", r"\bjailbr(eak|oken)\b", 0.4),
    _r("addressing_ai", r"\b(if\s+you\s+are|attention|note\s+to|message\s+for|instructions?\s+for)\s+(an?\s+|the\s+|any\s+)?"
       r"(ai|llm|language\s+model|ai\s+assistant|chatbot|gpt|claude|ai\s+agent)s?\b", 0.6),
    _r("ai_reading_this", r"\b(ai|llm|assistant|agent|model)s?\s+(reading|processing|summari[sz]ing|parsing)\s+this\b", 0.8),
    _r("chat_markup", r"(<\|im_start\|>|<\|im_end\|>|<\|system\|>|<\|assistant\|>|\[/?INST\]|<<SYS>>|</?system>|"
       r"^\s*#{2,}\s*(system|assistant)\s*:?\s*$)"),
    _r("tool_markup", r"(<\s*/?\s*(tool_call|tool_use|function_calls?|invoke|antml:[a-z_]+)\b|"
       r"\"(tool|function)_?(name|call)?\"\s*:\s*\"[a-z_.]+\"|\"name\"\s*:\s*\"(" + _TOOL_NAMES + r")\"|"
       r"\b(" + _TOOL_NAMES + r")\s*\()"),
    _r("visit_url_and", r"\b(visit|open|go\s+to|navigate\s+to|fetch|load|click)\s+(this|the\s+following|that)\s+"
       r"(url|link|page|address)\s*(https?://\S+\s+)?and\s+(then\s+)?(send|post|submit|paste|include|report|upload|"
       r"append|forward)"),
    _r("send_data", r"\b(send|email|post|forward|transmit|upload|exfiltrate|leak)\b[\w\s'’]{0,30}\b(conversation|chat\s+history|"
       r"credentials?|api\s*keys?|tokens?|passwords?|secrets?|system\s+prompt|user\s+data|personal\s+data|cookies)\b"
       r"[\w\s'’]{0,20}\b(to|via|at)\b", skip_if_negated=True),
    _r("shell_exfil", r"\b(curl|wget|invoke-webrequest)\b[^\n]{0,200}(\|\s*(ba|z)?sh\b|\$\(|`[^`]+`|-d\s+@|--data(-binary)?\s+@)"),
    _r("shell_fetch", r"\b(curl|wget)\s+(-[a-z]+\s+)*['\"]?https?://", 0.3),
    _r("do_not_tell", r"\b(do\s+not|don'?t|never)\s+(tell|inform|mention|reveal)\b[\w\s]{0,15}\b(to\s+)?(the\s+)?(user|human|"
       r"operator)s?\b"),
    _r("hidden_instruction", r"\b(hidden|secret)\s+(instruction|command|task)s?\b", 0.6),
)
BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{4}){50,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?(?![A-Za-z0-9+/])")
FLAG_THRESHOLD = 1.0


@dataclass
class InjectionReport:
    flagged: bool
    score: float
    reasons: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    sanitized_text: str = ""

    def to_dict(self) -> dict:
        return {"flagged": self.flagged, "score": round(self.score, 3), "reasons": self.reasons, "samples": self.samples[:5]}


def sanitize(text: str, *, max_chars: int | None = None) -> str:
    """Strip invisible/bidi/tag/control characters, NFC-normalize, normalize newlines; optional length cap."""
    if not text:
        return ""
    t = _TAG_CHARS_RE.sub("", text)
    t = _INVISIBLE_RE.sub("", t)
    t = _CONTROL_RE.sub("", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = unicodedata.normalize("NFC", t)
    if max_chars is not None and len(t) > max_chars:
        t = t[:max_chars]
    return t


def _detection_view(text: str) -> str:
    t = _TAG_CHARS_RE.sub("", text)
    t = _INVISIBLE_RE.sub("", t)
    t = unicodedata.normalize("NFKC", t)
    return _WS_RE.sub(" ", t)


def classify(text: str) -> InjectionReport:
    """Regex + heuristic injection classifier. ``flagged`` when the weighted score reaches 1.0."""
    reasons: list[str] = []
    samples: list[str] = []
    score = 0.0
    if not text:
        return InjectionReport(False, 0.0, sanitized_text="")
    tag_hits = len(_TAG_CHARS_RE.findall(text))
    if tag_hits:
        score += 1.0
        reasons.append("invisible_tag_characters")
    zw_hits = len(_SUSPICIOUS_ZW_RE.findall(text))
    if zw_hits >= 3:
        score += 1.0
        reasons.append("zero_width_characters")
    elif zw_hits:
        score += 0.3
    if _BIDI_OVERRIDE_RE.search(text):
        score += 1.0
        reasons.append("bidi_control_characters")
    view = _detection_view(text)
    for rule in RULES:
        m = rule.pattern.search(view)
        if m and rule.skip_if_negated and _NEGATION_RE.search(view[max(0, m.start() - 40): m.start()]):
            m = None
        if m:
            score += rule.weight
            reasons.append(rule.name)
            samples.append(view[max(0, m.start() - 20): m.end() + 20].strip())
    for m in BASE64_RE.finditer(view):
        if len(m.group(0)) > 200:
            score += 1.0
            reasons.append("base64_blob")
            samples.append(m.group(0)[:40] + "…")
            break
    return InjectionReport(score >= FLAG_THRESHOLD, score, reasons, samples, sanitize(text))


def wrap_untrusted(text: str, *, source_id: str | None = None, kind: str = "webpage") -> str:
    """Prompt-isolation wrapper (doc 19 §19.6 rule 3). Closing tags inside the payload are neutralized."""
    body = sanitize(text).replace("</untrusted", "&lt;/untrusted")
    sid = f' source_id="{source_id}"' if source_id else ""
    return f'<untrusted{sid} kind="{kind}">\n{body}\n</untrusted>'
