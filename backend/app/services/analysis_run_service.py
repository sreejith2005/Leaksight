"""
LeakSight V1 — Analysis Run Service

Source: docs/DATABASE_SCHEMA.md (Section 4.1 — analysis_runs),
       docs/RULES_ENGINE.md (Section 3.5 — PARTIAL_SUCCESS conditions)

Manages the lifecycle of an analysis run:
  QUEUED → PROCESSING → COMPLETE | PARTIAL_SUCCESS | FAILED

PARTIAL_SUCCESS conditions (from RULES_ENGINE.md):
  - One or more PENDING_FX_RATE records were created
  - One or more invoice line items had cross-dimension unit mismatches
  - One or more contract version overlaps required manual review

Status transitions are strictly enforced — invalid transitions raise.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.derived import AnalysisRun, LeakageRecord


class InvalidTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""
    pass


# Valid status transitions
VALID_TRANSITIONS = {
    "QUEUED": {"PROCESSING"},
    "PROCESSING": {"COMPLETE", "PARTIAL_SUCCESS", "FAILED"},
    # Terminal states — no further transitions
    "COMPLETE": set(),
    "PARTIAL_SUCCESS": set(),
    "FAILED": set(),
}


async def create_run(
    tenant_id: UUID,
    total_documents: int,
    db: AsyncSession,
) -> AnalysisRun:
    """Create a new analysis run in QUEUED status.

    Args:
        tenant_id: Tenant UUID.
        total_documents: Number of documents to be processed.
        db: Async database session.

    Returns:
        New AnalysisRun instance (added to session, not committed).
    """
    run = AnalysisRun(
        tenant_id=tenant_id,
        status="QUEUED",
        total_documents=total_documents,
        processed_documents=0,
        total_leakage_found=Decimal("0"),
        leakage_record_count=0,
    )
    db.add(run)
    return run


async def transition_to_processing(
    run: AnalysisRun,
) -> AnalysisRun:
    """Transition a run from QUEUED to PROCESSING.

    Sets started_at timestamp.

    Raises InvalidTransitionError if current status is not QUEUED.
    """
    _validate_transition(run.status, "PROCESSING")
    run.status = "PROCESSING"
    run.started_at = datetime.now(timezone.utc)
    return run


async def complete_run(
    run: AnalysisRun,
    tenant_id: UUID,
    db: AsyncSession,
    has_partial_issues: bool = False,
) -> AnalysisRun:
    """Complete a run — determines COMPLETE vs PARTIAL_SUCCESS.

    Automatically checks for PENDING_FX_RATE records. If any exist or
    has_partial_issues is True, status becomes PARTIAL_SUCCESS.

    Also tallies the final leakage totals from the leakage_records table.

    Raises InvalidTransitionError if current status is not PROCESSING.
    """
    _validate_transition(run.status, "COMPLETE")

    # Check for PENDING_FX_RATE records
    pending_fx_count_stmt = (
        select(func.count())
        .select_from(LeakageRecord)
        .where(
            LeakageRecord.run_id == run.id,
            LeakageRecord.tenant_id == tenant_id,
            LeakageRecord.status == "PENDING_FX_RATE",
        )
    )
    result = await db.execute(pending_fx_count_stmt)
    pending_fx_count = result.scalar() or 0

    # Tally leakage totals
    totals_stmt = (
        select(
            func.count().label("record_count"),
            func.coalesce(func.sum(LeakageRecord.amount), Decimal("0")).label("total_amount"),
        )
        .select_from(LeakageRecord)
        .where(
            LeakageRecord.run_id == run.id,
            LeakageRecord.tenant_id == tenant_id,
        )
    )
    totals_result = await db.execute(totals_stmt)
    totals_row = totals_result.one()

    run.leakage_record_count = totals_row.record_count
    run.total_leakage_found = totals_row.total_amount
    run.completed_at = datetime.now(timezone.utc)

    if pending_fx_count > 0 or has_partial_issues:
        run.status = "PARTIAL_SUCCESS"
    else:
        run.status = "COMPLETE"

    return run


async def fail_run(
    run: AnalysisRun,
    error_summary: str,
) -> AnalysisRun:
    """Transition a run to FAILED status.

    Raises InvalidTransitionError if current status is not PROCESSING.
    """
    _validate_transition(run.status, "FAILED")
    run.status = "FAILED"
    run.error_summary = error_summary
    run.completed_at = datetime.now(timezone.utc)
    return run


async def increment_processed(
    run: AnalysisRun,
    count: int = 1,
) -> AnalysisRun:
    """Increment the processed_documents counter.

    Only valid while status is PROCESSING.
    """
    if run.status != "PROCESSING":
        raise InvalidTransitionError(
            f"Cannot increment processed count while status is {run.status}"
        )
    run.processed_documents = (run.processed_documents or 0) + count
    return run


def _validate_transition(current_status: str, target_status: str) -> None:
    """Validate that a status transition is allowed.

    Raises InvalidTransitionError if the transition is not in VALID_TRANSITIONS.
    """
    current = current_status if isinstance(current_status, str) else current_status.value
    allowed = VALID_TRANSITIONS.get(current, set())
    if target_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {current} to {target_status}. "
            f"Allowed transitions: {allowed or 'none (terminal state)'}"
        )
