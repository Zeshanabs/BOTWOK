"""Primary HTML extractor: trafilatura (favor_recall, no links/images/comments, with metadata)."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.ports.extractor_provider import ExtractedDocument
from app.integrations.search.base import parse_date

log = get_logger("extract.trafilatura")


def _get(doc: Any, key: str) -> Any:
    if doc is None:
        return None
    if isinstance(doc, dict):
        return doc.get(key)
    return getattr(doc, key, None)


class TrafilaturaExtractor:
    name = "trafilatura"

    def extract(self, html: str, url: str) -> ExtractedDocument | None:
        try:
            import trafilatura
        except ImportError:
            return None
        try:
            doc = trafilatura.bare_extraction(html, url=url, favor_recall=True, include_comments=False, include_links=False,
                                              include_images=False, include_tables=True, with_metadata=True,
                                              deduplicate=False)
        except Exception as e:  # malformed markup can make lxml raise
            log.info("extract.trafilatura_failed", url=url, error=str(e)[:200])
            return None
        text = (_get(doc, "text") or "").strip()
        if not text:
            return None
        lang = _get(doc, "language")
        return ExtractedDocument(url=url, title=_get(doc, "title"), text=text, author=_get(doc, "author"),
                                 published_at=parse_date(_get(doc, "date")),
                                 language=(lang.split("-")[0].lower() if isinstance(lang, str) and lang else None),
                                 extractor=self.name)
