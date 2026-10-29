"""ApprovalService — approval requests, decisions, expiry and resume hooks (doc 05 §5.2.8, doc 17 "Approvals",
doc 19 §19.7).

Kinds: ``content`` (target content_item/content_variant → ContentService.transition), ``ai_action`` / ``spend``
(→ ``app.agents.orchestrator.approval_gate.on_approved/on_rejected`` when installed), ``automation_step``
(→ ``app.workflows.engine.on_approval_decided`` on approve/reject/expire).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import _compat
from app.core.errors import conflict, forbidden, not_found, validation
from app.core.events import emit
from app.core.logging import get_logger
from app.core.pagination import encode_cursor
from app.models import Approval, ContentItem, ContentVariant, WorkspaceMember
from app.models.enums import ApprovalStatus, ContentStatus, MemberRole

log = get_logger("approvals")

DEFAULT_ROLES = [MemberRole.approver, MemberRole.admin, MemberRole.owner]
KINDS = ("content", "ai_action", "automation_step", "spend")


def _roles(roles: Any) -> list[MemberRole]:
    out = []
    for r in roles or DEFAULT_ROLES:
        out.append(r if isinstance(r, MemberRole) else MemberRole(str(r)))
    return out


def _user_uuid(requested_by: str | None) -> UUID | None:
    try:
        return UUID(str(requested_by))
    except (TypeError, ValueError):
        return None


class ApprovalService:
    @staticmethod
    async def create(db: AsyncSession, workspace_id: UUID, brand_id: UUID | None, kind: str, target_type: str,
                     target_id: UUID, payload: dict[str, Any] | None, requested_by: str,
                     required_roles: list[Any] | None = None, expires_in_hours: int | None = 72, *,
                     actor: Any = None) -> Approval:
        if kind not in KINDS:
            raise validation(f"Unknown approval kind {kind}")
        ap = Approval(workspace_id=workspace_id, brand_id=brand_id, kind=kind, target_type=target_type, target_id=target_id,
                      payload=payload or {}, status=ApprovalStatus.pending, requested_by=str(requested_by),
                      required_roles=_roles(required_roles),
                      expires_at=(datetime.now(UTC) + timedelta(hours=expires_in_hours)) if expires_in_hours else None)
        db.add(ap)
        await db.flush()
        await db.refresh(ap)
        ev_actor = getattr(actor, "event_actor", None) or (
            {"type": "agent", "id": requested_by[6:]} if str(requested_by).startswith("agent:") else
            {"type": "user", "id": str(requested_by)})
        await emit(db, "APPROVAL_REQUESTED", {"approval_id": str(ap.id), "kind": kind, "brand_id": str(brand_id) if brand_id else None,
                                              "target": {"type": target_type, "id": str(target_id)},
                                              "required_roles": [r.value for r in ap.required_roles]},
                   workspace_id=workspace_id, actor=ev_actor)
        await _compat.audit(db, getattr(actor, "audit_actor", None) or actor, "approval.request", "approval", ap.id,
                            after={"kind": kind, "target_type": target_type, "target_id": str(target_id)})
        await ApprovalService._notify_approvers(db, ap)
        return ap

    @staticmethod
    async def _notify_approvers(db: AsyncSession, ap: Approval) -> None:
        title = (ap.payload or {}).get("title") or ap.target_type.replace("_", " ")
        roles = [r.value if hasattr(r, "value") else str(r) for r in ap.required_roles or []]
        members = (await db.execute(select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == ap.workspace_id, WorkspaceMember.role.in_(roles)))).scalars().all()
        requester = _user_uuid(ap.requested_by)
        for uid in members:
            if uid == requester:
                continue
            await _compat.notify(db, ap.workspace_id, "approval_requested", f"Approval needed: {title}",
                                 (ap.payload or {}).get("comment"), f"/approvals/{ap.id}", user_id=uid,
                                 severity="warning" if (ap.payload or {}).get("risk_level") == "high" else "info")

    @staticmethod
    async def list(db: AsyncSession, member: Any, *, status: list[str] | None = None, brand_id: Any = None,
                   kind: str | None = None, target_id: Any = None, limit: int = 50,
                   cursor: str | None = None) -> tuple[list[Approval], str | None]:
        q = select(Approval).where(Approval.workspace_id == member.workspace_id)
        if status:
            try:
                q = q.where(Approval.status.in_([ApprovalStatus(s) for s in status]))
            except ValueError as e:
                raise validation(f"Invalid status filter: {status}") from e
        if brand_id:
            q = q.where(Approval.brand_id == UUID(str(brand_id)))
        if kind:
            q = q.where(Approval.kind == kind)
        if target_id:
            q = q.where(Approval.target_id == UUID(str(target_id)))
        from app.services.content_service import _cursor
        cur = _cursor(cursor)
        if cur:
            t = datetime.fromisoformat(cur["t"])
            q = q.where(or_(Approval.created_at < t, and_(Approval.created_at == t, Approval.id < UUID(cur["id"]))))
        rows = list((await db.execute(q.order_by(Approval.created_at.desc(), Approval.id.desc()).limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @staticmethod
    async def get(db: AsyncSession, workspace_id: UUID, approval_id: Any, *, for_update: bool = False) -> Approval:
        try:
            aid = UUID(str(approval_id))
        except ValueError as e:
            raise not_found("Approval") from e
        q = select(Approval).where(Approval.id == aid, Approval.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        ap = (await db.execute(q)).scalar_one_or_none()
        if ap is None:
            raise not_found("Approval")
        return ap

    @staticmethod
    async def preview(db: AsyncSession, ap: Approval) -> dict[str, Any] | None:
        """Target preview for approvers: item + variants + critique + factcheck + sources + generation metadata."""
        from app.services.content_service import ContentService
        item_id = None
        variant_id = None
        if ap.target_type == "content_item":
            item_id = ap.target_id
        elif ap.target_type == "content_variant":
            variant_id = ap.target_id
            item_id = (await db.execute(select(ContentVariant.content_item_id).where(
                ContentVariant.id == ap.target_id, ContentVariant.workspace_id == ap.workspace_id))).scalar_one_or_none()
        if item_id is None:
            return {"type": ap.target_type, "id": ap.target_id, "payload": ap.payload}
        item = (await db.execute(select(ContentItem).where(ContentItem.id == item_id,
                                                           ContentItem.workspace_id == ap.workspace_id)
                                 .execution_options(populate_existing=True))).scalar_one_or_none()
        if item is None:
            return {"type": ap.target_type, "id": ap.target_id, "missing": True}
        data = await ContentService.serialize_item(db, item)
        return {"type": ap.target_type, "id": ap.target_id, "item": data, "variant_id": variant_id,
                "variants": data["variants"], "critique": item.critique, "factcheck": item.factcheck,
                "sources": data["sources"], "generation_metadata": item.generation_metadata, "risk_level": item.risk_level}

    @staticmethod
    def _check_pending(ap: Approval) -> None:
        if ap.status != ApprovalStatus.pending:
            raise conflict("approval_not_pending", f"Approval is already {ap.status.value}")

    @staticmethod
    def _check_role(member: Any, ap: Approval) -> None:
        role = getattr(member.role, "value", member.role)
        allowed = {r.value if hasattr(r, "value") else str(r) for r in ap.required_roles or DEFAULT_ROLES}
        if role not in allowed:
            raise forbidden(f"This approval requires one of: {', '.join(sorted(allowed))}")

    @staticmethod
    async def _expire_if_due(db: AsyncSession, ap: Approval) -> bool:
        if ap.expires_at and ap.expires_at < datetime.now(UTC):
            ap.status = ApprovalStatus.expired
            ap.decided_at = datetime.now(UTC)
            ap.decision_comment = "expired"
            await db.flush()
            return True
        return False

    @staticmethod
    async def _automation_hook(db: AsyncSession, ap: Approval) -> None:
        """``automation_step`` approvals resume their automation run (app.workflows.engine, lazy import)."""
        fn = _compat.optional_attr("app.workflows.engine", "on_approval_decided")
        if fn is not None:
            await fn(db, ap)

    @staticmethod
    async def _hook(name: str, db: AsyncSession, ap: Approval) -> Any:
        fn = _compat.optional_attr("app.agents.orchestrator.approval_gate", name)
        if fn is None:
            log.info("approval_gate.unavailable", hook=name, approval_id=str(ap.id))
            return None
        res = fn(db, ap)
        if hasattr(res, "__await__"):
            res = await res
        return res

    @staticmethod
    async def approve(db: AsyncSession, member: Any, approval_id: Any, comment: str | None = None) -> Approval:
        from app.services.content_service import ContentService
        ap = await ApprovalService.get(db, member.workspace_id, approval_id, for_update=True)
        ApprovalService._check_pending(ap)
        if await ApprovalService._expire_if_due(db, ap):
            raise conflict("approval_expired", "This approval request has expired")
        ApprovalService._check_role(member, ap)
        now = datetime.now(UTC)
        ap.status = ApprovalStatus.approved
        ap.decided_by = member.user.id
        ap.decided_at = now
        ap.decision_comment = comment
        await db.flush()
        actor = {"type": "user", "id": str(member.user.id)}
        if ap.kind == "content":
            item_id = await ApprovalService._content_item_id(db, ap)
            await ContentService.transition(db, member, item_id, ContentStatus.approved, comment, approval=ap)
            await emit(db, "CONTENT_APPROVED", {"approval_id": str(ap.id), "content_item_id": str(item_id),
                                                "brand_id": str(ap.brand_id) if ap.brand_id else None,
                                                "approver": str(member.user.id), "comment": comment},
                       workspace_id=ap.workspace_id, actor=actor)
        elif ap.kind == "automation_step":
            await ApprovalService._automation_hook(db, ap)
        elif ap.kind in ("ai_action", "spend"):
            await ApprovalService._hook("on_approved", db, ap)
        await _compat.audit(db, member, "approval.approve", "approval", ap.id, before={"status": "pending"},
                            after={"status": "approved", "comment": comment, "kind": ap.kind,
                                   "target_id": str(ap.target_id)})
        await ApprovalService._notify_requester(db, ap, member, "approved")
        return ap

    @staticmethod
    async def reject(db: AsyncSession, member: Any, approval_id: Any, comment: str, decision: str = "reject") -> Approval:
        from app.services.content_service import ContentService
        if not (comment or "").strip():
            raise validation("A comment is required when rejecting",
                             [{"code": "required", "field": "comment", "message": "Comment is required"}])
        if decision not in ("reject", "request_changes"):
            raise validation("decision must be reject or request_changes")
        ap = await ApprovalService.get(db, member.workspace_id, approval_id, for_update=True)
        ApprovalService._check_pending(ap)
        if await ApprovalService._expire_if_due(db, ap):
            raise conflict("approval_expired", "This approval request has expired")
        ApprovalService._check_role(member, ap)
        ap.status = ApprovalStatus.rejected
        ap.decided_by = member.user.id
        ap.decided_at = datetime.now(UTC)
        ap.decision_comment = comment
        ap.payload = {**(ap.payload or {}), "decision": decision}
        await db.flush()
        if ap.kind == "content":
            item_id = await ApprovalService._content_item_id(db, ap)
            to = ContentStatus.draft if decision == "request_changes" else ContentStatus.rejected
            await ContentService.transition(db, member, item_id, to, comment, approval=ap)
            await emit(db, "CONTENT_REJECTED", {"approval_id": str(ap.id), "content_item_id": str(item_id),
                                                "brand_id": str(ap.brand_id) if ap.brand_id else None,
                                                "approver": str(member.user.id), "comment": comment, "decision": decision},
                       workspace_id=ap.workspace_id, actor={"type": "user", "id": str(member.user.id)})
        elif ap.kind == "automation_step":
            await ApprovalService._automation_hook(db, ap)
        elif ap.kind in ("ai_action", "spend"):
            await ApprovalService._hook("on_rejected", db, ap)
        await _compat.audit(db, member, "approval.reject", "approval", ap.id, before={"status": "pending"},
                            after={"status": "rejected", "comment": comment, "decision": decision, "kind": ap.kind,
                                   "target_id": str(ap.target_id)})
        await ApprovalService._notify_requester(db, ap, member, "changes requested" if decision == "request_changes" else "rejected")
        return ap

    @staticmethod
    async def _content_item_id(db: AsyncSession, ap: Approval) -> UUID:
        if ap.target_type == "content_variant":
            iid = (await db.execute(select(ContentVariant.content_item_id).where(
                ContentVariant.id == ap.target_id, ContentVariant.workspace_id == ap.workspace_id))).scalar_one_or_none()
            if iid is None:
                raise not_found("Content")
            return iid
        return ap.target_id

    @staticmethod
    async def _notify_requester(db: AsyncSession, ap: Approval, member: Any, verb: str) -> None:
        uid = _user_uuid(ap.requested_by)
        if uid is None or uid == member.user.id:
            return
        title = (ap.payload or {}).get("title") or ap.target_type.replace("_", " ")
        await _compat.notify(db, ap.workspace_id, f"approval_{ap.status.value}", f"'{title}' was {verb}",
                             ap.decision_comment, f"/approvals/{ap.id}", user_id=uid,
                             severity="success" if verb == "approved" else "warning")

    @staticmethod
    async def expire(db: AsyncSession, workspace_id: UUID | None = None) -> int:
        """Mark pending approvals past ``expires_at`` as expired. Returns the count."""
        stmt = (update(Approval).where(Approval.status == ApprovalStatus.pending, Approval.expires_at.is_not(None),
                                       Approval.expires_at < datetime.now(UTC))
                .values(status=ApprovalStatus.expired, decided_at=datetime.now(UTC), decision_comment="expired")
                .returning(Approval.id, Approval.workspace_id, Approval.kind))
        if workspace_id:
            stmt = stmt.where(Approval.workspace_id == workspace_id)
        rows = (await db.execute(stmt)).all()
        for r in rows:
            if r.kind in ("ai_action", "automation_step", "spend"):
                ap = await db.get(Approval, r.id)
                if ap is not None:
                    try:
                        if r.kind == "automation_step":
                            await ApprovalService._automation_hook(db, ap)
                            continue
                        await ApprovalService._hook("on_expired", db, ap)
                    except Exception as e:
                        log.warning("approval.expire_hook_failed", approval_id=str(r.id), error=str(e))
        return len(rows)
