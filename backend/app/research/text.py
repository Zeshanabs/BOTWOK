"""Shared deterministic text helpers (tokenizing, stopwords, sentences) for the research pipeline."""
from __future__ import annotations

import re
from collections import Counter

STOPWORDS = frozenset("""
a about above across after afterwards again against all almost alone along already also although always am among amongst
an and another any anyhow anyone anything anyway anywhere are around as at back be became because become becomes becoming
been before beforehand behind being below beside besides between beyond both but by can cannot could did do does doing done
down due during each eg either else elsewhere enough etc even ever every everyone everything everywhere except few first for
former formerly from further get gets getting give given go goes going got had has have having he hence her here hereafter
hereby herein hereupon hers herself him himself his how however i ie if in inc indeed into is it its itself just keep last
latter latterly least less let like likely ltd made make makes many may me meanwhile might mine more moreover most mostly
much must my myself namely neither never nevertheless new next no nobody none noone nor not nothing now nowhere of off often
on once one only onto or other others otherwise our ours ourselves out over own per perhaps please put quite rather re really
said same say says see seem seemed seeming seems several she should show since so some somehow someone something sometime
sometimes somewhere still such take than that the their theirs them themselves then thence there thereafter thereby therefore
therein thereupon these they this those though through throughout thru thus to together too toward towards under until up
upon us use used using very via was we well were what whatever when whence whenever where whereafter whereas whereby wherein
whereupon wherever whether which while whither who whoever whole whom whose why will with within without would yet you your
yours yourself yourselves also just one two three four five six seven eight nine ten year years time times way ways day days
week weeks month months today new news read more click here sign subscribe newsletter cookie cookies privacy policy terms
copyright reserved rights menu home page share tweet email login account free best top im youre dont doesnt isnt cant wont
""".split())

_WORD_RE = re.compile(r"[^\W\d_][\w'’-]*[^\W_]|[^\W\d_]", re.UNICODE)
_SENT_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
_CAP_SEQ_RE = re.compile(r"\b(?:[A-Z][\w&'’.-]*[A-Za-z0-9](?:\s+(?:of|and|for|the|de|&)\s+|\s+)?){1,4}")


def words(text: str) -> list[str]:
    return [w.strip("'’-") for w in _WORD_RE.findall(text or "")]


def tokens(text: str, *, min_len: int = 3) -> list[str]:
    """Lowercased content tokens without stopwords."""
    out = []
    for w in words(text):
        lw = w.lower().replace("’", "'")
        if len(lw) >= min_len and lw not in STOPWORDS and not lw.isdigit():
            out.append(lw)
    return out


def term_set(text: str) -> set[str]:
    return set(tokens(text))


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        para = para.strip()
        if not para:
            continue
        out.extend(s.strip() for s in _SENT_RE.split(para) if s.strip())
    return out


def word_count(text: str) -> int:
    return len((text or "").split())


def top_terms(text: str, k: int = 10, *, with_bigrams: bool = True) -> list[str]:
    """Term-frequency keywords: unigrams + frequent bigrams (bigrams need ≥2 occurrences)."""
    toks = tokens(text)
    if not toks:
        return []
    uni = Counter(toks)
    scored: Counter[str] = Counter()
    for t, c in uni.items():
        scored[t] = c
    if with_bigrams:
        raw = [w.lower() for w in words(text)]
        bi: Counter[str] = Counter()
        for a, b in zip(raw, raw[1:], strict=False):
            if len(a) >= 3 and len(b) >= 3 and a not in STOPWORDS and b not in STOPWORDS and not a.isdigit() and not b.isdigit():
                bi[f"{a} {b}"] += 1
        for t, c in bi.items():
            if c >= 2:
                scored[t] = c * 1.5
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[str] = []
    for term, _ in ranked:
        if " " in term:
            out.append(term)
        elif not any(term in o.split() for o in out if " " in o):
            out.append(term)
        if len(out) >= k:
            break
    return out


def capitalized_ngrams(text: str, *, max_items: int = 25) -> list[tuple[str, int]]:
    """Candidate named entities: runs of 1–4 capitalized words, excluding sentence-initial stopwords."""
    counts: Counter[str] = Counter()
    for m in _CAP_SEQ_RE.finditer(text or ""):
        cand = m.group(0).strip().rstrip(".,;:")
        parts = cand.split()
        while parts and parts[0].lower() in STOPWORDS:
            parts = parts[1:]
        while parts and parts[-1].lower() in STOPWORDS | {"of", "and", "for", "the", "de", "&"}:
            parts = parts[:-1]
        if not parts:
            continue
        cand = " ".join(parts)
        if len(cand) < 3 or cand.isupper() and len(cand) > 12:
            continue
        counts[cand] += 1
    return counts.most_common(max_items)
