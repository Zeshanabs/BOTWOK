"""FastAPI dependencies: db session, current user, current member (workspace scope + RLS), role checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session, set_workspace
from app.core.errors import ProblemError, forbidden
from app.core.logging import request_context
from app.core.security import decode_access_token
from app.models.enums import ROLE_RANK, MemberRole
from app.models.identity import User, WorkspaceMember

DB = Annotated[AsyncSession, Depends(get_session)]


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("botwok_access")


async def current_user(request: Request, db: DB) -> User:
    token = _bearer(request)
    if not token:
        raise ProblemError(401, "unauthorized", "Authentication required")
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as e:
        raise ProblemError(401, "token_expired", "Access token expired") from e
    except jwt.PyJWTError as e:
        raise ProblemError(401, "unauthorized", "Invalid token") from e
    user = await db.get(User, UUID(claims["sub"]))
    if not user or not user.is_active:
        raise ProblemError(401, "unauthorized", "User not found")
    request_context.set({**request_context.get(), "user_id": str(user.id)})
    return user


CurrentUser = Annotated[User, Depends(current_user)]


@dataclass
class Member:
    user: User
    workspace_id: UUID
    role: MemberRole

    def has(self, role: str) -> bool:
        return ROLE_RANK[self.role.value] >= ROLE_RANK[role]


async def current_member(request: Request, db: DB, user: CurrentUser,
                         x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id")) -> Member:
    ws = x_workspace_id or request.path_params.get("ws") or request.query_params.get("workspace_id")
    if not ws:
        if user.memberships:
            ws = str(user.memberships[0].workspace_id)
        else:
            raise ProblemError(400, "workspace_required", "X-Workspace-Id header required")
    try:
        ws_id = UUID(str(ws))
    except ValueError as e:
        raise ProblemError(400, "workspace_required", "Invalid workspace id") from e
    m = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id))).scalar_one_or_none()
    if not m:
        raise forbidden("Not a member of this workspace")
    await set_workspace(db, ws_id)
    request_context.set({**request_context.get(), "workspace_id": str(ws_id)})
    return Member(user=user, workspace_id=ws_id, role=m.role)


CurrentMember = Annotated[Member, Depends(current_member)]


def require_role(role: str):
    async def _check(member: CurrentMember) -> Member:
        if not member.has(role):
            raise forbidden(f"Requires role {role} or higher")
        return member
    return _check
