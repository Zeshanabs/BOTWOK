"""CitationTracker (doc 05 §5.2.11): collects source ids/URLs from tool results, verifies output URLs ⊆ known URLs
(hallucinated-citation guard) and builds the run's sources[] panel from research_sources rows."""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.logging import get_logger
from app.tools.runner import ToolResult, collect_refs

log = get_logger("ai.citations")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]\\]+", re.I)
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class CitationGuardError(ValueError):
    def __init__(self, foreign_urls: list[str]):
        super().__init__(f"output cites URLs not present in tool results: {', '.join(foreign_urls[:5])}")
        self.foreign_urls = foreign_urls


def normalize_url(u: str) -> str:
    u = u.strip().rstrip(".,;:)!?'\"").rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u, flags=re.I)
    return u.lower()


def extract_urls(text: str) -> set[str]:
    return {normalize_url(m) for m in _URL_RE.findall(text or "")}


def walk_strings(obj: Any, depth: int = 0) -> Iterator[str]:
    if depth > 12:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v, depth + 1)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from walk_strings(v, depth + 1)


def _as_data(output: Any) -> Any:
    return output.model_dump(mode="json") if isinstance(output, BaseModel) else output


class CitationTracker:
    def __init__(self) -> None:
        self.source_ids: set[str] = set()
        self.urls: set[str] = set()                # normalized URLs seen in tool results
        self.allowed_urls: set[str] = set()        # URLs from inputs / brand context (user-provided, allowed to echo)
        self.url_index: dict[str, str] = {}        # normalized -> original form
        self.tool_sources: list[dict[str, Any]] = []

    # -- collection -------------------------------------------------------------------------------------------------
    def allow_text(self, text: str | None) -> None:
        if text:
            self.allowed_urls.update(extract_urls(text))

    def allow_data(self, data: Any) -> None:
        for s in walk_strings(_as_data(data)):
            self.allow_text(s)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            if r.status != "succeeded":
                continue
            sids: set[str] = set(r.source_ids)
            urls: set[str] = set(r.urls)
            collect_refs(r.result, sids, urls)
            self.source_ids.update(sids)
            for u in urls:
                n = normalize_url(u)
                self.urls.add(n)
                self.url_index.setdefault(n, u)
            for s in walk_strings(r.result):
                for u in extract_urls(s):
                    self.urls.add(u)
            self._collect_source_dicts(r.result)

    def _collect_source_dicts(self, data: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(data, dict):
            if data.get("source_id") and (data.get("url") or data.get("canonical_url") or data.get("title")):
                self.tool_sources.append({"source_id": str(data["source_id"]), "url": data.get("url") or data.get("canonical_url"),
                                          "title": data.get("title"), "domain": data.get("domain"),
                                          "credibility": data.get("credibility") or data.get("credibility_score"),
                                          "published_at": data.get("published_at")})
            for v in data.values():
                self._collect_source_dicts(v, depth + 1)
        elif isinstance(data, list):
            for v in data:
                self._collect_source_dicts(v, depth + 1)

    # -- verification -----------------------------------------------------------------------------------------------
    def foreign_urls(self, output: Any) -> list[str]:
        known = self.urls | self.allowed_urls
        found: dict[str, str] = {}
        for s in walk_strings(_as_data(output)):
            for raw in _URL_RE.findall(s):
                n = normalize_url(raw)
                if n and n not in known and not any(n.startswith(k) or k.startswith(n) for k in known):
                    found.setdefault(n, raw)
        return list(found.values())

    def verify(self, output: Any) -> None:
        foreign = self.foreign_urls(output)
        if foreign:
            raise CitationGuardError(foreign)

    def output_source_ids(self, output: Any) -> list[str]:
        ids: set[str] = set()
        data = _as_data(output)

        def _walk(o: Any, depth: int = 0) -> None:
            if depth > 12:
                return
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "source_id" and isinstance(v, str):
                        ids.add(v)
                    elif k in ("sources", "evidence_sources", "example_sources", "evidence_ids") and isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                ids.add(item)
                            else:
                                _walk(item, depth + 1)
                    else:
                        _walk(v, depth + 1)
            elif isinstance(o, list):
                for item in o:
                    _walk(item, depth + 1)
        _walk(data)
        return sorted(ids)

    # -- sources panel ----------------------------------------------------------------------------------------------
    async def resolve_sources(self, db: Any, workspace_id: UUID, source_ids: set[str] | None = None) -> list[dict[str, Any]]:
        ids = sorted(source_ids if source_ids is not None else self.source_ids)
        out: dict[str, dict[str, Any]] = {}
        for s in self.tool_sources:
            if s["source_id"] in ids or source_ids is None:
                out.setdefault(s["source_id"], s)
        uuids = [UUID(i) for i in ids if _UUID_RE.match(i)]
        if db is not None and uuids:
            try:
                from sqlalchemy import select

                from app.models.research import ResearchSource
                rows = (await db.execute(select(ResearchSource).where(ResearchSource.workspace_id == workspace_id,
                                                                      ResearchSource.id.in_(uuids)))).scalars().all()
                for r in rows:
                    out[str(r.id)] = {"source_id": str(r.id), "url": r.final_url or r.canonical_url, "title": r.title,
                                      "domain": r.domain, "published_at": r.published_at.isoformat() if r.published_at else None,
                                      "credibility": float(r.credibility_score) if r.credibility_score is not None else None,
                                      "kind": r.source_kind, "injection_flag": bool(r.injection_flag)}
            except Exception as e:  # noqa: BLE001
                log.warning("citations.resolve_failed", error=str(e)[:200])
        for i in ids:
            out.setdefault(i, {"source_id": i, "url": None, "title": None})
        return sorted(out.values(), key=lambda s: (-(s.get("credibility") or 0), s.get("title") or ""))

    def summary(self) -> dict[str, Any]:
        return {"source_ids": sorted(self.source_ids), "urls": len(self.urls)}
