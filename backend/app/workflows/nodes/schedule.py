"""schedule — schedule approved variants via ``SchedulingService.schedule`` (APPROVAL by default; requires the
workflow's autonomous actions). Slot strategies: ``fixed`` (``at``), ``best_time`` (highest-scoring slot from
``SchedulingService.best_times``), ``next_slot`` (soonest free slot). The planned slots are shown to the approver; a
best-time slot that went stale while waiting for approval is recomputed. SchedulingService still refuses variants that
are not ``approved`` — AI-generated content always needs a human approval first."""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.errors import ProblemError
from app.models.content import ContentItem, ContentVariant
from app.models.enums import AccountStatus
from app.models.social import SocialAccount
from app.workflows.nodes import approve
from app.workflows.nodes.base import (
    NodeContext,
    NodeError,
    as_uuid,
    as_uuid_list,
    parse_dt,
    problem_message,
    utcnow,
)


def variant_ids(config: dict[str, Any]) -> list[UUID]:
    ids = as_uuid_list(config.get("variants"), "variants") if config.get("variants") else []
    if config.get("variant"):
        ids = as_uuid_list(config["variant"], "variant") + ids
    out: list[UUID] = []
    for i in ids:
        if i not in out:
            out.append(i)
    return out


async def load_variant(ctx: NodeContext, vid: UUID) -> ContentVariant:
    v = await ctx.db.get(ContentVariant, vid)
    if v is None or v.workspace_id != ctx.workspace_id:
        raise NodeError(f"content variant {vid} not found")
    return v


async def account_for(ctx: NodeContext, v: ContentVariant, config: dict[str, Any]) -> UUID:
    platform = getattr(v.platform, "value", v.platform)
    if config.get("account"):
        acc = await ctx.db.get(SocialAccount, as_uuid(config["account"], "account"))
        if acc is None or acc.workspace_id != ctx.workspace_id:
            raise NodeError("social account not found")
        return acc.id
    if v.social_account_id:
        return v.social_account_id
    item = await ctx.db.get(ContentItem, v.content_item_id)
    rows = (await ctx.db.execute(select(SocialAccount.id).where(
        SocialAccount.workspace_id == ctx.workspace_id, SocialAccount.brand_id == (item.brand_id if item else ctx.brand_id),
        SocialAccount.platform == v.platform, SocialAccount.status == AccountStatus.active)
        .order_by(SocialAccount.created_at))).scalars().all()
    if not rows:
        raise NodeError(f"no connected {platform} account for this brand")
    if len(rows) > 1:
        raise NodeError(f"several {platform} accounts are connected; set 'account' on the node")
    return rows[0]


async def pick_slot(ctx: NodeContext, v: ContentVariant, account_id: UUID, config: dict[str, Any],
                    taken: list[str]) -> str:
    from app.services.scheduling_service import SchedulingService
    strategy = config.get("strategy") or "best_time"
    if strategy == "fixed":
        at = parse_dt(config.get("at"))
        if at is None:
            raise NodeError("schedule strategy 'fixed' needs 'at'")
        return at.isoformat()
    item = await ctx.db.get(ContentItem, v.content_item_id)
    now = utcnow()
    res = await SchedulingService().best_times(ctx.db, item.brand_id if item else ctx.require_brand(),
                                               getattr(v.platform, "value", v.platform), account_id, now,
                                               now + timedelta(days=int(config.get("window_days") or 7)),
                                               count=50 if strategy == "next_slot" else 10, workspace_id=ctx.workspace_id)
    slots = [s for s in res.get("slots") or [] if s["at"] not in taken]
    if not slots:
        raise NodeError("no free publishing slot in the scheduling window")
    if strategy == "next_slot":
        slots.sort(key=lambda s: s["at"])
    return slots[0]["at"]


async def plan(ctx: NodeContext, config: dict[str, Any]) -> list[dict[str, Any]]:
    ids = variant_ids(config)
    if not ids:
        raise NodeError("no variant to act on (did the generate step produce one?)")
    out: list[dict[str, Any]] = []
    for vid in ids:
        v = await load_variant(ctx, vid)
        acc = await account_for(ctx, v, config)
        out.append({"variant_id": str(vid), "account_id": str(acc), "platform": getattr(v.platform, "value", v.platform),
                    "status": getattr(v.status, "value", v.status)})
    return out


async def gate(ctx: NodeContext, config: dict[str, Any], *, action: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Approval gate for schedule/publish. Returns a 'rejected' output, None to proceed, or raises NodeYield."""
    if (config.get("approval") or "required") == "required":
        ap = await approve.request(ctx, title=f"{action.title()} {len(items)} post(s) — {ctx.workflow.name}"[:300],
                                   description=f"Automation '{ctx.workflow.name}' wants to {action} these posts.",
                                   payload={"action": action, "items": items}, roles=None,
                                   timeout_hours=config.get("timeout_hours"))
        if ap is None:
            raise approve.pause(ctx)
        if getattr(ap.status, "value", ap.status) != "approved":
            return {**approve.decision_output(ap), "scheduled_post_ids": [], "rejected": True, "slots": items}
        return None
    for it in items:
        v = await load_variant(ctx, UUID(it["variant_id"]))
        if getattr(v.status, "value", v.status) != "approved":
            raise NodeError(f"variant {it['variant_id']} is {getattr(v.status, 'value', v.status)}; it must be approved "
                            f"by a human before it can be {action}d")
    return None


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    if not ctx.workflow.autonomous_actions_enabled:
        raise NodeError("autonomous actions are disabled for this workflow; nothing was scheduled")
    from app.services.scheduling_service import SchedulingService
    st = ctx.state
    if "plan" not in st:
        items = await plan(ctx, config)
        taken: list[str] = []
        for it in items:
            v = await load_variant(ctx, UUID(it["variant_id"]))
            it["at"] = await pick_slot(ctx, v, UUID(it["account_id"]), config, taken)
            taken.append(it["at"])
        st["plan"] = items
    items = st["plan"]
    if ctx.dry_run:
        return ctx.simulated(slots=items, scheduled_post_ids=[])
    rejected = await gate(ctx, config, action="schedule", items=items)
    if rejected is not None:
        return rejected
    actor = ctx.require_actor()
    svc = SchedulingService()
    ids: list[str] = []
    taken = []
    for it in items:
        v = await load_variant(ctx, UUID(it["variant_id"]))
        at = parse_dt(it["at"])
        if at is None or at < utcnow() + timedelta(minutes=2):
            if (config.get("strategy") or "best_time") == "fixed":
                raise NodeError(f"the fixed time {it['at']} passed before the schedule was approved")
            it["at"] = await pick_slot(ctx, v, UUID(it["account_id"]), config, taken)
            at = parse_dt(it["at"])
        taken.append(it["at"])
        item = await ctx.db.get(ContentItem, v.content_item_id)
        tz = "UTC"
        if item is not None:
            from app.models.brand import Brand
            brand = await ctx.db.get(Brand, item.brand_id)
            tz = brand.timezone if brand and brand.timezone else "UTC"
        try:
            sp = await svc.schedule(ctx.db, actor, v.id, UUID(it["account_id"]), at, tz,
                                    actor={"type": "system", "id": f"automation:{ctx.workflow.id}",
                                           "on_behalf_of": str(actor.user_id)})
        except ProblemError as e:
            raise NodeError(f"could not schedule variant {v.id}: {problem_message(e)}") from e
        ids.append(str(sp.id))
    return {"scheduled_post_ids": ids, "slots": items, "approval_id": st.get("approval_id")}
