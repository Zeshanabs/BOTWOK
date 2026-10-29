from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class ExtractedDocument:
    url: str
    title: str | None
    text: str
    author: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    extractor: str = ""


class ExtractorProvider(Protocol):
    name: str

    def extract(self, html: str, url: str) -> ExtractedDocument | None: ...
