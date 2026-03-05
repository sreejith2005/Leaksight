"""
Tests for LeakSight V1 — Rules Engine

Tests cover:
  Rule 1:
    1. Price mismatch detected → RuleResult with correct leakage
    2. No contract → returns None (skip)
    3. Contract overlap → confidence 0.5
    4. PENDING_FX_RATE when currencies differ and no rate
    5. Zero quantity → skip

  Rule 2:
    6. Exact duplicate → confidence 1.0
    7. Near-duplicate → confidence 0.85
    8. No duplicate → empty list

  Rule 3:
    9.  GRN authority overcharge → leakage detected
    10. PO fallback → confidence 0.90
    11. No GRN / no PO → skip (None)

  Orchestrator:
    12. Runs all three rules, collects results
    13. Rule 2 only runs once per invoice
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.rules.rule1_price_mismatch import (
    RuleResult,
    evaluate as rule1_evaluate,
)
from backend.app.rules.rule2_duplicate_invoice import evaluate as rule2_evaluate
from backend.app.rules.rule3_quantity_mismatch import evaluate as rule3_evaluate
from backend.app.rules.rule_engine import evaluate_line_item


TENANT_ID = uuid4()
RUN_ID = uuid4()
VENDOR_ID = uuid4()
INVOICE_ID = uuid4()
LINE_ITEM_ID = uuid4()
CONTRACT_VERSION_ID = uuid4()
CONTRACT_LINE_ITEM_ID = uuid4()


def _make_invoice(**overrides):
    inv = MagicMock()
    inv.id = overrides.get("id", INVOICE_ID)
    inv.tenant_id = TENANT_ID
    inv.vendor_id = overrides.get("vendor_id", VENDOR_ID)
    inv.invoice_no = overrides.get("invoice_no", "INV-001")
    inv.invoice_date = overrides.get("invoice_date", date(2024, 6, 15))
    inv.total_amount = overrides.get("total_amount", Decimal("50000"))
    inv.currency = overrides.get("currency", "INR")
    return inv


def _make_line_item(**overrides):
    li = MagicMock()
    li.id = overrides.get("id", LINE_ITEM_ID)
    li.invoice_id = INVOICE_ID
    li.tenant_id = TENANT_ID
    li.item_desc = overrides.get("item_desc", "cement 43 grade")
    li.raw_item_desc = overrides.get("raw_item_desc", "Cement 43 Grade")
    li.quantity = overrides.get("quantity", Decimal("100"))
    li.unit = overrides.get("unit", "MT")
    li.unit_price = overrides.get("unit_price", Decimal("500"))
    li.line_total = overrides.get("line_total", Decimal("50000"))
    return li


def _make_contract_version(**overrides):
    cv = MagicMock()
    cv.id = overrides.get("id", CONTRACT_VERSION_ID)
    cv.contract_id = overrides.get("contract_id", uuid4())
    cv.version_number = overrides.get("version_number", 1)
    cv.valid_from = overrides.get("valid_from", date(2024, 1, 1))
    cv.valid_to = overrides.get("valid_to", date(2024, 12, 31))
    return cv


def _make_contract_line_item(**overrides):
    cli = MagicMock()
    cli.id = overrides.get("id", CONTRACT_LINE_ITEM_ID)
    cli.contract_version_id = CONTRACT_VERSION_ID
    cli.tenant_id = TENANT_ID
    cli.item_desc = overrides.get("item_desc", "cement 43 grade")
    cli.unit = overrides.get("unit", "MT")
    cli.unit_price = overrides.get("unit_price", Decimal("450"))
    cli.currency = overrides.get("currency", "INR")
    return cli


# ═══════════════════════════════════════════════════════════════════════
# Rule 1 Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("backend.app.rules.rule1_price_mismatch._get_fuzzy_threshold", return_value=0.85)
@patch("backend.app.rules.rule1_price_mismatch.get_valid_contract_version")
@patch("backend.app.rules.rule1_price_mismatch._match_item")
async def test_rule1_price_mismatch_detected(mock_match, mock_contract, mock_thresh):
    """Invoice price > contract price → leakage detected."""
    from backend.app.core.contract_resolver import (
        ContractResolutionResult,
        ContractResolutionStatus,
    )

    cv = _make_contract_version()
    mock_contract.return_value = ContractResolutionResult(
        status=ContractResolutionStatus.FOUND, versions=[cv]
    )

    cli = _make_contract_line_item(unit_price=Decimal("450"))
    mock_match.return_value = (cli, 1.0, "EXACT")

    invoice = _make_invoice(currency="INR")
    line_item = _make_line_item(
        unit_price=Decimal("500"), quantity=Decimal("100"), unit="MT"
    )

    db = AsyncMock()
    result = await rule1_evaluate(
        line_item, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db
    )

    assert result is not None
    assert result.leakage_type == "PRICE_MISMATCH"
    assert result.amount == Decimal("5000")  # (500-450) * 100
    assert result.confidence == 1.0
    assert result.status == "PENDING"
    assert "Overcharge" in result.explanation


@pytest.mark.asyncio
@patch("backend.app.rules.rule1_price_mismatch.get_valid_contract_version")
async def test_rule1_no_contract_skips(mock_contract):
    """No valid contract → returns None."""
    from backend.app.core.contract_resolver import (
        ContractResolutionResult,
        ContractResolutionStatus,
    )

    mock_contract.return_value = ContractResolutionResult(
        status=ContractResolutionStatus.NONE, versions=[]
    )

    invoice = _make_invoice()
    line_item = _make_line_item()
    db = AsyncMock()

    result = await rule1_evaluate(
        line_item, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db
    )
    assert result is None


@pytest.mark.asyncio
@patch("backend.app.rules.rule1_price_mismatch.get_valid_contract_version")
async def test_rule1_overlap_confidence_05(mock_contract):
    """Overlapping contract versions → confidence 0.5."""
    from backend.app.core.contract_resolver import (
        ContractResolutionResult,
        ContractResolutionStatus,
    )

    shared_contract_id = uuid4()
    mock_contract.return_value = ContractResolutionResult(
        status=ContractResolutionStatus.OVERLAP,
        versions=[_make_contract_version(contract_id=shared_contract_id), _make_contract_version(contract_id=shared_contract_id)],
    )

    invoice = _make_invoice()
    line_item = _make_line_item()
    db = AsyncMock()

    result = await rule1_evaluate(
        line_item, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db
    )
    assert result is not None
    assert result.confidence == 0.5
    assert "multiple contract versions" in result.explanation.lower() or "manual review" in result.explanation.lower()


@pytest.mark.asyncio
@patch("backend.app.rules.rule1_price_mismatch._get_fuzzy_threshold", return_value=0.85)
@patch("backend.app.rules.rule1_price_mismatch.get_valid_contract_version")
@patch("backend.app.rules.rule1_price_mismatch._match_item")
@patch("backend.app.rules.rule1_price_mismatch.get_rate")
async def test_rule1_pending_fx_rate(mock_fx, mock_match, mock_contract, mock_thresh):
    """Different currencies, no FX rate → PENDING_FX_RATE."""
    from backend.app.core.contract_resolver import (
        ContractResolutionResult,
        ContractResolutionStatus,
    )
    from backend.app.core.fx_service import PENDING_FX_RATE

    cv = _make_contract_version()
    mock_contract.return_value = ContractResolutionResult(
        status=ContractResolutionStatus.FOUND, versions=[cv]
    )

    cli = _make_contract_line_item(unit_price=Decimal("450"), currency="INR")
    mock_match.return_value = (cli, 1.0, "EXACT")
    mock_fx.return_value = PENDING_FX_RATE

    invoice = _make_invoice(currency="USD")
    line_item = _make_line_item(unit_price=Decimal("6"), unit="MT")
    db = AsyncMock()

    result = await rule1_evaluate(
        line_item, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db
    )

    assert result is not None
    assert result.status == "PENDING_FX_RATE"
    assert result.amount == Decimal("0")
    assert "FX rate" in result.explanation


@pytest.mark.asyncio
async def test_rule1_zero_quantity_skips():
    """Zero quantity → returns None (edge case)."""
    invoice = _make_invoice()
    line_item = _make_line_item(quantity=Decimal("0"))
    db = AsyncMock()

    result = await rule1_evaluate(
        line_item, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db
    )
    assert result is None


# ═══════════════════════════════════════════════════════════════════════
# Rule 2 Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule2_exact_duplicate():
    """Exact duplicate found → confidence 1.0."""
    dupe = _make_invoice(id=uuid4(), invoice_no="INV-001")

    db = AsyncMock()

    # Mock: exact query returns one dupe
    exact_result_mock = MagicMock()
    exact_scalars = MagicMock()
    exact_scalars.all.return_value = [dupe]
    exact_result_mock.scalars.return_value = exact_scalars

    db.execute = AsyncMock(return_value=exact_result_mock)

    invoice = _make_invoice()
    results = await rule2_evaluate(invoice, "Vendor A", TENANT_ID, RUN_ID, db)

    assert len(results) >= 1
    assert results[0].leakage_type == "DUPLICATE_INVOICE"
    assert results[0].confidence == 1.0
    assert "exact duplicate" in results[0].explanation.lower()


@pytest.mark.asyncio
async def test_rule2_near_duplicate():
    """Near-duplicate (same vendor, same amount, within window) → confidence 0.85."""
    near_dupe = _make_invoice(
        id=uuid4(),
        invoice_no="INV-002",
        invoice_date=date(2024, 6, 20),
    )

    db = AsyncMock()

    # First call: exact query → empty
    exact_result_mock = MagicMock()
    exact_scalars = MagicMock()
    exact_scalars.all.return_value = []
    exact_result_mock.scalars.return_value = exact_scalars

    # Second call: tenant settings
    settings_mock = MagicMock()
    settings_mock.scalar_one_or_none.return_value = None  # use defaults

    # Third call: near query → one near dupe
    near_result_mock = MagicMock()
    near_scalars = MagicMock()
    near_scalars.all.return_value = [near_dupe]
    near_result_mock.scalars.return_value = near_scalars

    # Fourth call: source invoice line items for item_desc filtering
    src_li_result_mock = MagicMock()
    src_li_result_mock.fetchall.return_value = [("cement 43 grade",)]

    # Fifth call: dupe invoice line items for item_desc filtering
    dupe_li_result_mock = MagicMock()
    dupe_li_result_mock.fetchall.return_value = [("cement 43 grade",)]

    db.execute = AsyncMock(
        side_effect=[exact_result_mock, settings_mock, near_result_mock,
                     src_li_result_mock, dupe_li_result_mock]
    )

    invoice = _make_invoice()
    results = await rule2_evaluate(invoice, "Vendor A", TENANT_ID, RUN_ID, db)

    assert len(results) == 1
    assert results[0].confidence == 0.85
    assert "NEAR_DUPLICATE" in results[0].evidence_jsonb["duplicate_reference"]["duplicate_type"]


@pytest.mark.asyncio
async def test_rule2_no_duplicate():
    """No duplicates → empty list."""
    db = AsyncMock()

    # Exact query → empty
    exact_mock = MagicMock()
    exact_s = MagicMock()
    exact_s.all.return_value = []
    exact_mock.scalars.return_value = exact_s

    # Settings
    settings_mock = MagicMock()
    settings_mock.scalar_one_or_none.return_value = None

    # Near query → empty
    near_mock = MagicMock()
    near_s = MagicMock()
    near_s.all.return_value = []
    near_mock.scalars.return_value = near_s

    db.execute = AsyncMock(side_effect=[exact_mock, settings_mock, near_mock])

    invoice = _make_invoice()
    results = await rule2_evaluate(invoice, "Vendor A", TENANT_ID, RUN_ID, db)
    assert results == []


# ═══════════════════════════════════════════════════════════════════════
# Rule 3 Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule3_grn_overcharge():
    """Invoice qty > GRN qty → leakage detected (GRN authority)."""
    grn_li = MagicMock()
    grn_li.id = uuid4()
    grn_li.grn_id = uuid4()
    grn_li.item_desc = "cement 43 grade"
    grn_li.received_qty = Decimal("80")

    grn_header = MagicMock()
    grn_header.id = grn_li.grn_id
    grn_header.grn_date = date(2024, 6, 10)

    po = MagicMock()
    po.id = uuid4()
    po.vendor_id = VENDOR_ID
    po.po_no = "PO-001"

    db = AsyncMock()

    # settings → default
    settings_mock = MagicMock()
    settings_mock.scalar_one_or_none.return_value = None

    # PO query → one PO
    po_result = MagicMock()
    po_scalars = MagicMock()
    po_scalars.all.return_value = [po]
    po_result.scalars.return_value = po_scalars

    # GRN query → one GRN
    grn_result = MagicMock()
    grn_scalars = MagicMock()
    grn_scalars.all.return_value = [grn_header]
    grn_result.scalars.return_value = grn_scalars

    # GRN line items → one match
    gli_result = MagicMock()
    gli_scalars = MagicMock()
    gli_scalars.all.return_value = [grn_li]
    gli_result.scalars.return_value = gli_scalars

    db.execute = AsyncMock(
        side_effect=[settings_mock, po_result, grn_result, gli_result]
    )

    invoice = _make_invoice()
    line_item = _make_line_item(
        quantity=Decimal("100"), unit_price=Decimal("500")
    )

    result = await rule3_evaluate(
        line_item, invoice, "Vendor A", TENANT_ID, RUN_ID, db
    )

    assert result is not None
    assert result.leakage_type == "QUANTITY_MISMATCH"
    assert result.amount == Decimal("10000")  # (100-80) * 500
    assert result.confidence == 1.0
    assert "GRN" in result.explanation


@pytest.mark.asyncio
async def test_rule3_po_fallback():
    """No GRN, PO only → PO authority, confidence 0.90."""
    po = MagicMock()
    po.id = uuid4()
    po.vendor_id = VENDOR_ID
    po.po_no = "PO-001"

    po_li = MagicMock()
    po_li.id = uuid4()
    po_li.po_id = po.id
    po_li.item_desc = "cement 43 grade"
    po_li.ordered_qty = Decimal("80")

    db = AsyncMock()

    # settings → default
    settings_mock = MagicMock()
    settings_mock.scalar_one_or_none.return_value = None

    # PO query → one PO
    po_result = MagicMock()
    po_scalars = MagicMock()
    po_scalars.all.return_value = [po]
    po_result.scalars.return_value = po_scalars

    # GRN query → empty (no GRNs)
    grn_result = MagicMock()
    grn_scalars = MagicMock()
    grn_scalars.all.return_value = []
    grn_result.scalars.return_value = grn_scalars

    # PO line items (for fallback path)
    pli_result = MagicMock()
    pli_scalars = MagicMock()
    pli_scalars.all.return_value = [po_li]
    pli_result.scalars.return_value = pli_scalars

    db.execute = AsyncMock(
        side_effect=[settings_mock, po_result, grn_result, pli_result]
    )

    invoice = _make_invoice()
    line_item = _make_line_item(
        quantity=Decimal("100"), unit_price=Decimal("500")
    )

    result = await rule3_evaluate(
        line_item, invoice, "Vendor A", TENANT_ID, RUN_ID, db
    )

    assert result is not None
    assert result.leakage_type == "QUANTITY_MISMATCH"
    assert result.confidence == 0.90
    assert "PO used as authority" in result.explanation


@pytest.mark.asyncio
async def test_rule3_no_grn_no_po_skips():
    """No GRN and no PO → skip, returns None."""
    db = AsyncMock()

    # settings → default
    settings_mock = MagicMock()
    settings_mock.scalar_one_or_none.return_value = None

    # PO query → empty (no POs for this vendor)
    po_result = MagicMock()
    po_scalars = MagicMock()
    po_scalars.all.return_value = []
    po_result.scalars.return_value = po_scalars

    db.execute = AsyncMock(side_effect=[settings_mock, po_result])

    invoice = _make_invoice()
    line_item = _make_line_item()

    result = await rule3_evaluate(
        line_item, invoice, "Vendor A", TENANT_ID, RUN_ID, db
    )
    assert result is None


# ═══════════════════════════════════════════════════════════════════════
# Orchestrator Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("backend.app.rules.rule_engine.rule3_quantity_mismatch")
@patch("backend.app.rules.rule_engine.rule2_duplicate_invoice")
@patch("backend.app.rules.rule_engine.rule1_price_mismatch")
async def test_orchestrator_collects_results(mock_r1, mock_r2, mock_r3):
    """Orchestrator runs all three rules and collects their results."""
    r1_result = RuleResult(
        leakage_type="PRICE_MISMATCH",
        amount=Decimal("5000"),
        currency="INR",
        confidence=1.0,
        evidence_jsonb={},
        rule_applied="RULE_1_PRICE_MISMATCH",
        explanation="Test explanation with ₹5000 overcharge detected",
        status="PENDING",
        invoice_id=INVOICE_ID,
        invoice_line_item_id=LINE_ITEM_ID,
    )
    mock_r1.evaluate = AsyncMock(return_value=r1_result)
    mock_r2.evaluate = AsyncMock(return_value=[])
    mock_r3.evaluate = AsyncMock(return_value=None)

    invoice = _make_invoice()
    line_item = _make_line_item()
    db = AsyncMock()
    checked = set()

    results = await evaluate_line_item(
        line_item, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db, checked
    )

    assert len(results) == 1
    assert results[0].leakage_type == "PRICE_MISMATCH"
    mock_r1.evaluate.assert_called_once()
    mock_r2.evaluate.assert_called_once()
    mock_r3.evaluate.assert_called_once()


@pytest.mark.asyncio
@patch("backend.app.rules.rule_engine.rule3_quantity_mismatch")
@patch("backend.app.rules.rule_engine.rule2_duplicate_invoice")
@patch("backend.app.rules.rule_engine.rule1_price_mismatch")
async def test_orchestrator_rule2_once_per_invoice(mock_r1, mock_r2, mock_r3):
    """Rule 2 only runs once per invoice, even across multiple line items."""
    mock_r1.evaluate = AsyncMock(return_value=None)
    mock_r2.evaluate = AsyncMock(return_value=[])
    mock_r3.evaluate = AsyncMock(return_value=None)

    invoice = _make_invoice()
    li1 = _make_line_item(id=uuid4())
    li2 = _make_line_item(id=uuid4())
    db = AsyncMock()
    checked = set()

    # First line item — Rule 2 runs
    await evaluate_line_item(
        li1, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db, checked
    )
    assert mock_r2.evaluate.call_count == 1

    # Second line item from same invoice — Rule 2 should NOT run again
    await evaluate_line_item(
        li2, invoice, "Vendor A", 1.0, TENANT_ID, RUN_ID, db, checked
    )
    assert mock_r2.evaluate.call_count == 1  # Still 1
