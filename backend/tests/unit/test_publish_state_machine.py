"""Publish worker state machine (doc 11 §11.3) driven with an in-memory FakeAdapter against the REAL local database.

Marked ``integration``; skipped when DATABASE_URL is unreachable. Each test creates its own workspace/brand/account/
variant rows and deletes the workspace at the end (cascades).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.core.errors import ProblemError
from app.core.ids import new_id
from app.core.ports.social_adapter import (
    Capabilities,
    PublishError,
    PublishRequest,
    PublishResult,
    RemotePost,
    TokenSet,
    ValidationResult,
)
from app.integrations.social.base import BaseAdapter, normalize_text
from app.models.brand import Brand
from app.models.content import ContentItem, ContentVariant
from app.models.enums import AccountStatus, ContentFormat, ContentStatus, MemberRole, Platform, ScheduleStatus
from app.models.identity import User, Workspace, WorkspaceMember
from app.models.scheduling import PublishAttempt, PublishedPost, ScheduledPost
from app.models.social import SocialAccount
from app.services.publishing_service import PublishingService
from app.services.scheduling_service import SchedulingService, dispatch_due_posts, dispatch_retries
from app.services.token_vault import TokenVault

pytestmark = pytest.mark.integration
TEST_QUEUE = "publishing-tests"   # a live worker (make dev) listens on "publishing"; keep test jobs out of its reach


async def _db_reachable() -> bool:
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def _engine_guard(monkeypatch):
    """asyncpg connections are loop-bound: dispose the pool so each test's event loop starts clean. Jobs go to an
    isolated queue and adapters resolve to the test fakes (never real HTTP)."""
    import app.services.analytics_sync_service as ass
    import app.services.publishing_service as ps
    import app.services.scheduling_service as ss
    monkeypatch.setattr(ps, "PUBLISH_QUEUE", TEST_QUEUE)
    monkeypatch.setattr(ss, "PUBLISH_QUEUE", TEST_QUEUE)
    monkeypatch.setattr(ass, "SYNC_TASK", "jobs.analytics.sync_account")
    await engine.dispose()
    if not await _db_reachable():
        pytest.skip("DATABASE_URL unreachable")
    yield
    await engine.dispose()


# ------------------------------------------------------------------------------------------ fake adapter
class FakeAdapter(BaseAdapter):
    """Scripted adapter: ``script`` is a list of actions consumed per publish() call.

    * ``"ok"`` → publish succeeds (one id per segment)
    * ``PublishError(...)`` → raised as-is
    * ``"ambiguous_posted"`` → the platform *did* create the post, then the connection died
    * ``"partial"`` → first missing segment is posted, then a transient error
    """
    platform = "x"
    verified_at = "2026-10-08"

    def __init__(self, script: list[Any] | None = None, *, can_list: bool = True, refresh_ok: bool = True):
        super().__init__()
        self.script = list(script or [])
        self.remote: list[RemotePost] = []
        self.publish_calls = 0
        self.refresh_calls = 0
        self.can_list_own_posts = can_list
        self.refresh_ok = refresh_ok
        self.deleted: list[str] = []

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(formats=["text", "image"], max_text=280, max_media=4, native_schedule=False, can_delete=True, supports_alt_text=True)

    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        return ValidationResult(ok=True)

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        return {"token_valid": True, "scopes_missing": [], "limits_remaining": None}

    def refresh_supported(self, tokens: TokenSet | None = None) -> bool:
        return True

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        self.refresh_calls += 1
        if not self.refresh_ok:
            raise PublishError("auth", "refresh rejected", code="invalid_grant")
        return TokenSet(access_token="refreshed-" + uuid.uuid4().hex[:6], refresh_token=tokens.refresh_token,
                        expires_at=datetime.now(UTC) + timedelta(days=60), scopes=tokens.scopes)

    def _post(self, text_: str) -> str:
        ext = f"ext-{len(self.remote) + 1}-{uuid.uuid4().hex[:4]}"
        self.remote.append(RemotePost(external_id=ext, text=text_, created_at=datetime.now(UTC), url=f"https://x.test/{ext}"))
        return ext

    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        self.publish_calls += 1
        action = self.script.pop(0) if self.script else "ok"
        if isinstance(action, Exception):
            raise action
        segments = req.segments or [req.text]
        done: list[str] = state.setdefault("segment_external_ids", [])
        if action == "ambiguous_posted":
            self._post(segments[0])
            raise PublishError("ambiguous", "read timeout after send", code="ReadTimeout")
        for i, seg in enumerate(segments):
            if i < len(done):
                continue
            done.append(self._post(seg))
            state["segment_external_ids"] = done
            if action == "partial":
                raise PublishError("transient", "503 after first segment", code="503")
        return PublishResult(external_id=done[0], external_url=f"https://x.test/{done[0]}", published_at=datetime.now(UTC),
                             segments=[{"index": i, "external_id": e} for i, e in enumerate(done)], raw={"cost_usd": 0.015})

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        return [p for p in self.remote if p.created_at and p.created_at >= since]

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        self.deleted.append(external_id)


# ------------------------------------------------------------------------------------------ fixtures
class Member:
    def __init__(self, user: User, workspace_id):
        self.user = user
        self.workspace_id = workspace_id
        self.role = MemberRole.owner

    def has(self, role: str) -> bool:
        return True


class World:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def make_world(db, *, status: ScheduleStatus = ScheduleStatus.queued, segments: list[str] | None = None, text_: str = "Hello world",
                     scheduled_at: datetime | None = None, max_attempts: int = 5) -> World:
    tag = uuid.uuid4().hex[:8]
    user = User(id=new_id(), email=f"pub-{tag}@test.local", full_name="Pub Tester", password_hash="x")
    ws = Workspace(id=new_id(), name=f"ws-{tag}", slug=f"ws-{tag}", created_by=user.id)
    db.add_all([user, ws])
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))
    brand = Brand(id=new_id(), workspace_id=ws.id, name="Brand", slug=f"brand-{tag}", timezone="UTC", created_by=user.id)
    db.add(brand)
    await db.flush()
    account = SocialAccount(id=new_id(), workspace_id=ws.id, brand_id=brand.id, platform=Platform.x, auth_flavor="default", external_id=f"x-{tag}",
                            display_name="@test", handle="test", status=AccountStatus.active, scopes=["tweet.write"], connected_by=user.id)
    db.add(account)
    await db.flush()
    await TokenVault().store(db, ws.id, account.id, "access", "tok-" + tag, expires_at=datetime.now(UTC) + timedelta(days=30))
    await TokenVault().store(db, ws.id, account.id, "refresh", "ref-" + tag)
    item = ContentItem(id=new_id(), workspace_id=ws.id, brand_id=brand.id, title="Item", master_format=ContentFormat.text, status=ContentStatus.approved,
                       created_by=user.id)
    db.add(item)
    await db.flush()
    variant = ContentVariant(id=new_id(), workspace_id=ws.id, content_item_id=item.id, platform=Platform.x, format=ContentFormat.text, text=text_,
                             segments=segments or [], status=ContentStatus.approved)
    db.add(variant)
    await db.flush()
    sp = None
    if status is not None:
        sp = ScheduledPost(id=new_id(), workspace_id=ws.id, brand_id=brand.id, content_variant_id=variant.id, social_account_id=account.id,
                           scheduled_at=scheduled_at or datetime.now(UTC) - timedelta(minutes=1), timezone="UTC", status=status,
                           queued_at=datetime.now(UTC) if status == ScheduleStatus.queued else None, created_by=user.id, max_attempts=max_attempts)
        db.add(sp)
        await db.flush()
    await db.commit()
    return World(user=user, ws=ws, brand=brand, account=account, item=item, variant=variant, sp=sp, member=Member(user, ws.id))


async def cleanup(ws_id, user_id) -> None:
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM procrastinate_jobs WHERE args->>'workspace_id' = :ws"), {"ws": str(ws_id)})
        await db.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": ws_id})
        await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await db.commit()


async def reload_sp(sp_id) -> ScheduledPost:
    async with SessionLocal() as db:
        return (await db.execute(select(ScheduledPost).where(ScheduledPost.id == sp_id))).scalars().unique().one()


async def attempts(sp_id) -> list[PublishAttempt]:
    async with SessionLocal() as db:
        return list((await db.execute(select(PublishAttempt).where(PublishAttempt.scheduled_post_id == sp_id).order_by(PublishAttempt.attempt_no))).scalars())


async def published(sp_id) -> list[PublishedPost]:
    async with SessionLocal() as db:
        return list((await db.execute(select(PublishedPost).where(PublishedPost.scheduled_post_id == sp_id))).scalars())


async def events(ws_id, name: str) -> int:
    async with SessionLocal() as db:
        return int((await db.execute(text("SELECT count(*) FROM events_outbox WHERE workspace_id=:ws AND name=:n"), {"ws": ws_id, "n": name})).scalar())


async def pending_jobs(sp_id) -> int:
    async with SessionLocal() as db:
        return int((await db.execute(text("SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock=:l AND status='todo'"), {"l": f"publish:{sp_id}"})).scalar())


def service(adapter: FakeAdapter) -> PublishingService:
    return PublishingService(session_factory=SessionLocal, adapter_for=lambda account: adapter)


# ------------------------------------------------------------------------------------------ tests
async def test_happy_path_publishes_once_and_records_ledger():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter()
        out = await service(fake).run_attempt(w.sp.id, 1, w.ws.id)
        assert out == "published"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.published and sp.attempt_count == 1 and sp.published_at is not None
        pp = await published(w.sp.id)
        assert len(pp) == 1 and pp[0].external_id == fake.remote[0].external_id and pp[0].raw["fingerprint"]
        att = await attempts(w.sp.id)
        assert len(att) == 1 and att[0].status == "succeeded" and att[0].idempotency_key == f"{sp.idempotency_root}:1"
        assert await events(w.ws.id, "PUBLISH_STARTED") == 1 and await events(w.ws.id, "PUBLISH_SUCCESS") == 1
        # stale/duplicate job → no-op, no second platform call
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "stale"
        assert fake.publish_calls == 1 and len(fake.remote) == 1
        async with SessionLocal() as db:
            n = (await db.execute(text("SELECT count(*) FROM usage_ledger WHERE workspace_id=:ws AND kind='platform_writes'"), {"ws": w.ws.id})).scalar()
        assert n == 1
    finally:
        await cleanup(w.ws.id, w.user.id)


@pytest.mark.parametrize("category", ["validation", "permanent", "unsupported"])
async def test_permanent_categories_fail_without_retry(category):
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter([PublishError(category, "rejected", code="x1")])
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "failed"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.failed and sp.next_attempt_at is None and "rejected" in (sp.last_error or "")
        att = await attempts(w.sp.id)
        assert att[0].status == "failed" and att[0].error_category == category and att[0].error_code == "x1"
        assert await events(w.ws.id, "PUBLISH_FAILED") == 1 and await pending_jobs(w.sp.id) == 0
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_rate_limited_sets_next_attempt_from_retry_after():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter([PublishError("rate_limited", "429", code="429", retry_after_s=120)])
        before = datetime.now(UTC)
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "retry_scheduled"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.queued
        assert timedelta(seconds=110) <= sp.next_attempt_at - before <= timedelta(seconds=130)
        assert "rate limited until" in sp.last_error
        # the scheduler re-dispatches only once next_attempt_at passes
        async with SessionLocal() as db:
            assert await dispatch_retries(db) == 0
            await db.execute(text("UPDATE scheduled_posts SET next_attempt_at = now() - interval '1 second' WHERE id=:id"), {"id": w.sp.id})
            await db.commit()
        async with SessionLocal() as db:
            assert await dispatch_retries(db) == 1
            await db.commit()
        assert await pending_jobs(w.sp.id) == 1
        sp = await reload_sp(w.sp.id)
        assert sp.next_attempt_at is None
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_transient_backoff_then_dead_letter():
    async with SessionLocal() as db:
        w = await make_world(db, max_attempts=2)
    try:
        fake = FakeAdapter([PublishError("transient", "503", code="503"), PublishError("transient", "503", code="503")])
        svc = service(fake)
        before = datetime.now(UTC)
        assert await svc.run_attempt(w.sp.id, 1, w.ws.id) == "retry_scheduled"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.queued and sp.attempt_count == 1
        assert timedelta(seconds=55) <= sp.next_attempt_at - before <= timedelta(seconds=80)   # 1 min + ≤20 % jitter
        async with SessionLocal() as db:
            await db.execute(text("UPDATE scheduled_posts SET next_attempt_at=NULL WHERE id=:id"), {"id": w.sp.id})
            await db.commit()
        assert await svc.run_attempt(w.sp.id, 2, w.ws.id) == "dead_lettered"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.failed and sp.attempt_count == 2
        assert await events(w.ws.id, "PUBLISH_DEAD_LETTERED") == 1
        assert [a.idempotency_key for a in await attempts(w.sp.id)] == [f"{sp.idempotency_root}:1", f"{sp.idempotency_root}:2"]
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_auth_refresh_once_then_requeue_immediately():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter([PublishError("auth", "401", code="401")])
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "requeued"
        assert fake.refresh_calls == 1
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.queued and sp.next_attempt_at is None and await pending_jobs(w.sp.id) == 1
        async with SessionLocal() as db:
            tokens = await TokenVault().get_tokens(db, await db.get(SocialAccount, w.account.id))
        assert tokens.access_token.startswith("refreshed-")
        # second auth failure in the same chain: refresh is not retried, account marked expired
        fake.script = [PublishError("auth", "401 again", code="401")]
        assert await service(fake).run_attempt(w.sp.id, 2, w.ws.id) == "failed"
        assert fake.refresh_calls == 1
        async with SessionLocal() as db:
            acc = await db.get(SocialAccount, w.account.id)
        assert acc.status == AccountStatus.expired
        assert await events(w.ws.id, "SOCIAL_ACCOUNT_EXPIRED") == 1
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_auth_refresh_failure_marks_account_expired():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter([PublishError("auth", "401", code="401")], refresh_ok=False)
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "failed"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.failed
        async with SessionLocal() as db:
            acc = await db.get(SocialAccount, w.account.id)
        assert acc.status == AccountStatus.expired and await events(w.ws.id, "SOCIAL_ACCOUNT_EXPIRED") == 1
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_ambiguous_reconcile_finds_post_no_duplicate():
    async with SessionLocal() as db:
        w = await make_world(db, text_="Reconcile me please")
    try:
        fake = FakeAdapter(["ambiguous_posted"])
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "published"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.published
        att = await attempts(w.sp.id)
        assert att[0].status == "reconciled" and att[0].error_category == "ambiguous"
        pp = await published(w.sp.id)
        assert len(pp) == 1 and pp[0].external_id == fake.remote[0].external_id and pp[0].raw.get("reconciled_via") == "find_recent_posts"
        assert len(fake.remote) == 1 and fake.publish_calls == 1   # never re-posted
        assert normalize_text(fake.remote[0].text) == normalize_text("Reconcile me please")
        assert await pending_jobs(w.sp.id) == 0
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_ambiguous_not_found_retries_with_backoff():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter([PublishError("ambiguous", "timeout after send", code="ReadTimeout")])
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "retry_scheduled"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.queued and sp.next_attempt_at is not None
        att = await attempts(w.sp.id)
        assert att[0].status == "ambiguous"
        assert await published(w.sp.id) == []
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_ambiguous_cannot_list_fails_for_manual_verification():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter([PublishError("ambiguous", "timeout after send", code="ReadTimeout")], can_list=False)
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "failed"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.failed and "verify manually" in sp.last_error
        assert await pending_jobs(w.sp.id) == 0
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_partial_thread_resumes_at_first_missing_segment():
    async with SessionLocal() as db:
        w = await make_world(db, text_="one", segments=["one", "two", "three"])
    try:
        fake = FakeAdapter(["partial", "ok"])
        svc = service(fake)
        assert await svc.run_attempt(w.sp.id, 1, w.ws.id) == "retry_scheduled"
        sp = await reload_sp(w.sp.id)
        assert sp.status == ScheduleStatus.queued and "partially published: 1 segment" in sp.last_error
        att = await attempts(w.sp.id)
        assert att[0].state["segment_external_ids"] == [fake.remote[0].external_id]
        async with SessionLocal() as db:
            await db.execute(text("UPDATE scheduled_posts SET next_attempt_at=NULL WHERE id=:id"), {"id": w.sp.id})
            await db.commit()
        assert await svc.run_attempt(w.sp.id, 2, w.ws.id) == "published"
        assert len(fake.remote) == 3 and [p.text for p in fake.remote] == ["one", "two", "three"]
        pp = await published(w.sp.id)
        assert len(pp) == 1 and [s["external_id"] for s in pp[0].segments] == [p.external_id for p in fake.remote]
        att = await attempts(w.sp.id)
        assert att[1].state["segment_external_ids"] == [p.external_id for p in fake.remote]
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_duplicate_live_schedule_409_and_fingerprint_duplicate():
    async with SessionLocal() as db:
        w = await make_world(db, status=None)
    try:
        fake = FakeAdapter()
        sched = SchedulingService(publishing=service(fake))
        at = datetime.now(UTC) + timedelta(hours=2)
        async with SessionLocal() as db:
            sp = await sched.schedule(db, w.member, w.variant.id, w.account.id, at, "UTC")
            await db.commit()
        assert sp.status == ScheduleStatus.scheduled and await events(w.ws.id, "POST_SCHEDULED") == 1
        async with SessionLocal() as db:
            with pytest.raises(ProblemError) as ei:
                await sched.schedule(db, w.member, w.variant.id, w.account.id, at + timedelta(hours=1), "UTC")
            assert ei.value.status_code == 409 and ei.value.type == "duplicate_live_schedule"
        # publish it, then the same content again within 24 h → 409 possible_duplicate unless force
        async with SessionLocal() as db:
            await db.execute(text("UPDATE scheduled_posts SET status='queued', scheduled_at=now() WHERE id=:id"), {"id": sp.id})
            await db.commit()
        assert await service(fake).run_attempt(sp.id, 1, w.ws.id) == "published"
        async with SessionLocal() as db:
            with pytest.raises(ProblemError) as ei:
                await sched.schedule(db, w.member, w.variant.id, w.account.id, at, "UTC")
            assert ei.value.status_code == 409 and ei.value.type == "possible_duplicate"
        async with SessionLocal() as db:
            sp2 = await sched.schedule(db, w.member, w.variant.id, w.account.id, at, "UTC", force=True)
            await db.commit()
        seeds = [a for a in await attempts(sp2.id) if a.attempt_no == 0]
        assert seeds and seeds[0].state == {"allow_duplicate": True}
        async with SessionLocal() as db:
            await db.execute(text("UPDATE scheduled_posts SET status='queued', scheduled_at=now() WHERE id=:id"), {"id": sp2.id})
            await db.commit()
        assert await service(fake).run_attempt(sp2.id, 1, w.ws.id) == "published"   # override honoured at worker time
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_worker_time_duplicate_block_without_override():
    async with SessionLocal() as db:
        w = await make_world(db, text_="same text twice")
    try:
        fake = FakeAdapter()
        assert await service(fake).run_attempt(w.sp.id, 1, w.ws.id) == "published"
        async with SessionLocal() as db:
            sp2 = ScheduledPost(id=new_id(), workspace_id=w.ws.id, brand_id=w.brand.id, content_variant_id=w.variant.id, social_account_id=w.account.id,
                                scheduled_at=datetime.now(UTC), timezone="UTC", status=ScheduleStatus.queued, created_by=w.user.id)
            db.add(sp2)
            await db.commit()
        assert await service(fake).run_attempt(sp2.id, 1, w.ws.id) == "failed"
        sp = await reload_sp(sp2.id)
        assert "possible duplicate" in sp.last_error and fake.publish_calls == 1
    finally:
        await cleanup(w.ws.id, w.user.id)


async def _flip_to_scheduled(ws_id) -> None:
    async with SessionLocal() as db:
        await db.execute(text("UPDATE scheduled_posts SET status='scheduled' WHERE workspace_id=:ws AND status='paused'"), {"ws": ws_id})
        await db.commit()


async def test_dispatch_due_posts_concurrent_never_double_enqueues():
    """Rows start ``paused`` and are flipped to ``scheduled`` right before dispatching: a live scheduler (make dev) must
    not get a chance to dispatch them onto the real queue first."""
    async with SessionLocal() as db:
        w = await make_world(db, status=ScheduleStatus.paused)
        extra_ids = []
        for i in range(3):
            v = ContentVariant(id=new_id(), workspace_id=w.ws.id, content_item_id=w.item.id, platform=Platform.x, format=ContentFormat.text, text=f"t{i}",
                               status=ContentStatus.approved)
            db.add(v)
            await db.flush()
            sp = ScheduledPost(id=new_id(), workspace_id=w.ws.id, brand_id=w.brand.id, content_variant_id=v.id, social_account_id=w.account.id,
                               scheduled_at=datetime.now(UTC) - timedelta(minutes=2), timezone="UTC", status=ScheduleStatus.paused, created_by=w.user.id)
            db.add(sp)
            extra_ids.append(sp.id)
        await db.commit()
    all_ids = [w.sp.id, *extra_ids]
    try:
        await _flip_to_scheduled(w.ws.id)

        async def run_once() -> int:
            async with SessionLocal() as db:
                n = await dispatch_due_posts(db)
                await db.commit()
                return n

        results = await asyncio.gather(run_once(), run_once())
        assert sum(results) == len(all_ids)
        for sp_id in all_ids:
            assert await pending_jobs(sp_id) == 1
            assert (await reload_sp(sp_id)).status == ScheduleStatus.queued
        # a third pass finds nothing due and nothing to re-enqueue
        assert await run_once() == 0
        async with SessionLocal() as db:
            n = (await db.execute(text("SELECT count(*) FROM procrastinate_jobs WHERE task_name='jobs.publishing.publish_post' AND status='todo' "
                                       "AND args->>'workspace_id' = :ws"), {"ws": str(w.ws.id)})).scalar()
        assert n == len(all_ids)
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_dispatch_holds_unapproved_and_late_posts():
    async with SessionLocal() as db:
        w = await make_world(db, status=ScheduleStatus.paused, scheduled_at=datetime.now(UTC) - timedelta(hours=7))
        late_id = w.sp.id
        v2 = ContentVariant(id=new_id(), workspace_id=w.ws.id, content_item_id=w.item.id, platform=Platform.x, format=ContentFormat.text, text="draft",
                            status=ContentStatus.draft)
        db.add(v2)
        await db.flush()
        sp2 = ScheduledPost(id=new_id(), workspace_id=w.ws.id, brand_id=w.brand.id, content_variant_id=v2.id, social_account_id=w.account.id,
                            scheduled_at=datetime.now(UTC) - timedelta(minutes=1), timezone="UTC", status=ScheduleStatus.paused, created_by=w.user.id)
        db.add(sp2)
        await db.commit()
    try:
        await _flip_to_scheduled(w.ws.id)
        async with SessionLocal() as db:
            assert await dispatch_due_posts(db) == 0
            await db.commit()
        late, unapproved = await reload_sp(late_id), await reload_sp(sp2.id)
        assert late.status == ScheduleStatus.paused and "missed_window" in late.last_error
        assert unapproved.status == ScheduleStatus.paused and "variant_not_approved" in unapproved.last_error
        assert await events(w.ws.id, "POST_PAUSED") == 2 and await pending_jobs(late_id) == 0
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_delete_published_uses_adapter_and_marks_deleted():
    async with SessionLocal() as db:
        w = await make_world(db)
    try:
        fake = FakeAdapter()
        svc = service(fake)
        assert await svc.run_attempt(w.sp.id, 1, w.ws.id) == "published"
        pp = (await published(w.sp.id))[0]
        async with SessionLocal() as db:
            out = await svc.delete_published(db, w.member, pp.id)
            await db.commit()
        assert out.deleted_at is not None and fake.deleted == [pp.external_id]
    finally:
        await cleanup(w.ws.id, w.user.id)


# ------------------------------------------------------------------------------------------ scheduling extras
class MetricsFake(FakeAdapter):
    async def get_post_metrics(self, account, tokens, external_id):
        from app.analytics.normalize import normalize_post_metrics
        return normalize_post_metrics("x", {"public_metrics": {"impression_count": 1000, "like_count": 10, "reply_count": 2, "retweet_count": 1,
                                                               "quote_count": 0, "bookmark_count": 1}, "cost_usd": 0.001})

    async def get_account_metrics(self, account, tokens):
        from app.analytics.normalize import normalize_account_metrics
        return normalize_account_metrics("x", {"public_metrics": {"followers_count": 500, "following_count": 10, "tweet_count": 42}})


async def test_best_times_calendar_and_analytics_sync():
    from app.analytics.queries import breakdown, kpis, post_rows
    from app.services.analytics_sync_service import AnalyticsSyncService, dispatch_analytics_cadence, is_due
    async with SessionLocal() as db:
        w = await make_world(db, text_="metrics post")
    try:
        fake = MetricsFake()
        svc = service(fake)
        import app.services.analytics_sync_service as ass
        orig_get = ass.get_adapter
        ass.get_adapter = lambda platform: fake
        assert await svc.run_attempt(w.sp.id, 1, w.ws.id) == "published"
        sched = SchedulingService(publishing=svc)
        async with SessionLocal() as db:
            cal = await sched.calendar(db, w.ws.id, datetime.now(UTC) - timedelta(days=1), datetime.now(UTC) + timedelta(days=1))
            assert len(cal["cards"]) == 1 and cal["cards"][0]["status"] == "published" and cal["cards"][0]["published_url"]
            best = await sched.best_times(db, w.brand.id, "x", w.account.id, datetime.now(UTC), datetime.now(UTC) + timedelta(days=2), 3)
            assert len(best["slots"]) == 3 and all(s["basis"] == "generic" for s in best["slots"]) and best["evidence"] == "generic prior"
        # analytics: first pull is due 1 h after publish → force it now
        pp = (await published(w.sp.id))[0]
        assert is_due(pp.published_at, None, "x", now=pp.published_at + timedelta(hours=2))
        assert not is_due(pp.published_at, None, "x", now=pp.published_at + timedelta(minutes=10))
        async with SessionLocal() as db:
            res = await AnalyticsSyncService.sync_account(db, w.account.id, force=True)
            await db.commit()
        assert res["status"] == "ok" and res["posts_pulled"] == 1 and res["account_metrics"] == "updated"
        async with SessionLocal() as db:
            rows = await post_rows(db, w.ws.id, brand_id=w.brand.id)
            assert rows[0]["metrics"]["impressions"] == 1000 and rows[0]["engagement_rate_basis"] == "impressions"
            assert rows[0]["availability"]["link_clicks"] == "not_available" and rows[0]["metrics"]["link_clicks"] is None
            k = kpis(rows)
            assert k["impressions"]["value"] == 1000 and k["impressions"]["coverage"] == 1 and k["reach"]["value"] is None
            bd = breakdown(rows, "platform", "engagement_rate")
            assert bd["groups"][0]["key"] == "x" and bd["coverage"] == {"posts": 1, "with_metric": 1}
            snaps = (await db.execute(text("SELECT count(*) FROM analytics_snapshots WHERE brand_id=:b"), {"b": w.brand.id})).scalar()
            assert snaps >= 3
            acc_rows = (await db.execute(text("SELECT followers FROM account_metrics WHERE social_account_id=:a"), {"a": w.account.id})).scalars().all()
            assert acc_rows == [500]
            # second sync the same day: nothing due (idempotent), no new rows
            res2 = await AnalyticsSyncService.sync_account(db, w.account.id)
            assert res2["posts_pulled"] == 0
            assert await dispatch_analytics_cadence(db) == 0
            await db.commit()
    finally:
        ass.get_adapter = orig_get
        await cleanup(w.ws.id, w.user.id)


async def test_materialize_recurring_creates_posts_14_days_ahead():
    from app.models.scheduling import RecurringSchedule
    from app.services.scheduling_service import materialize_recurring
    async with SessionLocal() as db:
        w = await make_world(db, status=None)
        r = RecurringSchedule(id=new_id(), workspace_id=w.ws.id, brand_id=w.brand.id, name="weekly", rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
                              timezone="Europe/Berlin", kind="repost_variant",
                              payload={"content_variant_id": str(w.variant.id), "social_account_id": str(w.account.id)}, created_by=w.user.id)
        db.add(r)
        await db.commit()
    try:
        async with SessionLocal() as db:
            n = await materialize_recurring(db)
            await db.commit()
        assert n == 1   # a weekly rule yields 2 Mondays in 14 days, but only one live row per variant/account may exist (unique index)
        async with SessionLocal() as db:
            rows = (await db.execute(select(ScheduledPost).where(ScheduledPost.recurring_schedule_id == r.id))).scalars().unique().all()
            assert rows and all(x.scheduled_at.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin")).hour == 9 for x in rows)
            again = await materialize_recurring(db)
            await db.commit()
        assert again == 0   # idempotent
    finally:
        await cleanup(w.ws.id, w.user.id)


async def test_token_monitor_marks_expiring_and_refreshes():
    from app.services.social_account_service import SocialAccountService
    async with SessionLocal() as db:
        w = await make_world(db, status=None)
        await db.execute(text("UPDATE oauth_tokens SET expires_at = now() + interval '2 days' WHERE social_account_id=:a AND token_kind='access'"), {"a": w.account.id})
        await db.commit()
    try:
        import app.services.social_account_service as sas
        fake = FakeAdapter()
        orig = sas.get_adapter
        sas.get_adapter = lambda platform: fake
        try:
            async with SessionLocal() as db:
                n = await SocialAccountService.token_monitor(db)
                await db.commit()
        finally:
            sas.get_adapter = orig
        assert n == 1 and fake.refresh_calls == 1
        async with SessionLocal() as db:
            tokens = await TokenVault().get_tokens(db, await db.get(SocialAccount, w.account.id))
        assert tokens.access_token.startswith("refreshed-") and tokens.expires_at > datetime.now(UTC) + timedelta(days=30)
    finally:
        await cleanup(w.ws.id, w.user.id)
