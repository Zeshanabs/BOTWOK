"""Reports API schemas (doc 13 §13.6, doc 17, doc 24 Reports)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ReportKind = Literal["weekly_performance", "competitor", "competitor_opportunities", "campaign", "research_brief", "custom"]


class ReportCreateIn(BaseModel):
    kind: ReportKind
    brand_id: UUID
    period_start: date | None = None
    period_end: date | None = None
    title: str | None = Field(default=None, max_length=300)
    recipients: list[str | dict[str, Any]] = Field(default_factory=list, max_length=50,
                                                   description="emails, user ids, channel names (in_app|email|slack|webhook) "
                                                               "or {user_id}|{email}|{channel}")
    audience: Literal["executive", "team"] = "team"
    length: Literal["brief", "standard", "long"] = "standard"
    instructions: str | None = Field(default=None, max_length=2000)
    campaign_ids: list[UUID] = Field(default_factory=list, max_length=10)
    use_ai: bool = True

    @model_validator(mode="after")
    def _period(self) -> ReportCreateIn:
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        return self


class ReportSection(BaseModel):
    heading: str
    markdown: str
    charts: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    origin: str = "data"


class ReportListItem(BaseModel):
    id: UUID
    brand_id: UUID | None = None
    kind: str
    title: str
    status: str
    period_start: date | None = None
    period_end: date | None = None
    summary: str | None = None
    narrative_status: str | None = None
    rendered_object_key: str | None = None
    ai_run_id: UUID | None = None
    automation_run_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None


class ReportOut(ReportListItem):
    sections: list[ReportSection] = Field(default_factory=list)
    recipients: list[dict[str, Any] | str] = Field(default_factory=list)
    delivery: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    data_pack_version: int | None = None
    data: dict[str, Any] | None = None


class ReportCreatedOut(ReportOut):
    report_id: UUID
    run_id: UUID | None = None
    status_url: str | None = None


def report_view(report: Any, *, detail: bool = True) -> dict[str, Any]:
    """ORM ``Report`` → dict for ReportListItem / ReportOut (status & sections live in ``content``)."""
    c = report.content or {}
    out: dict[str, Any] = {"id": report.id, "brand_id": report.brand_id, "kind": report.kind, "title": report.title,
                           "status": c.get("status") or "ready", "period_start": report.period_start,
                           "period_end": report.period_end, "summary": c.get("summary"),
                           "narrative_status": c.get("narrative_status"), "rendered_object_key": report.rendered_object_key,
                           "ai_run_id": report.ai_run_id, "automation_run_id": report.automation_run_id,
                           "created_by": report.created_by, "created_at": report.created_at}
    if detail:
        out.update(sections=c.get("sections") or [], recipients=list(report.recipients or []),
                   delivery=c.get("delivery") or [], error=c.get("error"), data_pack_version=c.get("data_pack_version"),
                   data=c.get("data"))
    return out
