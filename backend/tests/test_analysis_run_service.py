"""
Tests for LeakSight V1 — Analysis Run Service

Tests:
1. create_run: creates in QUEUED status
2. transition_to_processing: QUEUED → PROCESSING, sets started_at
3. complete_run: PROCESSING → COMPLETE (no partial issues)
4. complete_run: PROCESSING → PARTIAL_SUCCESS (PENDING_FX_RATE exists)
5. complete_run: PROCESSING → PARTIAL_SUCCESS (has_partial_issues flag)
6. fail_run: PROCESSING → FAILED with error_summary
7. invalid transition: QUEUED → COMPLETE raises InvalidTransitionError
8. invalid transition: COMPLETE → PROCESSING raises (terminal state)
9. increment_processed: increments counter during PROCESSING
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from uuid import uuid4

import pytest

from backend.app.services.analysis_run_service import (
    InvalidTransitionError,
    complete_run,
    create_run,
    fail_run,
    increment_processed,
    transition_to_processing,
)


TENANT_ID = uuid4()
RUN_ID = uuid4()


# ── Test 1: create_run ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_run_queued():
    db = AsyncMock()
    run = await create_run(TENANT_ID, total_documents=10, db=db)

    assert run.tenant_id == TENANT_ID
    assert run.status == "QUEUED"
    assert run.total_documents == 10
    assert run.processed_documents == 0
    assert run.total_leakage_found == Decimal("0")
    db.add.assert_called_once()


# ── Test 2: transition_to_processing ───────────────────────────────────


@pytest.mark.asyncio
async def test_transition_to_processing():
    run = MagicMock()
    run.status = "QUEUED"

    result = await transition_to_processing(run)

    assert result.status == "PROCESSING"
    assert result.started_at is not None


# ── Test 3: complete_run → COMPLETE ────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_run_clean():
    """No PENDING_FX_RATE records → COMPLETE."""
    run = MagicMock()
    run.id = RUN_ID
    run.status = "PROCESSING"

    db = AsyncMock()

    # Count PENDING_FX_RATE → 0
    count_result = MagicMock()
    count_result.scalar.return_value = 0

    # Totals query
    totals_row = MagicMock()
    totals_row.record_count = 5
    totals_row.total_amount = Decimal("25000")
    totals_result = MagicMock()
    totals_result.one.return_value = totals_row

    db.execute = AsyncMock(side_effect=[count_result, totals_result])

    result = await complete_run(run, TENANT_ID, db)

    assert result.status == "COMPLETE"
    assert result.leakage_record_count == 5
    assert result.total_leakage_found == Decimal("25000")
    assert result.completed_at is not None


# ── Test 4: complete_run → PARTIAL_SUCCESS (PENDING_FX_RATE) ──────────


@pytest.mark.asyncio
async def test_complete_run_partial_fx():
    """PENDING_FX_RATE records exist → PARTIAL_SUCCESS."""
    run = MagicMock()
    run.id = RUN_ID
    run.status = "PROCESSING"

    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar.return_value = 3  # 3 PENDING_FX_RATE records

    totals_row = MagicMock()
    totals_row.record_count = 10
    totals_row.total_amount = Decimal("50000")
    totals_result = MagicMock()
    totals_result.one.return_value = totals_row

    db.execute = AsyncMock(side_effect=[count_result, totals_result])

    result = await complete_run(run, TENANT_ID, db)

    assert result.status == "PARTIAL_SUCCESS"


# ── Test 5: complete_run → PARTIAL_SUCCESS (flag) ──────────────────────


@pytest.mark.asyncio
async def test_complete_run_partial_flag():
    """has_partial_issues=True → PARTIAL_SUCCESS even with 0 PENDING_FX."""
    run = MagicMock()
    run.id = RUN_ID
    run.status = "PROCESSING"

    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar.return_value = 0

    totals_row = MagicMock()
    totals_row.record_count = 3
    totals_row.total_amount = Decimal("10000")
    totals_result = MagicMock()
    totals_result.one.return_value = totals_row

    db.execute = AsyncMock(side_effect=[count_result, totals_result])

    result = await complete_run(run, TENANT_ID, db, has_partial_issues=True)

    assert result.status == "PARTIAL_SUCCESS"


# ── Test 6: fail_run ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_run():
    run = MagicMock()
    run.status = "PROCESSING"

    result = await fail_run(run, "Out of memory during processing")

    assert result.status == "FAILED"
    assert result.error_summary == "Out of memory during processing"
    assert result.completed_at is not None


# ── Test 7: Invalid transition QUEUED → COMPLETE ──────────────────────


@pytest.mark.asyncio
async def test_invalid_transition_queued_to_complete():
    run = MagicMock()
    run.id = RUN_ID
    run.status = "QUEUED"

    db = AsyncMock()

    with pytest.raises(InvalidTransitionError, match="QUEUED.*COMPLETE"):
        await complete_run(run, TENANT_ID, db)


# ── Test 8: Terminal state → no further transitions ───────────────────


@pytest.mark.asyncio
async def test_terminal_state_no_transition():
    run = MagicMock()
    run.status = "COMPLETE"

    with pytest.raises(InvalidTransitionError, match="terminal"):
        await transition_to_processing(run)


# ── Test 9: increment_processed ───────────────────────────────────────


@pytest.mark.asyncio
async def test_increment_processed():
    run = MagicMock()
    run.status = "PROCESSING"
    run.processed_documents = 3

    result = await increment_processed(run, count=2)

    assert result.processed_documents == 5
