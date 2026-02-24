"""
Tests for LeakSight V1 — Report Data Assembler

Source: docs/ARCHITECTURE.md (reporting engine section),
       docs/RULES_ENGINE.md (evidence requirements)

Tests:
1. CFO summary with known data → correct totals, vendor grouping, confidence bands
2. CFO summary ACCEPTED-only filter → PENDING records excluded from total_leakage_amount
3. Evidence pack with full evidence_jsonb → all EvidenceFinding fields populated
4. Evidence pack with no accepted records → empty findings list, no crash
5. Excel export data structure → all sheets populated correctly
6. Run not owned by tenant → ValueError raised
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from uuid import UUID, uuid4

import pytest

from backend.app.reporting.report_assembler import (
    CFOSummaryData,
    ConfidenceBandSummary,
    EvidencePackData,
    ExcelExportData,
    VendorLeakageSummary,
    _confidence_label,
    _safe_decimal,
    assemble_cfo_summary,
    assemble_evidence_pack,
    assemble_excel_export,
)

TENANT_ID = uuid4()
RUN_ID = uuid4()
INVOICE_ID = uuid4()
VENDOR_ID = uuid4()
CONTRACT_LINE_ID = uuid4()
INVOICE_LINE_ID = uuid4()


# ═══════════════════════════════════════════════════════════════════════
# Helper: confidence label
# ═══════════════════════════════════════════════════════════════════════


def test_confidence_label_high():
    assert _confidence_label(0.95) == "High"
    assert _confidence_label(0.9) == "High"
    assert _confidence_label(1.0) == "High"


def test_confidence_label_medium():
    assert _confidence_label(0.89) == "Medium"
    assert _confidence_label(0.7) == "Medium"
    assert _confidence_label(0.75) == "Medium"


def test_confidence_label_low():
    assert _confidence_label(0.69) == "Low"
    assert _confidence_label(0.0) == "Low"
    assert _confidence_label(0.5) == "Low"


def test_safe_decimal_none():
    assert _safe_decimal(None) == Decimal("0")


def test_safe_decimal_decimal():
    assert _safe_decimal(Decimal("100.50")) == Decimal("100.50")


def test_safe_decimal_float():
    assert _safe_decimal(100.5) == Decimal("100.5")


# ═══════════════════════════════════════════════════════════════════════
# Fixtures for mock DB
# ═══════════════════════════════════════════════════════════════════════


def _make_run(status="COMPLETE", error_summary=None):
    run = MagicMock()
    run.id = RUN_ID
    run.tenant_id = TENANT_ID
    run.status = status
    run.started_at = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
    run.completed_at = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    run.error_summary = error_summary
    return run


def _make_leakage_record(
    record_id=None,
    leakage_type="PRICE_MISMATCH",
    amount=Decimal("5000"),
    currency="INR",
    confidence=0.92,
    status="ACCEPTED",
    explanation="Invoice INV-001 from Vendor A charges ₹500/unit but contract specifies ₹450/unit. Overcharge of ₹50/unit × 100 units = ₹5000 total.",
    evidence_jsonb=None,
):
    rec = MagicMock()
    rec.id = record_id or uuid4()
    rec.run_id = RUN_ID
    rec.tenant_id = TENANT_ID
    rec.leakage_type = leakage_type
    rec.invoice_id = INVOICE_ID
    rec.invoice_line_item_id = INVOICE_LINE_ID
    rec.contract_line_item_id = CONTRACT_LINE_ID
    rec.amount = amount
    rec.currency = currency
    rec.confidence = confidence
    rec.status = status
    rec.explanation = explanation
    rec.rule_applied = f"RULE_1_{leakage_type}" if leakage_type == "PRICE_MISMATCH" else f"RULE_{leakage_type}"
    rec.evidence_jsonb = evidence_jsonb or {
        "invoice_reference": {
            "item_desc": "Cement OPC 53 Grade",
            "quantity": 100,
            "unit": "MT",
            "unit_price": 500.0,
        },
        "contract_reference": {
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "unit_price": 450.0,
            "unit": "MT",
            "version_number": 1,
        },
        "calculation": {
            "price_diff_per_unit": 50.0,
            "quantity": 100,
            "total_leakage": 5000.0,
            "currency": "INR",
        },
        "unit_conversion_details": None,
        "fx_rate_applied": None,
        "match_confidence_breakdown": {
            "vendor_match_method": "ALIAS",
            "vendor_match_confidence": 1.0,
            "item_match_method": "EXACT",
            "item_match_confidence": 1.0,
            "overall": 0.92,
        },
        "source_documents": [],
    }
    return rec


def _make_vendor_row(vendor_name="tata steel", leakage_amount=Decimal("5000"), record_count=1):
    row = MagicMock()
    row.vendor_name = vendor_name
    row.total_amount = leakage_amount
    row.record_count = record_count
    return row


def _make_rule_row(rule_type="PRICE_MISMATCH", total_amount=Decimal("5000"), record_count=1):
    row = MagicMock()
    row.rule_type = rule_type
    row.total_amount = total_amount
    row.record_count = record_count
    return row


# ═══════════════════════════════════════════════════════════════════════
# Test: CFO summary with known data
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cfo_summary_known_data():
    """CFO summary with known data → correct totals, vendor grouping, confidence bands."""
    db = AsyncMock()

    run = _make_run()

    # DB execute calls sequence:
    # 1. Run query
    # 2. Tenant currency
    # 3. Total leakage
    # 4. By vendor
    # 5. By rule
    # 6. Accepted records (for confidence bands)
    # 7. Pending count
    # 8. Pending FX rate count

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = run

    currency_result = MagicMock()
    currency_result.scalar_one_or_none.return_value = "INR"

    total_result = MagicMock()
    total_result.scalar.return_value = Decimal("15000")

    vendor_row1 = _make_vendor_row("tata steel", Decimal("10000"), 2)
    vendor_row2 = _make_vendor_row("jsw steel", Decimal("5000"), 1)
    vendor_result = MagicMock()
    vendor_result.all.return_value = [vendor_row1, vendor_row2]

    rule_row1 = _make_rule_row("PRICE_MISMATCH", Decimal("10000"), 2)
    rule_row2 = _make_rule_row("DUPLICATE_INVOICE", Decimal("5000"), 1)
    rule_result = MagicMock()
    rule_result.all.return_value = [rule_row1, rule_row2]

    # Accepted records for confidence band calc
    rec_high = _make_leakage_record(confidence=0.95, amount=Decimal("10000"))
    rec_medium = _make_leakage_record(confidence=0.85, amount=Decimal("3000"))
    rec_low = _make_leakage_record(confidence=0.65, amount=Decimal("2000"))
    accepted_result = MagicMock()
    accepted_result.scalars.return_value.all.return_value = [rec_high, rec_medium, rec_low]

    pending_result = MagicMock()
    pending_result.scalar.return_value = 3

    fx_result = MagicMock()
    fx_result.scalar.return_value = 1

    db.execute = AsyncMock(side_effect=[
        run_result,       # 1. Run
        currency_result,  # 2. Currency
        total_result,     # 3. Total
        vendor_result,    # 4. Vendors
        rule_result,      # 5. Rules
        accepted_result,  # 6. Accepted records (conf bands)
        pending_result,   # 7. Pending
        fx_result,        # 8. FX pending
    ])

    result = await assemble_cfo_summary(RUN_ID, TENANT_ID, db)

    assert isinstance(result, CFOSummaryData)
    assert result.run_id == RUN_ID
    assert result.total_leakage_amount == Decimal("15000")
    assert result.currency == "INR"
    assert len(result.leakage_by_vendor) == 2
    assert result.leakage_by_vendor[0].vendor_name == "tata steel"
    assert result.leakage_by_vendor[0].total_amount == Decimal("10000")
    assert len(result.leakage_by_rule) == 2
    assert result.leakage_by_confidence_band.high_count == 1
    assert result.leakage_by_confidence_band.high_amount == Decimal("10000")
    assert result.leakage_by_confidence_band.medium_count == 1
    assert result.leakage_by_confidence_band.medium_amount == Decimal("3000")
    assert result.leakage_by_confidence_band.low_count == 1
    assert result.leakage_by_confidence_band.low_amount == Decimal("2000")
    assert result.pending_review_count == 3
    assert result.pending_fx_rate_count == 1


# ═══════════════════════════════════════════════════════════════════════
# Test: CFO summary ACCEPTED-only filter
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cfo_summary_accepted_only():
    """PENDING records excluded from total_leakage_amount."""
    db = AsyncMock()

    run = _make_run()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = run

    currency_result = MagicMock()
    currency_result.scalar_one_or_none.return_value = "INR"

    # Total leakage = only ACCEPTED (the assembler queries on ACCEPTED filter)
    total_result = MagicMock()
    total_result.scalar.return_value = Decimal("5000")

    vendor_result = MagicMock()
    vendor_result.all.return_value = [_make_vendor_row("tata steel", Decimal("5000"), 1)]

    rule_result = MagicMock()
    rule_result.all.return_value = [_make_rule_row("PRICE_MISMATCH", Decimal("5000"), 1)]

    # Only 1 accepted record at high confidence
    rec = _make_leakage_record(confidence=0.95, amount=Decimal("5000"))
    accepted_result = MagicMock()
    accepted_result.scalars.return_value.all.return_value = [rec]

    # 2 PENDING records exist but are not in totals
    pending_result = MagicMock()
    pending_result.scalar.return_value = 2

    fx_result = MagicMock()
    fx_result.scalar.return_value = 0

    db.execute = AsyncMock(side_effect=[
        run_result, currency_result, total_result, vendor_result,
        rule_result, accepted_result, pending_result, fx_result,
    ])

    result = await assemble_cfo_summary(RUN_ID, TENANT_ID, db)

    # Total should be 5000 (ACCEPTED only), not 15000 (ACCEPTED + PENDING)
    assert result.total_leakage_amount == Decimal("5000")
    assert result.pending_review_count == 2
    assert result.pending_fx_rate_count == 0


# ═══════════════════════════════════════════════════════════════════════
# Test: Evidence pack with full evidence_jsonb
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_evidence_pack_full_evidence():
    """Evidence pack with full evidence_jsonb → all EvidenceFinding fields populated."""
    db = AsyncMock()

    run = _make_run()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = run

    currency_result = MagicMock()
    currency_result.scalar_one_or_none.return_value = "INR"

    tenant_name_result = MagicMock()
    tenant_name_result.scalar_one_or_none.return_value = "Acme Corp"

    evidence = {
        "invoice_reference": {
            "item_desc": "Cement OPC 53 Grade",
            "quantity": 100,
            "unit": "MT",
            "unit_price": 500.0,
        },
        "contract_reference": {
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "unit_price": 450.0,
            "unit": "MT",
            "version_number": 1,
        },
        "unit_conversion_details": {
            "applied": True,
            "from_unit": "KG",
            "to_unit": "MT",
            "factor": 0.001,
            "source": "SYSTEM",
        },
        "fx_rate_applied": {
            "from_currency": "USD",
            "to_currency": "INR",
            "rate": 83.5,
            "rate_date": "2026-01-15",
            "source": "MANUAL_UPLOAD",
        },
        "match_confidence_breakdown": {
            "vendor_match_method": "ALIAS",
            "vendor_match_confidence": 1.0,
            "item_match_method": "EXACT",
            "item_match_confidence": 1.0,
            "overall": 0.92,
        },
    }

    rec = _make_leakage_record(evidence_jsonb=evidence, confidence=0.92)
    accepted_result = MagicMock()
    accepted_result.scalars.return_value.all.return_value = [rec]

    # Invoice + Vendor join result
    invoice_mock = MagicMock()
    invoice_mock.invoice_no = "INV-2026-001"
    invoice_mock.invoice_date = date(2026, 1, 15)
    vendor_mock = MagicMock()
    vendor_mock.normalized_name = "tata steel"
    inv_join_result = MagicMock()
    inv_join_result.first.return_value = (invoice_mock, vendor_mock)

    # contract line item + version join (not needed, evidence has data)
    cli_join_result = MagicMock()
    cli_join_result.first.return_value = None

    db.execute = AsyncMock(side_effect=[
        run_result,         # Run validation
        currency_result,    # Tenant currency
        tenant_name_result, # Tenant name
        accepted_result,    # Accepted records
        inv_join_result,    # Invoice + vendor join
        cli_join_result,    # Contract line item join (skipped bc evidence has data)
    ])

    result = await assemble_evidence_pack(RUN_ID, TENANT_ID, db)

    assert isinstance(result, EvidencePackData)
    assert result.run_id == RUN_ID
    assert result.tenant_name == "Acme Corp"
    assert len(result.findings) == 1

    finding = result.findings[0]
    assert finding.amount == Decimal("5000")
    assert finding.confidence == 0.92
    assert finding.confidence_label == "High"
    assert finding.vendor_name == "tata steel"
    assert finding.invoice_number == "INV-2026-001"
    assert finding.unit_conversion_applied is True
    assert finding.unit_conversion_details is not None
    assert finding.unit_conversion_details["from_unit"] == "KG"
    assert finding.fx_rate_applied is not None
    assert finding.fx_rate_applied["rate"] == 83.5


# ═══════════════════════════════════════════════════════════════════════
# Test: Evidence pack with no accepted records
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_evidence_pack_no_accepted_records():
    """Evidence pack with no accepted records → empty findings, no crash."""
    db = AsyncMock()

    run = _make_run()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = run

    currency_result = MagicMock()
    currency_result.scalar_one_or_none.return_value = "INR"

    tenant_name_result = MagicMock()
    tenant_name_result.scalar_one_or_none.return_value = "Acme Corp"

    accepted_result = MagicMock()
    accepted_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(side_effect=[
        run_result, currency_result, tenant_name_result, accepted_result,
    ])

    result = await assemble_evidence_pack(RUN_ID, TENANT_ID, db)

    assert result.findings == []
    assert result.total_leakage_amount == Decimal("0")


# ═══════════════════════════════════════════════════════════════════════
# Test: Excel export data structure
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_excel_export_all_sheets():
    """Excel export data structure → all sheets populated correctly."""
    db = AsyncMock()

    run = _make_run()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = run

    currency_result = MagicMock()
    currency_result.scalar_one_or_none.return_value = "INR"

    # Create records of different types
    rec_pm = _make_leakage_record(
        leakage_type="PRICE_MISMATCH",
        amount=Decimal("5000"),
        confidence=0.92,
    )
    rec_dup = _make_leakage_record(
        leakage_type="DUPLICATE_INVOICE",
        amount=Decimal("10000"),
        confidence=1.0,
        evidence_jsonb={
            "invoice_reference": {"item_desc": "Invoice Total"},
            "duplicate_reference": {
                "original_invoice_no": "INV-2026-002",
                "duplicate_type": "EXACT",
            },
        },
    )
    rec_qty = _make_leakage_record(
        leakage_type="QUANTITY_MISMATCH",
        amount=Decimal("2000"),
        confidence=0.9,
        evidence_jsonb={
            "invoice_reference": {
                "item_desc": "Cement OPC",
                "unit": "MT",
            },
            "quantity_reference": {
                "invoiced_quantity": 120,
                "grn_quantity": 100,
                "po_quantity": 110,
                "authority_used": "GRN",
                "quantity_difference": 20,
            },
        },
    )

    # Build row tuples as the query returns
    row1 = MagicMock()
    row1.__getitem__ = lambda self, idx: rec_pm if idx == 0 else None
    row1.vendor_name = "tata steel"
    row1.invoice_no = "INV-001"
    row1.invoice_date = date(2026, 1, 15)
    # Make row1[0] return rec_pm
    type(row1).__getitem__ = lambda self, key: rec_pm if key == 0 else None

    row2 = MagicMock()
    row2.vendor_name = "jsw steel"
    row2.invoice_no = "INV-002"
    row2.invoice_date = date(2026, 1, 20)
    type(row2).__getitem__ = lambda self, key: rec_dup if key == 0 else None

    row3 = MagicMock()
    row3.vendor_name = "tata steel"
    row3.invoice_no = "INV-003"
    row3.invoice_date = date(2026, 1, 25)
    type(row3).__getitem__ = lambda self, key: rec_qty if key == 0 else None

    records_result = MagicMock()
    records_result.all.return_value = [row1, row2, row3]

    db.execute = AsyncMock(side_effect=[
        run_result, currency_result, records_result,
    ])

    result = await assemble_excel_export(RUN_ID, TENANT_ID, db)

    assert isinstance(result, ExcelExportData)
    assert result.run_id == RUN_ID
    assert len(result.price_mismatch_sheet) == 1
    assert len(result.duplicate_invoice_sheet) == 1
    assert len(result.quantity_mismatch_sheet) == 1
    assert len(result.vendor_breakdown_sheet) == 2  # tata steel + jsw steel

    # Vendor breakdown sorted by amount desc
    # jsw steel: 10000 (1 record), tata steel: 5000 + 2000 = 7000 (2 records)
    assert result.vendor_breakdown_sheet[0].vendor_name == "jsw steel"
    assert result.vendor_breakdown_sheet[0].total_leakage_amount == Decimal("10000")
    assert result.vendor_breakdown_sheet[0].record_count == 1
    assert result.vendor_breakdown_sheet[1].vendor_name == "tata steel"
    assert result.vendor_breakdown_sheet[1].total_leakage_amount == Decimal("7000")
    assert result.vendor_breakdown_sheet[1].record_count == 2

    # Summary sheet
    assert result.summary_sheet.total_leakage_amount == Decimal("17000")


# ═══════════════════════════════════════════════════════════════════════
# Test: Run not owned by tenant
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cfo_summary_run_not_found():
    """Run not found or not owned by tenant → ValueError raised."""
    db = AsyncMock()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=run_result)

    with pytest.raises(ValueError, match="not found"):
        await assemble_cfo_summary(RUN_ID, TENANT_ID, db)


@pytest.mark.asyncio
async def test_evidence_pack_run_not_found():
    """Run not found or not owned by tenant → ValueError raised."""
    db = AsyncMock()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=run_result)

    with pytest.raises(ValueError, match="not found"):
        await assemble_evidence_pack(RUN_ID, TENANT_ID, db)


@pytest.mark.asyncio
async def test_excel_export_run_not_found():
    """Run not found or not owned by tenant → ValueError raised."""
    db = AsyncMock()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=run_result)

    with pytest.raises(ValueError, match="not found"):
        await assemble_excel_export(RUN_ID, TENANT_ID, db)
