"""
LeakSight V1 — Leakage Record Service

Source: docs/DATABASE_SCHEMA.md (Section 4.2 — leakage_records),
       docs/RULES_ENGINE.md (Section 7 — Explanation Requirements),
       docs/DATABASE_SCHEMA.md (Section 4.2.2 — immutability trigger)

CRUD operations for leakage records. Handles:
  - Creating records from RuleResult
  - Accept / reject workflow
  - Immutability enforcement (ACCEPTED records cannot be modified)
  - Explanation validation (non-null, >20 chars, contains financial value)
"""

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.derived import LeakageRecord
from backend.app.rules.rule1_price_mismatch import RuleResult


class ExplanationValidationError(Exception):
    """Raised when a leakage explanation fails validation."""
    pass


class ImmutabilityError(Exception):
    """Raised when trying to modify an ACCEPTED leakage record."""
    pass


def validate_explanation(explanation: Optional[str]) -> None:
    """Validate a leakage explanation per RULES_ENGINE.md Section 7.3.

    Rules:
      - Not None
      - Not empty
      - Length > 20 characters
      - Contains at least one currency symbol or amount

    Raises ExplanationValidationError on failure.
    """
    if explanation is None:
        raise ExplanationValidationError("Explanation cannot be None")

    if not explanation.strip():
        raise ExplanationValidationError("Explanation cannot be empty")

    if len(explanation) <= 20:
        raise ExplanationValidationError(
            f"Explanation too short ({len(explanation)} chars, minimum 21)"
        )

    # Must contain at least one financial reference (₹, $, €, or a number)
    if not re.search(r"[\u20b9$\u20ac£]|\d+", explanation):
        raise ExplanationValidationError(
            "Explanation must contain at least one currency symbol or amount"
        )


async def create_leakage_record(
    rule_result: RuleResult,
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
) -> LeakageRecord:
    """Create a leakage record from a RuleResult.

    Validates the explanation before creating. Does NOT flush/commit —
    the caller controls the transaction boundary.

    Raises ExplanationValidationError if explanation is invalid.
    """
    validate_explanation(rule_result.explanation)

    record = LeakageRecord(
        tenant_id=tenant_id,
        run_id=run_id,
        leakage_type=rule_result.leakage_type,
        invoice_id=rule_result.invoice_id,
        invoice_line_item_id=rule_result.invoice_line_item_id,
        contract_line_item_id=rule_result.contract_line_item_id,
        amount=rule_result.amount,
        currency=rule_result.currency,
        confidence=rule_result.confidence,
        evidence_jsonb=rule_result.evidence_jsonb,
        rule_applied=rule_result.rule_applied,
        explanation=rule_result.explanation,
        status=rule_result.status,
    )
    db.add(record)
    return record


async def create_leakage_records(
    rule_results: List[RuleResult],
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
) -> List[LeakageRecord]:
    """Create multiple leakage records from a list of RuleResults.

    Skips results with invalid explanations (logs, does not raise).
    Returns list of successfully created records.
    """
    records = []
    for rr in rule_results:
        try:
            record = await create_leakage_record(rr, tenant_id, run_id, db)
            records.append(record)
        except ExplanationValidationError:
            # Invalid explanation — skip this record (logged at higher level)
            pass
    return records


async def accept_leakage_record(
    record_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
    notes: Optional[str] = None,
) -> LeakageRecord:
    """Mark a leakage record as ACCEPTED.

    Only PENDING records can be accepted. ACCEPTED records are immutable
    (enforced at DB level by trigger, and at app level here).

    Raises ImmutabilityError if record is already ACCEPTED.
    Raises ValueError if record not found.
    """
    stmt = select(LeakageRecord).where(
        LeakageRecord.id == record_id,
        LeakageRecord.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        raise ValueError(f"Leakage record {record_id} not found")

    if record.status == "ACCEPTED":
        raise ImmutabilityError(
            f"Leakage record {record_id} is already ACCEPTED and cannot "
            f"be modified"
        )

    record.status = "ACCEPTED"
    record.reviewed_by_user_id = user_id
    record.reviewed_at = datetime.now(timezone.utc)
    record.review_notes = notes

    return record


async def reject_leakage_record(
    record_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
    notes: Optional[str] = None,
) -> LeakageRecord:
    """Mark a leakage record as REJECTED.

    Only PENDING records can be rejected. ACCEPTED records cannot be
    changed to REJECTED.

    Raises ImmutabilityError if record is ACCEPTED.
    Raises ValueError if record not found.
    """
    stmt = select(LeakageRecord).where(
        LeakageRecord.id == record_id,
        LeakageRecord.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        raise ValueError(f"Leakage record {record_id} not found")

    if record.status == "ACCEPTED":
        raise ImmutabilityError(
            f"Leakage record {record_id} is ACCEPTED and cannot be "
            f"changed to REJECTED"
        )

    record.status = "REJECTED"
    record.reviewed_by_user_id = user_id
    record.reviewed_at = datetime.now(timezone.utc)
    record.review_notes = notes

    return record


async def get_leakage_records_for_run(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> List[LeakageRecord]:
    """Retrieve all leakage records for a given analysis run."""
    stmt = (
        select(LeakageRecord)
        .where(
            LeakageRecord.run_id == run_id,
            LeakageRecord.tenant_id == tenant_id,
        )
        .order_by(LeakageRecord.confidence.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
