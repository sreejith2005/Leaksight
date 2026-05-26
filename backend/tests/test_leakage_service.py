"""
Tests for LeakSight V1 — Leakage Record Service

Tests:
1. validate_explanation: valid explanation passes
2. validate_explanation: None → error
3. validate_explanation: empty → error
4. validate_explanation: too short → error
5. validate_explanation: no financial value → error
6. create_leakage_record: creates record from RuleResult
7. create_leakage_record: invalid explanation → raises
8. accept_leakage_record: PENDING → ACCEPTED
9. accept_leakage_record: already ACCEPTED → ImmutabilityError
10. reject_leakage_record: PENDING → REJECTED
11. reject_leakage_record: already ACCEPTED → ImmutabilityError
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.rules.rule1_price_mismatch import RuleResult
from backend.app.services.leakage_service import (
    ExplanationValidationError,
    ImmutabilityError,
    accept_leakage_record,
    create_leakage_record,
    reject_leakage_record,
    validate_explanation,
)


TENANT_ID = uuid4()
RUN_ID = uuid4()
INVOICE_ID = uuid4()
USER_ID = uuid4()


def _make_rule_result(**overrides) -> RuleResult:
    return RuleResult(
        leakage_type=overrides.get("leakage_type", "PRICE_MISMATCH"),
        amount=overrides.get("amount", Decimal("5000")),
        currency=overrides.get("currency", "INR"),
        confidence=overrides.get("confidence", 1.0),
        evidence_jsonb=overrides.get("evidence_jsonb", {"test": True}),
        rule_applied=overrides.get("rule_applied", "RULE_1_PRICE_MISMATCH"),
        explanation=overrides.get(
            "explanation",
            "Invoice INV-001 from Vendor A charges ₹500/unit but contract specifies ₹450/unit. Overcharge of ₹50/unit × 100 units = ₹5000 total.",
        ),
        status=overrides.get("status", "PENDING"),
        invoice_id=overrides.get("invoice_id", INVOICE_ID),
    )


# ═══════════════════════════════════════════════════════════════════════
# validate_explanation Tests
# ═══════════════════════════════════════════════════════════════════════


def test_valid_explanation_passes():
    validate_explanation(
        "Invoice INV-001 overcharges ₹5000 total for cement"
    )


def test_none_explanation_raises():
    with pytest.raises(ExplanationValidationError, match="None"):
        validate_explanation(None)


def test_empty_explanation_raises():
    with pytest.raises(ExplanationValidationError, match="empty"):
        validate_explanation("")


def test_short_explanation_raises():
    with pytest.raises(ExplanationValidationError, match="short"):
        validate_explanation("short text ₹1")


def test_no_financial_value_raises():
    with pytest.raises(ExplanationValidationError, match="currency"):
        validate_explanation(
            "This explanation has no financial references at all and is long enough"
        )


# ═══════════════════════════════════════════════════════════════════════
# create_leakage_record Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_record_from_rule_result():
    """Creates a LeakageRecord and calls db.add."""
    rr = _make_rule_result()
    db = AsyncMock()

    record = await create_leakage_record(rr, TENANT_ID, RUN_ID, db)

    assert record.tenant_id == TENANT_ID
    assert record.run_id == RUN_ID
    assert record.leakage_type == "PRICE_MISMATCH"
    assert record.amount == Decimal("5000")
    assert record.confidence == 1.0
    assert record.status == "PENDING"
    db.add.assert_called_once_with(record)


@pytest.mark.asyncio
async def test_create_record_invalid_explanation_raises():
    """Invalid explanation prevents record creation."""
    rr = _make_rule_result(explanation="bad")
    db = AsyncMock()

    with pytest.raises(ExplanationValidationError):
        await create_leakage_record(rr, TENANT_ID, RUN_ID, db)

    db.add.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# accept / reject Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_accept_pending_record():
    """PENDING → ACCEPTED sets status and reviewer fields."""
    record_id = uuid4()
    record = MagicMock()
    record.id = record_id
    record.tenant_id = TENANT_ID
    record.status = "PENDING"

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=result_mock)

    result = await accept_leakage_record(
        record_id, USER_ID, TENANT_ID, db, notes="Looks correct"
    )

    assert result.status == "ACCEPTED"
    assert result.reviewed_by_user_id == USER_ID
    assert result.review_notes == "Looks correct"


@pytest.mark.asyncio
async def test_accept_already_accepted_raises():
    """ACCEPTED → ACCEPTED raises ImmutabilityError."""
    record_id = uuid4()
    record = MagicMock()
    record.id = record_id
    record.status = "ACCEPTED"

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=result_mock)

    with pytest.raises(ImmutabilityError, match="ACCEPTED"):
        await accept_leakage_record(record_id, USER_ID, TENANT_ID, db)


@pytest.mark.asyncio
async def test_reject_pending_record():
    """PENDING → REJECTED sets status and reviewer fields."""
    record_id = uuid4()
    record = MagicMock()
    record.id = record_id
    record.status = "PENDING"

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=result_mock)

    result = await reject_leakage_record(
        record_id, USER_ID, TENANT_ID, db, notes="False positive"
    )

    assert result.status == "REJECTED"
    assert result.reviewed_by_user_id == USER_ID


@pytest.mark.asyncio
async def test_reject_accepted_raises():
    """ACCEPTED → REJECTED raises ImmutabilityError."""
    record_id = uuid4()
    record = MagicMock()
    record.id = record_id
    record.status = "ACCEPTED"

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=result_mock)

    with pytest.raises(ImmutabilityError, match="ACCEPTED"):
        await reject_leakage_record(record_id, USER_ID, TENANT_ID, db)
