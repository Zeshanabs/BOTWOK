from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.schemas.common import SourcedOutput, StrictBase


class ReportSection(StrictBase):
    heading: str
    markdown: str
    charts: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Report(SourcedOutput):
    title: str
    kind: str | None = None
    sections: list[ReportSection] = Field(default_factory=list)
    summary: str
    period: str | None = None
    report_id: str | None = None
