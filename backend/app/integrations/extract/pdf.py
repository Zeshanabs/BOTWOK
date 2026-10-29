"""PDF text extraction via pypdf (no rendering, no JavaScript, page and size caps)."""
from __future__ import annotations

import io
import re

from app.core.logging import get_logger
from app.core.ports.extractor_provider import ExtractedDocument
from app.integrations.search.base import parse_date

log = get_logger("extract.pdf")
MAX_PAGES = 80


def _pdf_date(v: object) -> str | None:
    if not v:
        return None
    s = str(v)
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?", s)
    if m:
        return f"{m.group(1)}-{m.group(2) or '01'}-{m.group(3) or '01'}"
    return s


class PdfExtractor:
    name = "pypdf"

    def extract_bytes(self, data: bytes, url: str) -> ExtractedDocument | None:
        try:
            from pypdf import PdfReader
        except ImportError:
            return None
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    return None
            pages: list[str] = []
            for page in reader.pages[:MAX_PAGES]:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            meta = reader.metadata or {}
        except Exception as e:
            log.info("extract.pdf_failed", url=url, error=str(e)[:200])
            return None
        text = "\n\n".join(re.sub(r"[ \t]+", " ", p).strip() for p in pages if p.strip())
        if not text:
            return None
        title = getattr(meta, "title", None) or (meta.get("/Title") if hasattr(meta, "get") else None)
        author = getattr(meta, "author", None) or (meta.get("/Author") if hasattr(meta, "get") else None)
        created = meta.get("/CreationDate") if hasattr(meta, "get") else None
        return ExtractedDocument(url=url, title=str(title) if title else None, text=text,
                                 author=str(author) if author else None, published_at=parse_date(_pdf_date(created)),
                                 extractor=self.name)

    def extract(self, html: str, url: str) -> ExtractedDocument | None:  # port compatibility (latin-1 round trip)
        return self.extract_bytes(html.encode("latin-1", errors="ignore"), url)
