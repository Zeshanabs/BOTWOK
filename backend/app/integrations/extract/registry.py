"""Extractor chain: trafilatura → readability fallback → PDF (pypdf); plain text / feeds / JSON handled directly.

``extract(html_or_bytes, url, content_type)`` always returns sanitized text (zero-width/bidi/control chars stripped) or None.
"""
from __future__ import annotations

import json
import re

from app.core.ports.extractor_provider import ExtractedDocument
from app.integrations.extract.pdf import PdfExtractor
from app.integrations.extract.readability_fallback import ReadabilityFallbackExtractor, page_metadata
from app.integrations.extract.trafilatura_extractor import TrafilaturaExtractor
from app.integrations.search.base import parse_date
from app.research.injection import sanitize

MIN_GOOD_WORDS = 60
MAX_TEXT_CHARS = 400_000
FEED_TYPES = ("application/rss+xml", "application/atom+xml")

_trafilatura = TrafilaturaExtractor()
_fallback = ReadabilityFallbackExtractor()
_pdf = PdfExtractor()


def _decode(data: str | bytes) -> str:
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _finish(doc: ExtractedDocument) -> ExtractedDocument:
    doc.text = sanitize(doc.text, max_chars=MAX_TEXT_CHARS).strip()
    if doc.title:
        doc.title = sanitize(doc.title, max_chars=500).strip() or None
    if doc.author:
        doc.author = sanitize(doc.author, max_chars=200).strip() or None
    return doc


def _feed_text(raw: str, url: str) -> ExtractedDocument | None:
    try:
        import feedparser
    except ImportError:
        return None
    parsed = feedparser.parse(raw)
    if not parsed.entries:
        return None
    parts = []
    for e in parsed.entries[:50]:
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")).strip()
        parts.append(f"{e.get('title', '')}\n{summary}\n{e.get('link', '')}")
    return ExtractedDocument(url=url, title=parsed.feed.get("title"), text="\n\n".join(parts), extractor="feedparser",
                             published_at=parse_date(parsed.feed.get("updated") or parsed.feed.get("published")))


def extract(html_or_bytes: str | bytes, url: str, content_type: str | None = None) -> ExtractedDocument | None:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    is_bytes = isinstance(html_or_bytes, bytes | bytearray)
    head = bytes(html_or_bytes[:5]) if is_bytes else html_or_bytes[:5].encode("latin-1", errors="ignore")
    if ct == "application/pdf" or head.startswith(b"%PDF-"):
        data = bytes(html_or_bytes) if is_bytes else html_or_bytes.encode("latin-1", errors="ignore")
        doc = _pdf.extract_bytes(data, url)
        return _finish(doc) if doc else None
    raw = _decode(html_or_bytes if not is_bytes else bytes(html_or_bytes))
    if ct == "text/plain":
        return _finish(ExtractedDocument(url=url, title=None, text=raw, extractor="plain"))
    if ct == "application/json":
        try:
            pretty = json.dumps(json.loads(raw), indent=1, ensure_ascii=False)[:MAX_TEXT_CHARS]
        except ValueError:
            pretty = raw
        return _finish(ExtractedDocument(url=url, title=None, text=pretty, extractor="json"))
    if ct in FEED_TYPES or (ct in ("application/xml", "text/xml") and re.search(r"<(rss|feed)[\s>]", raw[:2000])):
        doc = _feed_text(raw, url)
        return _finish(doc) if doc else None
    primary = _trafilatura.extract(raw, url)
    fallback = None
    if primary is None or len(primary.text.split()) < MIN_GOOD_WORDS:
        fallback = _fallback.extract(raw, url)
    doc = primary
    if fallback is not None and (primary is None or len(fallback.text.split()) > len(primary.text.split()) * 1.2):
        doc = fallback
        if primary is not None:  # keep trafilatura's metadata when it found any
            doc.title = primary.title or doc.title
            doc.author = primary.author or doc.author
            doc.published_at = primary.published_at or doc.published_at
            doc.language = primary.language or doc.language
    if doc is None:
        return None
    if not doc.title or not doc.language:
        meta = page_metadata(raw)
        doc.title = doc.title or meta.get("title")
        doc.language = doc.language or meta.get("language")
        doc.author = doc.author or meta.get("author")
        doc.published_at = doc.published_at or parse_date(meta.get("published"))
    return _finish(doc)
