"""
Tests for the Tenant Context Service.

Source: docs/ARCHITECTURE.md (tenant context section), docs/DATABASE_SCHEMA.md (RLS section)

Covers:
  - Setting tenant context and confirming the variable is readable
  - Confirming that get_current_tenant_id raises when context is not set
  - Confirming set_tenant_context rejects None tenant_id
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.tenant_context import get_current_tenant_id, set_tenant_context


@pytest.fixture
def tenant_id() -> uuid.UUID:
    """Provide a fixed tenant UUID for tests."""
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def mock_db() -> AsyncMock:
    """Provide a mock async database session."""
    return AsyncMock()


# ---------------------------------------------------------------------------
# set_tenant_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_tenant_context_executes_set_local(
    mock_db: AsyncMock, tenant_id: uuid.UUID
) -> None:
    """Setting tenant context should execute SET LOCAL with the tenant_id."""
    await set_tenant_context(mock_db, tenant_id)

    mock_db.execute.assert_called_once()
    call_args = mock_db.execute.call_args
    # First positional arg is the text() object (tenant_id is interpolated directly)
    sql_text = str(call_args[0][0])
    assert "SET LOCAL app.current_tenant_id" in sql_text
    assert str(tenant_id) in sql_text


@pytest.mark.asyncio
async def test_set_tenant_context_rejects_none() -> None:
    """Setting tenant context with None should raise ValueError."""
    mock_db = AsyncMock()
    with pytest.raises(ValueError, match="tenant_id must not be None"):
        await set_tenant_context(mock_db, None)  # type: ignore[arg-type]
    mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# get_current_tenant_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_tenant_id_returns_uuid(
    mock_db: AsyncMock, tenant_id: uuid.UUID
) -> None:
    """get_current_tenant_id should return the UUID from the session variable."""
    # Mock the result of SELECT current_setting(...)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = str(tenant_id)
    mock_db.execute.return_value = mock_result

    result = await get_current_tenant_id(mock_db)

    assert result == tenant_id
    assert isinstance(result, uuid.UUID)


@pytest.mark.asyncio
async def test_get_current_tenant_id_raises_when_not_set(
    mock_db: AsyncMock,
) -> None:
    """get_current_tenant_id should raise ValueError when variable is not set."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ""
    mock_db.execute.return_value = mock_result

    with pytest.raises(ValueError, match="Tenant context not set"):
        await get_current_tenant_id(mock_db)


@pytest.mark.asyncio
async def test_get_current_tenant_id_raises_when_none(
    mock_db: AsyncMock,
) -> None:
    """get_current_tenant_id should raise ValueError when variable returns None."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(ValueError, match="Tenant context not set"):
        await get_current_tenant_id(mock_db)


@pytest.mark.asyncio
async def test_set_and_get_tenant_context_roundtrip(
    tenant_id: uuid.UUID,
) -> None:
    """Setting and getting tenant context should roundtrip the same UUID."""
    # Track what SET LOCAL was called with, and return it on SELECT
    stored_value: dict[str, str] = {}

    async def mock_execute(stmt, params=None):
        sql = str(stmt)
        if "SET LOCAL" in sql:
            # tenant_id is interpolated directly in the SQL string
            stored_value["tenant_id"] = str(tenant_id)
            return None
        elif "current_setting" in sql:
            result = MagicMock()
            result.scalar_one_or_none.return_value = stored_value.get("tenant_id", "")
            return result
        return MagicMock()

    mock_db = AsyncMock()
    mock_db.execute = mock_execute

    await set_tenant_context(mock_db, tenant_id)
    result = await get_current_tenant_id(mock_db)

    assert result == tenant_id
