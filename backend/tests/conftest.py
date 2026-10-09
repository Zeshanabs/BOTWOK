"""Shared test fixtures. Unit tests need no DB; integration tests use the local Postgres (skip if unreachable)."""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

os.environ.setdefault("APP_ENV", "test")

from app.config import settings  # noqa: E402


def _db_reachable() -> bool:
    import socket
    from urllib.parse import urlparse
    u = urlparse(settings.database_url_sync)
    try:
        with socket.create_connection((u.hostname or "localhost", u.port or 5432), timeout=1):
            return True
    except OSError:
        return False


DB_AVAILABLE = _db_reachable()
integration = pytest.mark.skipif(not DB_AVAILABLE, reason="Postgres not reachable")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "integration" in item.keywords and not DB_AVAILABLE:
            item.add_marker(pytest.mark.skip(reason="Postgres not reachable"))


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires the local Postgres/Redis")


@pytest_asyncio.fixture
async def db():
    """Transactional session: everything is rolled back at the end of the test."""
    from app.core.db import SessionLocal
    async with SessionLocal() as session:
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seeded_user(client):
    """Signs up a fresh user (+ workspace) through the API and returns auth headers + ids."""
    email = f"t-{uuid.uuid4().hex[:8]}@test.local"
    r = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Passw0rd!xyz", "full_name": "Test User", "workspace_name": "Test WS"})
    assert r.status_code in (200, 201), r.text
    data = r.json()
    ws = (data.get("memberships") or [{}])[0].get("workspace", {})
    headers = {"Authorization": f"Bearer {data['access_token']}", "X-Workspace-Id": ws.get("id", "")}
    return {"email": email, "password": "Passw0rd!xyz", "user": data.get("user"), "workspace": ws, "headers": headers}


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
