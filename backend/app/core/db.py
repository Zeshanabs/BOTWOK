"""Async SQLAlchemy engine/session + Row-Level-Security context variable."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def set_workspace(session: AsyncSession, workspace_id: UUID | None) -> None:
    """Set app.workspace_id for RLS policies (no-op for NULL = system scope)."""
    await session.execute(text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": str(workspace_id) if workspace_id else ""})


@asynccontextmanager
async def session_scope(workspace_id: UUID | None = None) -> AsyncIterator[AsyncSession]:
    """Unit of work: one transaction; commits on success, rolls back on error."""
    async with SessionLocal() as session:
        try:
            if workspace_id:
                await set_workspace(session, workspace_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: request-scoped session (commit handled by services/route)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
