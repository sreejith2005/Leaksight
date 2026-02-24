"""
LeakSight V1 — Async Database Engine & Session Management

Source: docs/DATABASE_SCHEMA.md, docs/ARCHITECTURE.md, docs/DECISIONS.md (ADR-009)

Uses SQLAlchemy 2.0 async with asyncpg driver.
RLS tenant context is set per-session via SET LOCAL app.current_tenant_id.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models.

    All models inherit from this base to participate in metadata
    collection and Alembic migration generation.
    """


def _build_engine() -> "create_async_engine":
    """Create the async SQLAlchemy engine with connection pool settings.

    Returns:
        Configured async engine connected to PostgreSQL via asyncpg.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=(settings.app_env == "development"),
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


engine = _build_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session.

    The session is automatically closed when the request completes.
    RLS tenant context (SET LOCAL app.current_tenant_id) is set by
    TenantContextMiddleware before this session is used by route handlers.

    Yields:
        An async SQLAlchemy session bound to the application engine.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
