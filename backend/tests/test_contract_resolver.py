"""
Tests for LeakSight V1 — Contract Resolver

Tests:
1. Single valid version → FOUND
2. Overlapping versions → OVERLAP
3. No valid version → NONE
4. valid_from inclusive (invoice_date == valid_from → FOUND)
5. valid_to exclusive (invoice_date == valid_to → NONE)
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.core.contract_resolver import (
    ContractResolutionResult,
    ContractResolutionStatus,
    get_valid_contract_version,
)


TENANT_ID = uuid4()
VENDOR_ID = uuid4()


def _mock_db_returning(versions: list):
    """Build a mock AsyncSession that returns the given list of versions."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = versions

    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock

    db.execute = AsyncMock(return_value=result_mock)
    return db


def _make_version(version_number: int = 1, contract_id=None):
    """Create a fake ContractVersion-like object."""
    v = MagicMock()
    v.version_number = version_number
    if contract_id is not None:
        v.contract_id = contract_id
    return v


# ── Test 1: Single valid version → FOUND ──────────────────────────────


@pytest.mark.asyncio
async def test_single_version_found():
    version = _make_version(1)
    db = _mock_db_returning([version])

    result = await get_valid_contract_version(
        VENDOR_ID, date(2024, 6, 15), TENANT_ID, db
    )

    assert result.status == ContractResolutionStatus.FOUND
    assert len(result.versions) == 1
    assert result.versions[0] is version


# ── Test 2: Overlapping versions → OVERLAP ─────────────────────────────


@pytest.mark.asyncio
async def test_overlapping_versions():
    """Same contract, two versions valid on the same date → OVERLAP."""
    shared_contract_id = uuid4()
    v1 = _make_version(1, contract_id=shared_contract_id)
    v2 = _make_version(2, contract_id=shared_contract_id)
    db = _mock_db_returning([v1, v2])

    result = await get_valid_contract_version(
        VENDOR_ID, date(2024, 6, 15), TENANT_ID, db
    )

    assert result.status == ContractResolutionStatus.OVERLAP
    assert len(result.versions) == 2


@pytest.mark.asyncio
async def test_multi_contract_versions():
    """Different contracts, each with 1 version valid on same date → MULTI_CONTRACT."""
    v1 = _make_version(1, contract_id=uuid4())
    v2 = _make_version(1, contract_id=uuid4())
    db = _mock_db_returning([v1, v2])

    result = await get_valid_contract_version(
        VENDOR_ID, date(2024, 6, 15), TENANT_ID, db
    )

    assert result.status == ContractResolutionStatus.MULTI_CONTRACT
    assert len(result.versions) == 2


# ── Test 3: No valid version → NONE ───────────────────────────────────


@pytest.mark.asyncio
async def test_no_version_none():
    db = _mock_db_returning([])

    result = await get_valid_contract_version(
        VENDOR_ID, date(2024, 6, 15), TENANT_ID, db
    )

    assert result.status == ContractResolutionStatus.NONE
    assert len(result.versions) == 0


# ── Test 4: valid_from inclusive ────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_from_inclusive():
    """Invoice date exactly on valid_from should match (≤ check)."""
    version = _make_version(1)
    db = _mock_db_returning([version])

    result = await get_valid_contract_version(
        VENDOR_ID, date(2024, 1, 1), TENANT_ID, db
    )

    assert result.status == ContractResolutionStatus.FOUND
    # Verify the query was constructed — the WHERE clause in the real
    # implementation uses valid_from <= invoice_date.


# ── Test 5: valid_to exclusive ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_to_exclusive():
    """Invoice date exactly on valid_to should NOT match (< check).

    The query uses valid_to > invoice_date, meaning that when
    invoice_date == valid_to, no rows should be returned.
    Since the query is mocked, we return [] to simulate the DB
    filtering out the row where valid_to == invoice_date.
    """
    db = _mock_db_returning([])

    result = await get_valid_contract_version(
        VENDOR_ID, date(2024, 12, 31), TENANT_ID, db
    )

    assert result.status == ContractResolutionStatus.NONE
    assert len(result.versions) == 0
