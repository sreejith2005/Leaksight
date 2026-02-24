"""
LeakSight V1 — Phase 10 Step 10.3
Test Suite: Contract Resolution Integration

Pilot Readiness Checklist Sections:
  - Section 4.1: Contract version validity — date range resolution
  - Section 4.2: Contract overlap → manual review (confidence 0.5)
  - Section 4.3: No contract → skip Rule 1 (no false positive)

Tests exercise contract_resolver.get_valid_contract_version() with various
date / overlap / multi-version scenarios through to the leakage outcome.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.core.contract_resolver import (
    ContractResolutionResult,
    ContractResolutionStatus,
    get_valid_contract_version,
)
from backend.app.rules.rule1_price_mismatch import RuleResult, evaluate
from backend.tests.integration.conftest import (
    TENANT_A_ID,
    RUN_ID,
    make_contract,
    make_contract_line_item,
    make_contract_version,
    make_invoice,
    make_invoice_line_item,
    make_tenant_settings,
    make_vendor,
)


# ────────────────────────────────────────────────────────────────────────
# 10.3.1 — Date Range Resolution
# ────────────────────────────────────────────────────────────────────────

class TestDateRangeResolution:
    """Verify half-open interval semantics: valid_from <= date < valid_to.

    Satisfies: Pilot Readiness Section 4.1.
    """

    @pytest.mark.asyncio
    async def test_invoice_on_valid_from_date_matches(self):
        """Invoice dated exactly on valid_from should match (inclusive)."""
        vendor_id = uuid4()
        contract_id = uuid4()
        cv = make_contract_version(
            contract_id=contract_id,
            valid_from=date(2024, 1, 1),
            valid_to=date(2025, 1, 1),
        )

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [cv]
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await get_valid_contract_version(
            vendor_id=vendor_id,
            invoice_date=date(2024, 1, 1),  # Exactly on valid_from
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.status == ContractResolutionStatus.FOUND
        assert len(result.versions) == 1

    @pytest.mark.asyncio
    async def test_invoice_on_valid_to_date_does_not_match(self):
        """Invoice dated exactly on valid_to should NOT match (exclusive)."""
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await get_valid_contract_version(
            vendor_id=uuid4(),
            invoice_date=date(2025, 1, 1),  # Exactly on valid_to (exclusive)
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.status == ContractResolutionStatus.NONE
        assert len(result.versions) == 0

    @pytest.mark.asyncio
    async def test_invoice_within_range_matches(self):
        """Invoice dated mid-range should match normally."""
        cv = make_contract_version(
            valid_from=date(2024, 1, 1),
            valid_to=date(2025, 1, 1),
        )

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [cv]
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await get_valid_contract_version(
            vendor_id=uuid4(),
            invoice_date=date(2024, 6, 15),
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.status == ContractResolutionStatus.FOUND
        assert result.versions[0].id == cv.id

    @pytest.mark.asyncio
    async def test_invoice_before_range_no_match(self):
        """Invoice dated before valid_from should return NONE."""
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await get_valid_contract_version(
            vendor_id=uuid4(),
            invoice_date=date(2023, 12, 31),
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.status == ContractResolutionStatus.NONE


# ────────────────────────────────────────────────────────────────────────
# 10.3.2 — Contract Overlap → Manual Review
# ────────────────────────────────────────────────────────────────────────

class TestContractOverlap:
    """Verify that overlapping contract versions trigger OVERLAP status
    and that Rule 1 produces a confidence=0.5 manual review result.

    Satisfies: Pilot Readiness Section 4.2.
    """

    @pytest.mark.asyncio
    async def test_overlap_returns_overlap_status(self):
        """Two versions covering the same date → OVERLAP."""
        cv1 = make_contract_version(
            valid_from=date(2024, 1, 1),
            valid_to=date(2025, 1, 1),
            version_number=1,
        )
        cv2 = make_contract_version(
            valid_from=date(2024, 6, 1),
            valid_to=date(2025, 6, 1),
            version_number=2,
        )

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [cv1, cv2]
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await get_valid_contract_version(
            vendor_id=uuid4(),
            invoice_date=date(2024, 7, 1),
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.status == ContractResolutionStatus.OVERLAP
        assert len(result.versions) == 2

    @pytest.mark.asyncio
    async def test_overlap_produces_confidence_05_result(self):
        """When contract_resolver returns OVERLAP, Rule 1 must produce
        a result with confidence=0.5, amount=0, and manual review flag."""
        vendor_id = uuid4()
        cv1 = make_contract_version(version_number=1)
        cv2 = make_contract_version(version_number=2)

        cr_result = ContractResolutionResult(
            status=ContractResolutionStatus.OVERLAP,
            versions=[cv1, cv2],
        )

        invoice = make_invoice(vendor_id=vendor_id, currency="INR")
        line_item = make_invoice_line_item(
            invoice_id=invoice.id,
            quantity=Decimal("100"),
            unit_price=Decimal("200"),
        )

        db = AsyncMock()

        with patch(
            "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
        ) as mock_resolver:
            mock_resolver.return_value = cr_result
            result = await evaluate(
                invoice_line_item=line_item,
                invoice=invoice,
                vendor_name="overlap vendor",
                vendor_match_confidence=1.0,
                tenant_id=TENANT_A_ID,
                run_id=RUN_ID,
                db=db,
            )

        assert result is not None
        assert result.confidence == 0.5
        assert result.amount == Decimal("0")
        assert "overlap" in result.explanation.lower() or "manual review" in result.explanation.lower()
        assert result.evidence_jsonb.get("contract_overlap") is True


# ────────────────────────────────────────────────────────────────────────
# 10.3.3 — No Contract → Skip (No False Positive)
# ────────────────────────────────────────────────────────────────────────

class TestNoContractSkip:
    """Verify that absence of a contract means Rule 1 returns None,
    not a fabricated leakage finding.

    Satisfies: Pilot Readiness Section 4.3.
    """

    @pytest.mark.asyncio
    async def test_no_contract_rule1_returns_none(self):
        """No contract covering invoice date → Rule 1 returns None."""
        cr_result = ContractResolutionResult(
            status=ContractResolutionStatus.NONE,
            versions=[],
        )

        invoice = make_invoice(currency="INR")
        line_item = make_invoice_line_item(
            invoice_id=invoice.id,
            quantity=Decimal("100"),
            unit_price=Decimal("500"),
        )

        db = AsyncMock()

        with patch(
            "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
        ) as mock_resolver:
            mock_resolver.return_value = cr_result
            result = await evaluate(
                invoice_line_item=line_item,
                invoice=invoice,
                vendor_name="no contract co",
                vendor_match_confidence=1.0,
                tenant_id=TENANT_A_ID,
                run_id=RUN_ID,
                db=db,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_contract_no_leakage_record_created(self):
        """End-to-end: when there's no contract, the leakage service
        should never be called for Rule 1."""
        vendor_id = uuid4()

        cr_result = ContractResolutionResult(
            status=ContractResolutionStatus.NONE,
            versions=[],
        )

        ts = make_tenant_settings()
        invoice = make_invoice(vendor_id=vendor_id, currency="INR")
        line_item = make_invoice_line_item(
            invoice_id=invoice.id,
            item_desc="no contract item",
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
        )

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "invoice" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = []
            elif "purchase_order" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = []
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        with patch(
            "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
        ) as mock_resolver:
            mock_resolver.return_value = cr_result
            from backend.app.rules.rule_engine import evaluate_line_item
            results = await evaluate_line_item(
                invoice_line_item=line_item,
                invoice=invoice,
                vendor_name="no contract co",
                vendor_match_confidence=1.0,
                tenant_id=TENANT_A_ID,
                run_id=RUN_ID,
                db=db,
                checked_invoice_ids=set(),
            )

        # No PRICE_MISMATCH results
        price_results = [r for r in results if r.leakage_type == "PRICE_MISMATCH"]
        assert len(price_results) == 0


# ────────────────────────────────────────────────────────────────────────
# 10.3.4 — Contract Version Succession
# ────────────────────────────────────────────────────────────────────────

class TestContractVersionSuccession:
    """Verify that multi-version contracts are resolved correctly when
    versions are consecutive (non-overlapping)."""

    @pytest.mark.asyncio
    async def test_correct_version_selected_by_date(self):
        """Invoice in v1 period gets v1 pricing, invoice in v2 period
        gets v2 pricing — both through Rule 1."""
        vendor_id = uuid4()

        # Version 1: 2024-01-01 to 2024-07-01 (exclusive), price 100
        cv1 = make_contract_version(
            version_number=1,
            valid_from=date(2024, 1, 1),
            valid_to=date(2024, 7, 1),
        )
        cli_v1 = make_contract_line_item(
            contract_version_id=cv1.id,
            item_desc="widget",
            unit="NOS",
            unit_price=Decimal("100"),
            currency="INR",
        )

        # Version 2: 2024-07-01 to 2025-01-01 (exclusive), price 120
        cv2 = make_contract_version(
            version_number=2,
            valid_from=date(2024, 7, 1),
            valid_to=date(2025, 1, 1),
        )
        cli_v2 = make_contract_line_item(
            contract_version_id=cv2.id,
            item_desc="widget",
            unit="NOS",
            unit_price=Decimal("120"),
            currency="INR",
        )

        # Invoice A: date 2024-03-15 → should use v1 → price 100
        inv_a = make_invoice(
            vendor_id=vendor_id,
            invoice_no="INV-V1",
            invoice_date=date(2024, 3, 15),
            currency="INR",
        )
        li_a = make_invoice_line_item(
            invoice_id=inv_a.id,
            item_desc="widget",
            quantity=Decimal("100"),
            unit="NOS",
            unit_price=Decimal("110"),
        )

        # Invoice B: date 2024-08-15 → should use v2 → price 120
        inv_b = make_invoice(
            vendor_id=vendor_id,
            invoice_no="INV-V2",
            invoice_date=date(2024, 8, 15),
            currency="INR",
        )
        li_b = make_invoice_line_item(
            invoice_id=inv_b.id,
            item_desc="widget",
            quantity=Decimal("100"),
            unit="NOS",
            unit_price=Decimal("130"),
        )

        cr_result_v1 = ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=[cv1],
        )
        cr_result_v2 = ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=[cv2],
        )

        async def make_fake_execute(cli_to_return):
            async def fake_execute(stmt):
                mock_result = MagicMock()
                stmt_str = str(stmt)
                if "tenant_settings" in stmt_str.lower():
                    mock_result.scalar_one_or_none.return_value = make_tenant_settings()
                elif "contract_line_item" in stmt_str.lower():
                    mock_result.scalars.return_value.all.return_value = [cli_to_return]
                else:
                    mock_result.scalar_one_or_none.return_value = None
                    mock_result.scalars.return_value.all.return_value = []
                return mock_result
            return fake_execute

        # Test Invoice A → v1 pricing → ₹110-100 = ₹10/unit × 100 = ₹1000
        db_a = AsyncMock()
        db_a.execute = AsyncMock(side_effect=await make_fake_execute(cli_v1))

        with patch(
            "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
        ) as mock_resolver:
            mock_resolver.return_value = cr_result_v1
            result_a = await evaluate(
                invoice_line_item=li_a,
                invoice=inv_a,
                vendor_name="widget co",
                vendor_match_confidence=1.0,
                tenant_id=TENANT_A_ID,
                run_id=RUN_ID,
                db=db_a,
            )

        assert result_a is not None
        assert result_a.amount == Decimal("1000")

        # Test Invoice B → v2 pricing → ₹130-120 = ₹10/unit × 100 = ₹1000
        db_b = AsyncMock()
        db_b.execute = AsyncMock(side_effect=await make_fake_execute(cli_v2))

        with patch(
            "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
        ) as mock_resolver:
            mock_resolver.return_value = cr_result_v2
            result_b = await evaluate(
                invoice_line_item=li_b,
                invoice=inv_b,
                vendor_name="widget co",
                vendor_match_confidence=1.0,
                tenant_id=TENANT_A_ID,
                run_id=RUN_ID,
                db=db_b,
            )

        assert result_b is not None
        assert result_b.amount == Decimal("1000")
        # Both found leakage but against different contract versions
        assert result_a.evidence_jsonb["contract_reference"]["version_number"] == 1
        assert result_b.evidence_jsonb["contract_reference"]["version_number"] == 2
