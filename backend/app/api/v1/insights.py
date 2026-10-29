"""Insights & recommendations API (doc 13 §13.5, doc 17): list, analyze, recommendations, decisions, acknowledge."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.pagination import Page
from app.schemas.insights import (
    AcknowledgeIn,
    AnalyzeIn,
    AnalyzeOut,
    InsightOut,
    RecommendationDecisionIn,
    RecommendationOut,
)
from app.services.insight_service import (
    INSIGHT_KINDS,
    INSIGHT_STATUSES,
    RECOMMENDATION_STATUSES,
    InsightService,
)

router = APIRouter(prefix="/insights", tags=["insights"])
Editor = Annotated[Member, Depends(require_role("editor"))]


@router.get("", response_model=Page[InsightOut])
async def list_insights(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                        kind: Annotated[str | None, Query(pattern="^(" + "|".join(INSIGHT_KINDS) + ")$")] = None,
                        status_: Annotated[str | None, Query(alias="status", pattern="^(" + "|".join(INSIGHT_STATUSES) + ")$")] = None,
                        since: datetime | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None):
    rows, nxt = await InsightService.list_insights(db, member.workspace_id, brand_id=brand_id, kind=kind, status=status_,
                                                   since=since, limit=limit, cursor=cursor)
    return Page[InsightOut](items=[InsightOut.model_validate(r) for r in rows], next_cursor=nxt)


@router.post("/analyze", response_model=AnalyzeOut, response_model_exclude_none=True,
             responses={202: {"model": AnalyzeOut, "description": "AI analysis started"}})
async def analyze(body: AnalyzeIn, db: DB, member: Editor, response: Response):
    res = await InsightService.analyze(db, member, body.brand_id, body.period_days, mode=body.mode, metric=body.metric)
    await db.commit()
    response.status_code = status.HTTP_202_ACCEPTED if res.get("run_id") else status.HTTP_200_OK
    return AnalyzeOut.model_validate(res)


@router.get("/recommendations", response_model=Page[RecommendationOut])
async def list_recommendations(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                               status_: Annotated[str | None, Query(alias="status", pattern="^(" + "|".join(RECOMMENDATION_STATUSES) + ")$")] = None,
                               insight_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                               cursor: str | None = None):
    rows, nxt = await InsightService.list_recommendations(db, member.workspace_id, brand_id=brand_id, status=status_,
                                                          insight_id=insight_id, limit=limit, cursor=cursor)
    return Page[RecommendationOut](items=[RecommendationOut.model_validate(r) for r in rows], next_cursor=nxt)


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationOut)
async def get_recommendation(recommendation_id: UUID, db: DB, member: CurrentMember):
    return RecommendationOut.model_validate(await InsightService.get_recommendation(db, member.workspace_id, recommendation_id))


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationOut)
async def decide_recommendation(recommendation_id: UUID, body: RecommendationDecisionIn, db: DB, member: Editor):
    rec = await InsightService.decide_recommendation(db, member, recommendation_id, body.status, reason=body.reason)
    out = RecommendationOut.model_validate(rec)
    await db.commit()
    return out


@router.get("/{insight_id}", response_model=InsightOut)
async def get_insight(insight_id: UUID, db: DB, member: CurrentMember):
    return InsightOut.model_validate(await InsightService.get_insight(db, member.workspace_id, insight_id))


@router.post("/{insight_id}/acknowledge", response_model=InsightOut)
async def acknowledge(insight_id: UUID, db: DB, member: Editor, body: AcknowledgeIn | None = None):
    ins = await InsightService.acknowledge_insight(db, member, insight_id, (body or AcknowledgeIn()).status)
    out = InsightOut.model_validate(ins)
    await db.commit()
    return out
