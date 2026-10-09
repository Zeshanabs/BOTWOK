"""Research API (doc 17 §17.2 Research). Thin: validate → ResearchService → schema."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.pagination import Page
from app.schemas.research import (
    FeedCreate,
    FeedOut,
    KeywordCreate,
    KeywordOut,
    RankedSource,
    ResearchRunCreate,
    ResearchRunDetail,
    ResearchRunOut,
    RunAccepted,
    SourceCard,
    SourceDetail,
    SourcePin,
)
from app.services.research_service import ResearchService

router = APIRouter(prefix="/research", tags=["research"])
Editor = Annotated[Member, Depends(require_role("editor"))]


@router.post("/runs", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_run(body: ResearchRunCreate, db: DB, member: Editor) -> RunAccepted:
    run = await ResearchService.start_run(db, member, body)
    out = RunAccepted(run_id=run.id, ai_run_id=run.ai_run_id, status=run.status,
                      status_url=f"/api/v1/research/runs/{run.id}")
    await db.commit()
    return out


@router.get("/runs", response_model=Page[ResearchRunOut])
async def list_runs(db: DB, member: CurrentMember, status_: Annotated[str | None, Query(alias="status")] = None,
                    brand_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                    cursor: str | None = None) -> Page[ResearchRunOut]:
    rows, nxt = await ResearchService.list_runs(db, member.workspace_id, limit=limit, cursor=cursor, status=status_,
                                                brand_id=brand_id)
    return Page[ResearchRunOut](items=[ResearchRunOut.model_validate(r) for r in rows], next_cursor=nxt)


@router.get("/runs/{run_id}", response_model=ResearchRunDetail)
async def get_run(run_id: UUID, db: DB, member: CurrentMember) -> ResearchRunDetail:
    run = await ResearchService.get_run(db, member.workspace_id, run_id)
    sources = await ResearchService.ranked_sources(db, run)
    out = ResearchRunDetail.model_validate(run)
    out.result = run.result
    out.sources = [RankedSource.model_validate(s) for s in sources]
    return out


@router.post("/runs/{run_id}/cancel", response_model=ResearchRunOut, status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: UUID, db: DB, member: Editor) -> ResearchRunOut:
    run = await ResearchService.cancel_run(db, member, run_id)
    out = ResearchRunOut.model_validate(run)
    await db.commit()
    return out


@router.get("/sources", response_model=Page[SourceCard])
async def list_sources(db: DB, member: CurrentMember, q: str | None = None, domain: str | None = None,
                       competitor_id: UUID | None = None,
                       min_credibility: Annotated[float | None, Query(ge=0, le=1)] = None,
                       since: datetime | None = None, kind: str | None = None, flagged: bool | None = None,
                       include_duplicates: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                       cursor: str | None = None) -> Page[SourceCard]:
    rows, nxt = await ResearchService.list_sources(db, member.workspace_id, q=q, domain=domain, competitor_id=competitor_id,
                                                   min_credibility=min_credibility, since=since, kind=kind, flagged=flagged,
                                                   include_duplicates=include_duplicates, limit=limit, cursor=cursor)
    return Page[SourceCard](items=[SourceCard.model_validate(r) for r in rows], next_cursor=nxt)


@router.get("/sources/{source_id}", response_model=SourceDetail)
async def get_source(source_id: UUID, db: DB, member: CurrentMember, include_text: bool = True,
                     max_chars: Annotated[int, Query(ge=500, le=200_000)] = 50_000) -> SourceDetail:
    src, text, truncated = await ResearchService.get_source(db, member.workspace_id, source_id, include_text=include_text,
                                                            max_chars=max_chars)
    out = SourceDetail.model_validate(src)
    out.text = text
    out.text_truncated = truncated
    return out


@router.post("/sources/{source_id}/save", response_model=SourceDetail)
async def save_source(source_id: UUID, body: SourcePin, db: DB, member: Editor) -> SourceDetail:
    src = await ResearchService.pin_source(db, member, source_id, body)
    out = SourceDetail.model_validate(src)
    await db.commit()
    return out


@router.get("/feeds", response_model=list[FeedOut])
async def list_feeds(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                     competitor_id: UUID | None = None) -> list[FeedOut]:
    rows = await ResearchService.list_feeds(db, member.workspace_id, brand_id=brand_id, competitor_id=competitor_id)
    return [FeedOut.model_validate(r) for r in rows]


@router.post("/feeds", response_model=FeedOut, status_code=status.HTTP_201_CREATED)
async def add_feed(body: FeedCreate, db: DB, member: Editor) -> FeedOut:
    feed = await ResearchService.add_feed(db, member, body)
    out = FeedOut.model_validate(feed)
    await db.commit()
    return out


@router.delete("/feeds/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(feed_id: UUID, db: DB, member: Editor) -> Response:
    await ResearchService.delete_feed(db, member, feed_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/feeds/{feed_id}/poll")
async def poll_feed(feed_id: UUID, db: DB, member: Editor) -> dict:
    res = await ResearchService.poll_feed(db, member.workspace_id, feed_id)
    await db.commit()
    return res


@router.get("/keywords", response_model=list[KeywordOut])
async def list_keywords(db: DB, member: CurrentMember, brand_id: UUID | None = None, q: str | None = None,
                        source: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 200) -> list[KeywordOut]:
    rows = await ResearchService.list_keywords(db, member.workspace_id, brand_id=brand_id, q=q, source=source, limit=limit)
    return [KeywordOut.model_validate(r) for r in rows]


@router.post("/keywords", response_model=KeywordOut, status_code=status.HTTP_201_CREATED)
async def add_keyword(body: KeywordCreate, db: DB, member: Editor) -> KeywordOut:
    kw = await ResearchService.upsert_keyword(db, member, body)
    out = KeywordOut.model_validate(kw)
    await db.commit()
    return out


@router.get("/keywords/lookup")
async def lookup_keyword(term: str, db: DB, member: CurrentMember, brand_id: UUID | None = None,
                         days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
    return await ResearchService.lookup_keyword(db, member.workspace_id, term, brand_id=brand_id, days=days)
