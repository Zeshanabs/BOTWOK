"""Social accounts API (doc 17 "Social"): connect/callback/select, list, test, refresh, disconnect, capabilities matrix."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import DB, CurrentMember, Member, require_role
from app.config import settings
from app.core.errors import ProblemError
from app.integrations.social.registry import capabilities_matrix
from app.schemas.social import AccountHealthOut, ConnectStartOut, SelectIn, SelectionOut, SocialAccountOut
from app.services.social_account_service import SocialAccountService
from app.services.token_vault import TokenVault

router = APIRouter(prefix="/social", tags=["social"])
Admin = Annotated[Member, Depends(require_role("admin"))]


async def _out(db: DB, account) -> SocialAccountOut:
    out = SocialAccountOut.model_validate(account)
    out.token_expires_at = await TokenVault().access_expires_at(db, account.id)
    return out


@router.get("/accounts", response_model=list[SocialAccountOut])
async def list_accounts(db: DB, member: CurrentMember, brand_id: UUID | None = None, include_disconnected: bool = False):
    rows = await SocialAccountService.list(db, member.workspace_id, brand_id, include_disconnected)
    return [await _out(db, a) for a in rows]


@router.get("/capabilities")
async def capabilities(member: CurrentMember):
    return capabilities_matrix()


@router.get("/connect/{platform}", response_model=ConnectStartOut)
async def connect_start(platform: str, db: DB, member: Admin, brand_id: UUID, flavor: str | None = None):
    res = await SocialAccountService.connect_start(db, member, platform, brand_id, flavor)
    await db.commit()
    return ConnectStartOut(**res)


@router.get("/callback/{platform}", include_in_schema=True)
async def callback(platform: str, db: DB, code: str | None = None, state: str | None = None,
                   error: str | None = None, error_description: str | None = None):
    """Public: the platform redirects here. Validates the single-use state and redirects into the app."""
    base = settings.public_base_url.rstrip("/")
    if error or not code or not state:
        raise ProblemError(400, "oauth_denied" if error else "invalid_state", "OAuth callback failed",
                           error_description or error or "missing code/state")
    res = await SocialAccountService.handle_callback(db, platform, code, state)
    await db.commit()
    slug = res.get("workspace_slug") or ""
    if res["status"] == "connected":
        return RedirectResponse(f"{base}/w/{slug}/settings/social?connected={res['account_id']}", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(f"{base}/w/{slug}/settings/social?select={res['selection_token']}&platform={platform}",
                            status_code=status.HTTP_302_FOUND)


@router.get("/connect/{platform}/selection", response_model=SelectionOut)
async def selection(platform: str, member: Admin, selection_token: str = Query(...)):
    """Accounts stashed for a pending selection (so the UI can render the picker after the redirect)."""
    payload = await SocialAccountService._unstash(selection_token)
    if not payload or payload.get("platform") != platform or payload.get("workspace_id") != str(member.workspace_id):
        raise ProblemError(400, "invalid_selection_token", "Selection token invalid or expired")
    return SelectionOut(selection_token=selection_token, platform=platform,
                        accounts=[{k: v for k, v in a.items() if k != "extra"} for a in payload["accounts"]])


@router.post("/connect/{platform}/select", response_model=SocialAccountOut, status_code=status.HTTP_201_CREATED)
async def select_account(platform: str, body: SelectIn, db: DB, member: Admin):
    account = await SocialAccountService.select_account(db, member, platform, body.selection_token, body.external_id)
    await db.commit()
    return await _out(db, account)


@router.get("/accounts/{account_id}", response_model=SocialAccountOut)
async def get_account(account_id: UUID, db: DB, member: CurrentMember):
    return await _out(db, await SocialAccountService.get(db, member.workspace_id, account_id))


@router.post("/accounts/{account_id}/test", response_model=AccountHealthOut)
async def test_account(account_id: UUID, db: DB, member: CurrentMember):
    res = await SocialAccountService.test(db, member, account_id)
    await db.commit()
    return AccountHealthOut(**res)


@router.post("/accounts/{account_id}/refresh", response_model=SocialAccountOut)
async def refresh_account(account_id: UUID, db: DB, member: Admin):
    account = await SocialAccountService.refresh(db, member, account_id)
    await db.commit()
    return await _out(db, account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(account_id: UUID, db: DB, member: Admin, force: bool = False):
    await SocialAccountService.disconnect(db, member, account_id, force=force)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
