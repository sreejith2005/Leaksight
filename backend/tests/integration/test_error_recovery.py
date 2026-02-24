"""
LeakSight V1 — Phase 10 Step 10.8
Test Suite: Error Recovery and State Machine

Pilot Readiness Checklist Sections:
  - Section 8.1: Analysis run never left as PROCESSING
  - Section 8.2: Per-item exceptions don't crash the entire run
  - Section 8.3: Invalid state transitions raise InvalidTransitionError
  - Section 8.4: PARTIAL_SUCCESS conditions are explicit

Tests exercise the analysis_run_service state machine and the error
handling paths in the analysis_run_task.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.services.analysis_run_service import (
    InvalidTransitionError,
    VALID_TRANSITIONS,
    complete_run,
    create_run,
    fail_run,
    increment_processed,
    transition_to_processing,
)
from backend.app.services.leakage_service import (
    ExplanationValidationError,
    ImmutabilityError,
    validate_explanation,
)
from backend.app.tasks.analysis_run_task import _build_partial_summary
from backend.tests.integration.conftest import (
    TENANT_A_ID,
    RUN_ID,
    make_analysis_run,
)


# ────────────────────────────────────────────────────────────────────────
# 10.8.1 — State Machine Transitions
# ────────────────────────────────────────────────────────────────────────

class TestStateMachineTransitions:
    """Verify strict state machine enforcement.

    Satisfies: Pilot Readiness Section 8.3.
    """

    @pytest.mark.asyncio
    async def test_queued_to_processing_valid(self):
        """QUEUED → PROCESSING is valid."""
        run = make_analysis_run(status="QUEUED")
        result = await transition_to_processing(run)
        assert result.status == "PROCESSING"
        assert result.started_at is not None

    @pytest.mark.asyncio
    async def test_processing_to_complete_valid(self):
        """PROCESSING → COMPLETE via complete_run is valid."""
        run = make_analysis_run(status="PROCESSING")

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar.return_value = 0  # no pending_fx
            # For the totals query, return a row with record_count and total_amount
            row = MagicMock()
            row.record_count = 5
            row.total_amount = Decimal("10000")
            mock_result.one.return_value = row
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await complete_run(run, TENANT_A_ID, db, has_partial_issues=False)
        assert result.status == "COMPLETE"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_processing_to_failed_valid(self):
        """PROCESSING → FAILED via fail_run is valid."""
        run = make_analysis_run(status="PROCESSING")
        result = await fail_run(run, "Test error")
        assert result.status == "FAILED"
        assert result.error_summary == "Test error"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_complete_to_processing_invalid(self):
        """COMPLETE → PROCESSING is invalid (terminal state)."""
        run = make_analysis_run(status="COMPLETE")
        with pytest.raises(InvalidTransitionError):
            await transition_to_processing(run)

    @pytest.mark.asyncio
    async def test_failed_to_complete_invalid(self):
        """FAILED → COMPLETE is invalid (terminal state)."""
        run = make_analysis_run(status="FAILED")
        db = AsyncMock()
        with pytest.raises(InvalidTransitionError):
            await complete_run(run, TENANT_A_ID, db)

    @pytest.mark.asyncio
    async def test_queued_to_complete_invalid(self):
        """QUEUED → COMPLETE is invalid (must go through PROCESSING)."""
        run = make_analysis_run(status="QUEUED")
        db = AsyncMock()
        with pytest.raises(InvalidTransitionError):
            await complete_run(run, TENANT_A_ID, db)

    @pytest.mark.asyncio
    async def test_queued_to_failed_invalid(self):
        """QUEUED → FAILED is invalid (must go through PROCESSING)."""
        run = make_analysis_run(status="QUEUED")
        with pytest.raises(InvalidTransitionError):
            await fail_run(run, "Direct fail")

    def test_valid_transitions_map_complete(self):
        """Verify VALID_TRANSITIONS map covers all states."""
        assert "QUEUED" in VALID_TRANSITIONS
        assert "PROCESSING" in VALID_TRANSITIONS
        assert "COMPLETE" in VALID_TRANSITIONS
        assert "PARTIAL_SUCCESS" in VALID_TRANSITIONS
        assert "FAILED" in VALID_TRANSITIONS
        # Terminal states have no allowed transitions
        assert VALID_TRANSITIONS["COMPLETE"] == set()
        assert VALID_TRANSITIONS["PARTIAL_SUCCESS"] == set()
        assert VALID_TRANSITIONS["FAILED"] == set()


# ────────────────────────────────────────────────────────────────────────
# 10.8.2 — PARTIAL_SUCCESS Explicit Conditions
# ────────────────────────────────────────────────────────────────────────

class TestPartialSuccessConditions:
    """Verify the three PARTIAL_SUCCESS conditions.

    Satisfies: Pilot Readiness Section 8.4.
    """

    @pytest.mark.asyncio
    async def test_pending_fx_rate_triggers_partial_success(self):
        """has_pending_fx → PARTIAL_SUCCESS."""
        run = make_analysis_run(status="PROCESSING")

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            mock_result = MagicMock()
            if call_idx == 1:
                # pending_fx_count
                mock_result.scalar.return_value = 2  # Has pending FX
            else:
                # totals
                row = MagicMock()
                row.record_count = 10
                row.total_amount = Decimal("50000")
                mock_result.one.return_value = row
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await complete_run(run, TENANT_A_ID, db, has_partial_issues=False)
        assert result.status == "PARTIAL_SUCCESS"

    @pytest.mark.asyncio
    async def test_has_partial_issues_triggers_partial_success(self):
        """has_partial_issues=True → PARTIAL_SUCCESS."""
        run = make_analysis_run(status="PROCESSING")

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            mock_result = MagicMock()
            if call_idx == 1:
                mock_result.scalar.return_value = 0  # No pending FX
            else:
                row = MagicMock()
                row.record_count = 5
                row.total_amount = Decimal("30000")
                mock_result.one.return_value = row
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await complete_run(run, TENANT_A_ID, db, has_partial_issues=True)
        assert result.status == "PARTIAL_SUCCESS"

    @pytest.mark.asyncio
    async def test_no_issues_gives_complete(self):
        """No pending FX + no partial issues → COMPLETE."""
        run = make_analysis_run(status="PROCESSING")

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            mock_result = MagicMock()
            if call_idx == 1:
                mock_result.scalar.return_value = 0
            else:
                row = MagicMock()
                row.record_count = 3
                row.total_amount = Decimal("10000")
                mock_result.one.return_value = row
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await complete_run(run, TENANT_A_ID, db, has_partial_issues=False)
        assert result.status == "COMPLETE"

    def test_partial_summary_with_failed_items(self):
        """_build_partial_summary includes failed items count."""
        summary = _build_partial_summary(
            failed_items=["item-1", "item-2"],
            has_pending_fx=False,
        )
        assert "2 line item(s) failed" in summary

    def test_partial_summary_with_pending_fx(self):
        """_build_partial_summary includes pending FX note."""
        summary = _build_partial_summary(
            failed_items=[],
            has_pending_fx=True,
        )
        assert "PENDING_FX_RATE" in summary

    def test_partial_summary_combined(self):
        """Both failed items and pending FX → combined summary."""
        summary = _build_partial_summary(
            failed_items=["item-1"],
            has_pending_fx=True,
        )
        assert "1 line item(s) failed" in summary
        assert "PENDING_FX_RATE" in summary


# ────────────────────────────────────────────────────────────────────────
# 10.8.3 — Increment Processed Counter
# ────────────────────────────────────────────────────────────────────────

class TestIncrementProcessed:
    """Verify processed_documents counter only increments while PROCESSING."""

    @pytest.mark.asyncio
    async def test_increment_while_processing(self):
        run = make_analysis_run(status="PROCESSING")
        run.processed_documents = 5
        result = await increment_processed(run, 1)
        assert result.processed_documents == 6

    @pytest.mark.asyncio
    async def test_increment_while_queued_raises(self):
        run = make_analysis_run(status="QUEUED")
        with pytest.raises(InvalidTransitionError):
            await increment_processed(run, 1)


# ────────────────────────────────────────────────────────────────────────
# 10.8.4 — Create Run
# ────────────────────────────────────────────────────────────────────────

class TestCreateRun:
    """Verify create_run initializes with correct defaults."""

    @pytest.mark.asyncio
    async def test_create_run_defaults(self):
        db = AsyncMock()
        db.add = MagicMock()
        run = await create_run(
            tenant_id=TENANT_A_ID,
            total_documents=10,
            db=db,
        )
        assert run.status == "QUEUED"
        assert run.total_documents == 10
        assert run.processed_documents == 0
        assert run.total_leakage_found == Decimal("0")
        assert run.leakage_record_count == 0
        db.add.assert_called_once()


# ────────────────────────────────────────────────────────────────────────
# 10.8.5 — Explanation Validation
# ────────────────────────────────────────────────────────────────────────

class TestExplanationValidation:
    """Verify explanation validation rules per RULES_ENGINE.md Section 7.3."""

    def test_valid_explanation_passes(self):
        """A proper explanation should not raise."""
        validate_explanation(
            "Invoice INV-001 overcharge of ₹5000 for 1000 units of cement"
        )

    def test_none_explanation_raises(self):
        with pytest.raises(ExplanationValidationError, match="None"):
            validate_explanation(None)

    def test_empty_explanation_raises(self):
        with pytest.raises(ExplanationValidationError, match="empty"):
            validate_explanation("")

    def test_short_explanation_raises(self):
        with pytest.raises(ExplanationValidationError, match="too short"):
            validate_explanation("Too short")

    def test_no_financial_ref_raises(self):
        with pytest.raises(ExplanationValidationError, match="currency symbol or amount"):
            validate_explanation("This explanation has no financial reference at all and is long enough")
