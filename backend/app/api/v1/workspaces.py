"""Workspace routes: workspaces, members, invitations (+ top-level POST /invitations/{token}/accept)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import DB, CurrentUser, Member
from app.core.db import set_workspace
from app.core.errors import forbidden, not_found
from app.core.logging import request_context
from app.models.enums import MemberRole
from app.models.identity import Invitation
from app.schemas.identity import (
    InvitationAcceptOut,
    InvitationCreate,
    InvitationOut,
    MemberAdd,
    MemberOut,
    MemberRoleUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services.workspace_service import WorkspaceService

# prefix="" because this module serves both /workspaces/... and /invitations/{token}/accept (doc 00 §14).
router = APIRouter(prefix="", tags=["workspaces"])


async def path_member(ws: str, db: DB, user: CurrentUser) -> Member:
    """Membership for the workspace in the path (UUID or slug) — the path wins over X-Workspace-Id."""
    w = await WorkspaceService.resolve(db, ws)
    if not w:
        raise not_found("Workspace")
    m = await WorkspaceService.membership(db, w.id, user.id)
    if not m:
        raise not_found("Workspace")
    await set_workspace(db, w.id)
    request_context.set({**request_context.get(), "workspace_id": str(w.id)})
    return Member(user=user, workspace_id=w.id, role=m.role)


PathMember = Annotated[Member, Depends(path_member)]


def _require(member: Member, role: str) -> None:
    if not member.has(role):
        raise forbidden(f"Requires role {role} or higher")


def _inv_out(inv: Invitation, token: str | None = None) -> InvitationOut:
    out = InvitationOut.model_validate(inv).model_copy(update={"status": WorkspaceService.invitation_status(inv)})
    if token:
        out = out.model_copy(update={"token": token, "accept_url": WorkspaceService.accept_url(token)})
    return out


# ---------------------------------------------------------------- workspaces
@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser, db: DB) -> list[WorkspaceOut]:
    rows = await WorkspaceService.list_for_user(db, user.id)
    return [WorkspaceOut.model_validate(w).model_copy(update={"role": r}) for w, r in rows]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(body: WorkspaceCreate, user: CurrentUser, db: DB) -> WorkspaceOut:
    ws = await WorkspaceService.create(db, user, body.name, body.slug)
    await db.commit()
    return WorkspaceOut.model_validate(ws).model_copy(update={"role": MemberRole.owner})


@router.get("/workspaces/{ws}", response_model=WorkspaceOut)
async def get_workspace(member: PathMember, db: DB) -> WorkspaceOut:
    ws = await WorkspaceService.get(db, member.workspace_id)
    return WorkspaceOut.model_validate(ws).model_copy(update={"role": member.role})


@router.patch("/workspaces/{ws}", response_model=WorkspaceOut)
async def update_workspace(body: WorkspaceUpdate, member: PathMember, request: Request, db: DB) -> WorkspaceOut:
    ws = await WorkspaceService.update(db, member, name=body.name, slug=body.slug, request=request)
    await db.commit()
    return WorkspaceOut.model_validate(ws).model_copy(update={"role": member.role})


@router.delete("/workspaces/{ws}", status_code=204)
async def delete_workspace(member: PathMember, request: Request, db: DB) -> Response:
    await WorkspaceService.delete(db, member, request=request)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- members
@router.get("/workspaces/{ws}/members", response_model=list[MemberOut])
async def list_members(member: PathMember, db: DB) -> list[MemberOut]:
    return [MemberOut(**vars(m)) for m in await WorkspaceService.list_members(db, member.workspace_id)]


@router.post("/workspaces/{ws}/members", response_model=MemberOut, status_code=201)
async def add_member(body: MemberAdd, member: PathMember, request: Request, db: DB) -> MemberOut:
    row = await WorkspaceService.add_member(db, member, body.email, body.role, request=request)
    await db.commit()
    return MemberOut(**vars(row))


@router.patch("/workspaces/{ws}/members/{user_id}", response_model=MemberOut)
async def change_member_role(user_id: UUID, body: MemberRoleUpdate, member: PathMember, request: Request, db: DB) -> MemberOut:
    row = await WorkspaceService.change_role(db, member, user_id, body.role, request=request)
    await db.commit()
    return MemberOut(**vars(row))


@router.delete("/workspaces/{ws}/members/{user_id}", status_code=204)
async def remove_member(user_id: UUID, member: PathMember, request: Request, db: DB) -> Response:
    await WorkspaceService.remove_member(db, member, user_id, request=request)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- invitations
@router.get("/workspaces/{ws}/invitations", response_model=list[InvitationOut])
async def list_invitations(member: PathMember, db: DB, include_accepted: bool = False) -> list[InvitationOut]:
    _require(member, "admin")
    return [_inv_out(i) for i in await WorkspaceService.list_invitations(db, member.workspace_id, include_accepted)]


@router.post("/workspaces/{ws}/invitations", response_model=InvitationOut, status_code=201)
async def create_invitation(body: InvitationCreate, member: PathMember, request: Request, db: DB) -> InvitationOut:
    inv, token = await WorkspaceService.create_invitation(db, member, body.email, body.role, request=request)
    await db.commit()
    return _inv_out(inv, token)


@router.delete("/workspaces/{ws}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(invitation_id: UUID, member: PathMember, request: Request, db: DB) -> Response:
    await WorkspaceService.revoke_invitation(db, member, invitation_id, request=request)
    await db.commit()
    return Response(status_code=204)


@router.post("/invitations/{token}/accept", response_model=InvitationAcceptOut)
async def accept_invitation(token: str, user: CurrentUser, request: Request, db: DB) -> InvitationAcceptOut:
    ws, role = await WorkspaceService.accept_invitation(db, user, token, request=request)
    await db.commit()
    return InvitationAcceptOut(workspace=WorkspaceOut.model_validate(ws).model_copy(update={"role": role}), role=role)
