from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str
    published_at: datetime | None = None
    provider: str = ""
    rank: int = 0
    content: str | None = None   # some providers return extracted content


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, kind: Literal["web", "news"] = "web", recency_days: int | None = None,
                     max_results: int = 10, domains_allow: list[str] | None = None,
                     domains_deny: list[str] | None = None) -> list[SearchHit]: ...
