"""
LeakSight V1 — Tenant Context Service

Source: docs/ARCHITECTURE.md (Section 6.2), docs/DATABASE_SCHEMA.md (RLS section),
       backend/app/core/middleware.py (session variable name)

Sets the PostgreSQL session variable `app.current_tenant_id` that RLS policies
read. Must be called at the start of every request and every Celery task.
If not called, RLS will fail to filter correctly and cross-tenant data bleed
becomes possible.

Uses SET LOCAL so the variable is scoped to the current transaction only.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(db: AsyncSession, tenant_id: UUID) -> None:
    """Set the PostgreSQL session variable for RLS tenant isolation.

    Executes SET LOCAL app.current_tenant_id = '{tenant_id}' on the
    database session. Uses SET LOCAL (not SET) so the variable is
    scoped to the current transaction only.

    Args:
        db: The async SQLAlchemy session.
        tenant_id: The UUID of the tenant to scope queries to.

    Raises:
        ValueError: If tenant_id is None.
    """
    if tenant_id is None:
        raise ValueError("tenant_id must not be None")
    await db.execute(
        text("SET LOCAL app.current_tenant_id = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )


async def get_current_tenant_id(db: AsyncSession) -> UUID:
    """Read the current tenant_id from the PostgreSQL session variable.

    Used for verification that tenant context was set correctly.

    Args:
        db: The async SQLAlchemy session.

    Returns:
        The tenant_id UUID currently set in the session.

    Raises:
        ValueError: If the session variable is not set or is empty.
    """
    result = await db.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
    row = result.scalar_one_or_none()
    if not row or row == "":
        raise ValueError(
            "Tenant context not set. Call set_tenant_context() before any DB operation."
        )
    return UUID(row)
