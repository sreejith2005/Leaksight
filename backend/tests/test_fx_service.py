"""
Tests for LeakSight V1 — FX Rate Service

Tests:
1. Same currency → rate 1.0
2. Exact date rate → FXResult with matching date
3. Earlier date rate → closest rate_date ≤ invoice_date
4. No rate → PENDING_FX_RATE sentinel
5. Tenant rate takes precedence over system rate
6. Future-only rates → PENDING_FX_RATE (rate_date > invoice_date)
7. No HTTP imports in fx_service module
"""

import importlib
import inspect
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.core.fx_service import FXResult, PENDING_FX_RATE, get_rate


TENANT_ID = uuid4()


def _mock_db_with_results(tenant_row, system_row):
    """Build a mock AsyncSession that returns tenant_row then system_row.

    Each call to db.execute() returns a Result whose scalar_one_or_none()
    yields the corresponding row.
    """
    db = AsyncMock()

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant_row

    system_result = MagicMock()
    system_result.scalar_one_or_none.return_value = system_row

    # First execute → tenant query, second → system query
    db.execute = AsyncMock(side_effect=[tenant_result, system_result])
    return db


# ── Test 1: Same currency → rate 1.0 ──────────────────────────────────


@pytest.mark.asyncio
async def test_same_currency_returns_one():
    db = AsyncMock()
    result = await get_rate("USD", "USD", date(2024, 1, 15), TENANT_ID, db)

    assert isinstance(result, FXResult)
    assert result.rate == Decimal("1")
    assert result.source == "SYSTEM"
    assert result.from_currency == "USD"
    assert result.to_currency == "USD"
    # Should NOT hit the database at all
    db.execute.assert_not_called()


# ── Test 2: Exact date rate ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_date_rate():
    """System rate with exact invoice_date match."""
    rate_row = MagicMock()
    rate_row.rate = Decimal("83.12")
    rate_row.rate_date = date(2024, 1, 15)
    rate_row.source = "ECB"

    db = _mock_db_with_results(tenant_row=None, system_row=rate_row)
    result = await get_rate("USD", "INR", date(2024, 1, 15), TENANT_ID, db)

    assert isinstance(result, FXResult)
    assert result.rate == Decimal("83.12")
    assert result.rate_date == date(2024, 1, 15)
    assert result.source == "ECB"


# ── Test 3: Earlier date rate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_earlier_date_rate():
    """System rate from an earlier date is used when exact date missing."""
    rate_row = MagicMock()
    rate_row.rate = Decimal("82.50")
    rate_row.rate_date = date(2024, 1, 10)  # 5 days before invoice
    rate_row.source = "RBI"

    db = _mock_db_with_results(tenant_row=None, system_row=rate_row)
    result = await get_rate("USD", "INR", date(2024, 1, 15), TENANT_ID, db)

    assert isinstance(result, FXResult)
    assert result.rate == Decimal("82.50")
    assert result.rate_date == date(2024, 1, 10)
    assert result.source == "RBI"


# ── Test 4: No rate → PENDING_FX_RATE ─────────────────────────────────


@pytest.mark.asyncio
async def test_no_rate_returns_pending():
    """When no rate exists at all, return PENDING_FX_RATE sentinel."""
    db = _mock_db_with_results(tenant_row=None, system_row=None)
    result = await get_rate("USD", "INR", date(2024, 1, 15), TENANT_ID, db)

    assert result == PENDING_FX_RATE
    assert result == "PENDING_FX_RATE"


# ── Test 5: Tenant rate takes precedence over system rate ──────────────


@pytest.mark.asyncio
async def test_tenant_rate_precedence():
    """Tenant-specific rate should be returned even if system rate exists."""
    tenant_row = MagicMock()
    tenant_row.rate = Decimal("84.00")
    tenant_row.rate_date = date(2024, 1, 14)
    tenant_row.source = "MANUAL_UPLOAD"

    system_row = MagicMock()
    system_row.rate = Decimal("83.12")
    system_row.rate_date = date(2024, 1, 15)
    system_row.source = "ECB"

    db = _mock_db_with_results(tenant_row=tenant_row, system_row=system_row)
    result = await get_rate("USD", "INR", date(2024, 1, 15), TENANT_ID, db)

    assert isinstance(result, FXResult)
    assert result.rate == Decimal("84.00")
    assert result.source == "MANUAL_UPLOAD"
    # Should only execute ONE query (tenant), never reach system
    assert db.execute.call_count == 1


# ── Test 6: Future-only rate → PENDING_FX_RATE ────────────────────────


@pytest.mark.asyncio
async def test_future_only_rate_returns_pending():
    """Rates that exist only AFTER the invoice_date must not be used."""
    # Both tenant and system queries return None because all rates are
    # in the future (the WHERE clause rate_date <= invoice_date filters
    # them out).
    db = _mock_db_with_results(tenant_row=None, system_row=None)
    result = await get_rate("EUR", "INR", date(2024, 1, 15), TENANT_ID, db)

    assert result == PENDING_FX_RATE


# ── Test 7: No HTTP imports in fx_service ──────────────────────────────


def test_no_http_imports():
    """Structural enforcement: fx_service must never import HTTP clients."""
    import backend.app.core.fx_service as mod

    source = inspect.getsource(mod)
    forbidden = ["import requests", "import httpx", "import aiohttp", "import urllib"]
    for token in forbidden:
        assert token not in source, f"FORBIDDEN: {token} found in fx_service.py"
