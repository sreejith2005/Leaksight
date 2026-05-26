"""
LeakSight V1 — Phase 10 Step 10.7
Test Suite: Volume and Stress Testing

Pilot Readiness Checklist Sections:
  - Section 7.1: System handles 1,000 invoices without error
  - Section 7.2: Rule engine processes high-volume batches deterministically
  - Section 7.3: Memory usage remains bounded (no list accumulation leaks)

Tests exercise the rule engine and vendor matching at scale to verify
correctness under volume. These are NOT performance benchmarks — they
verify functional correctness at pilot-ready volumes.
"""

import time
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.core.contract_resolver import (
    ContractResolutionResult,
    ContractResolutionStatus,
)
from backend.app.matching.vendor_matcher import MatchMethod, match_vendor
from backend.app.rules.rule1_price_mismatch import evaluate
from backend.app.rules.rule_engine import evaluate_line_item
from backend.tests.integration.conftest import (
    TENANT_A_ID,
    RUN_ID,
    make_contract_line_item,
    make_contract_version,
    make_invoice,
    make_invoice_line_item,
    make_tenant_settings,
    make_vendor,
)


# ────────────────────────────────────────────────────────────────────────
# 10.7.1 — 1,000 Invoice Volume Test
# ────────────────────────────────────────────────────────────────────────

class TestVolumeProcessing:
    """Verify the rule engine processes 1,000+ invoices without error.

    Satisfies: Pilot Readiness Section 7.1.
    """

    @pytest.mark.asyncio
    async def test_1000_invoices_rule1_completes(self):
        """Process 1,000 invoice line items through Rule 1 without error.
        Each should produce a valid RuleResult or None."""
        vendor_id = uuid4()
        cv = make_contract_version(valid_from=date(2024, 1, 1), valid_to=date(2026, 1, 1))
        cli = make_contract_line_item(
            contract_version_id=cv.id,
            item_desc="cement 43 grade",
            unit="KG",
            unit_price=Decimal("100"),
            currency="INR",
        )

        cr_result = ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=[cv],
        )

        ts = make_tenant_settings()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "contract_line_item" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [cli]
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        results = []
        leakage_count = 0
        clean_count = 0

        for i in range(1000):
            invoice = make_invoice(
                vendor_id=vendor_id,
                invoice_no=f"INV-VOL-{i:04d}",
                invoice_date=date(2024, 6, 15),
                currency="INR",
            )
            # Alternate: 500 with overcharge, 500 at contract price
            price = Decimal("105") if i % 2 == 0 else Decimal("100")
            line_item = make_invoice_line_item(
                invoice_id=invoice.id,
                item_desc="cement 43 grade",
                quantity=Decimal("100"),
                unit="KG",
                unit_price=price,
            )

            with patch(
                "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
            ) as mock_resolver:
                mock_resolver.return_value = cr_result
                result = await evaluate(
                    invoice_line_item=line_item,
                    invoice=invoice,
                    vendor_name="tata steel",
                    vendor_match_confidence=1.0,
                    tenant_id=TENANT_A_ID,
                    run_id=RUN_ID,
                    db=db,
                )

            if result is not None:
                leakage_count += 1
                results.append(result)
            else:
                clean_count += 1

        # 500 with overcharge → leakage, 500 at contract → clean
        assert leakage_count == 500
        assert clean_count == 500

        # All leakage amounts must be ₹500 (₹5/unit × 100 units)
        for r in results:
            assert r.amount == Decimal("500")

    @pytest.mark.asyncio
    async def test_1000_vendor_matches_complete(self):
        """Process 1,000 vendor matching calls without error."""
        vendor = make_vendor(name="tata steel")
        ts = make_tenant_settings()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = None
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "vendor" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [vendor]
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        for i in range(1000):
            result = await match_vendor(
                raw_name="tata steel",
                gst_id=None,
                tenant_id=TENANT_A_ID,
                db=db,
            )
            assert result.match_method in (MatchMethod.FUZZY, MatchMethod.ALIAS)
            assert result.confidence >= 0.85


# ────────────────────────────────────────────────────────────────────────
# 10.7.2 — Determinism at Volume
# ────────────────────────────────────────────────────────────────────────

class TestDeterminismAtVolume:
    """Verify outputs remain deterministic even at high volume.

    Satisfies: Pilot Readiness Section 7.2.
    """

    @pytest.mark.asyncio
    async def test_100_invoices_deterministic_across_runs(self):
        """Run 100 invoices twice, assert all results match."""
        vendor_id = uuid4()
        cv = make_contract_version(valid_from=date(2024, 1, 1), valid_to=date(2026, 1, 1))
        cli = make_contract_line_item(
            contract_version_id=cv.id,
            item_desc="steel bar",
            unit="KG",
            unit_price=Decimal("50"),
            currency="INR",
        )

        cr_result = ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=[cv],
        )

        ts = make_tenant_settings()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "contract_line_item" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [cli]
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        invoices_and_items = []
        for i in range(100):
            inv = make_invoice(
                vendor_id=vendor_id,
                invoice_no=f"INV-DET-VOL-{i:03d}",
                invoice_date=date(2024, 6, 15),
                currency="INR",
            )
            li = make_invoice_line_item(
                invoice_id=inv.id,
                item_desc="steel bar",
                quantity=Decimal("200"),
                unit="KG",
                unit_price=Decimal("55"),
            )
            invoices_and_items.append((inv, li))

        results_run = []
        for pass_num in range(2):
            pass_results = []
            db = AsyncMock()
            db.execute = AsyncMock(side_effect=fake_execute)
            for inv, li in invoices_and_items:
                with patch(
                    "backend.app.rules.rule1_price_mismatch.get_valid_contract_version"
                ) as mock_resolver:
                    mock_resolver.return_value = cr_result
                    r = await evaluate(
                        invoice_line_item=li,
                        invoice=inv,
                        vendor_name="steel co",
                        vendor_match_confidence=1.0,
                        tenant_id=TENANT_A_ID,
                        run_id=RUN_ID,
                        db=db,
                    )
                pass_results.append(r)
            results_run.append(pass_results)

        for i in range(100):
            r1 = results_run[0][i]
            r2 = results_run[1][i]
            assert r1 is not None and r2 is not None
            assert r1.amount == r2.amount
            assert r1.evidence_jsonb == r2.evidence_jsonb
            assert r1.explanation == r2.explanation
