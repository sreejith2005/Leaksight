"""
LeakSight V1 — Phase 10 Integration Test Fixtures

Shared fixtures for all integration test suites.  Provides factory helpers
that build mock ORM objects with realistic data, shared tenant/user/settings
context, and a reusable async DB mock.

Tests in Phase 10 exercise full cross-component flows using mocks at the DB
boundary — they integrate services, rules, matching, and reporting logic
without requiring a live PostgreSQL or Redis instance.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# ────────────────────────────────────────────────────────────────────────
# Shared Identifiers
# ────────────────────────────────────────────────────────────────────────

TENANT_A_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_B_ID = UUID("22222222-2222-2222-2222-222222222222")
RUN_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# ────────────────────────────────────────────────────────────────────────
# ORM Mock Factories
# ────────────────────────────────────────────────────────────────────────


def make_tenant_settings(
    tenant_id: UUID = TENANT_A_ID,
    fuzzy_threshold: float = 0.85,
    duplicate_window_days: int = 30,
    manual_review_threshold: float = 0.70,
    base_currency: str = "INR",
    abbreviation_dictionary: Optional[dict] = None,
) -> MagicMock:
    ts = MagicMock()
    ts.tenant_id = tenant_id
    ts.fuzzy_threshold = fuzzy_threshold
    ts.duplicate_window_days = duplicate_window_days
    ts.manual_review_threshold = manual_review_threshold
    ts.base_currency = base_currency
    ts.abbreviation_dictionary = abbreviation_dictionary or {
        "MT": "metric_ton",
        "KG": "kilogram",
        "G": "gram",
        "L": "litre",
        "ML": "millilitre",
        "NOS": "nos",
    }
    return ts


def make_vendor(
    tenant_id: UUID = TENANT_A_ID,
    name: str = "tata steel",
    gst_id: Optional[str] = None,
    vendor_id: Optional[UUID] = None,
) -> MagicMock:
    v = MagicMock()
    v.id = vendor_id or uuid4()
    v.tenant_id = tenant_id
    v.normalized_name = name
    v.raw_names_jsonb = [name]
    v.gst_id = gst_id
    return v


def make_contract(
    tenant_id: UUID = TENANT_A_ID,
    vendor_id: Optional[UUID] = None,
    contract_id: Optional[UUID] = None,
) -> MagicMock:
    c = MagicMock()
    c.id = contract_id or uuid4()
    c.tenant_id = tenant_id
    c.vendor_id = vendor_id or uuid4()
    return c


def make_contract_version(
    contract_id: Optional[UUID] = None,
    tenant_id: UUID = TENANT_A_ID,
    version_number: int = 1,
    valid_from: date = date(2024, 1, 1),
    valid_to: date = date(2025, 12, 31),
    cv_id: Optional[UUID] = None,
) -> MagicMock:
    cv = MagicMock()
    cv.id = cv_id or uuid4()
    cv.contract_id = contract_id or uuid4()
    cv.tenant_id = tenant_id
    cv.version_number = version_number
    cv.valid_from = valid_from
    cv.valid_to = valid_to
    return cv


def make_contract_line_item(
    contract_version_id: Optional[UUID] = None,
    tenant_id: UUID = TENANT_A_ID,
    item_desc: str = "cement 43 grade",
    unit: str = "KG",
    unit_price: Decimal = Decimal("100"),
    currency: str = "INR",
    cli_id: Optional[UUID] = None,
) -> MagicMock:
    cli = MagicMock()
    cli.id = cli_id or uuid4()
    cli.contract_version_id = contract_version_id or uuid4()
    cli.tenant_id = tenant_id
    cli.item_desc = item_desc
    cli.raw_item_desc = item_desc.title()
    cli.unit = unit
    cli.unit_price = unit_price
    cli.currency = currency
    return cli


def make_invoice(
    tenant_id: UUID = TENANT_A_ID,
    vendor_id: Optional[UUID] = None,
    invoice_no: str = "INV-001",
    invoice_date: date = date(2024, 6, 15),
    total_amount: Decimal = Decimal("50000"),
    currency: str = "INR",
    source_document_id: Optional[UUID] = None,
    invoice_id: Optional[UUID] = None,
) -> MagicMock:
    inv = MagicMock()
    inv.id = invoice_id or uuid4()
    inv.tenant_id = tenant_id
    inv.vendor_id = vendor_id or uuid4()
    inv.invoice_no = invoice_no
    inv.invoice_date = invoice_date
    inv.total_amount = total_amount
    inv.currency = currency
    inv.source_document_id = source_document_id or uuid4()
    return inv


def make_invoice_line_item(
    invoice_id: Optional[UUID] = None,
    tenant_id: UUID = TENANT_A_ID,
    item_desc: str = "cement 43 grade",
    quantity: Decimal = Decimal("1000"),
    unit: str = "KG",
    unit_price: Decimal = Decimal("105"),
    line_total: Optional[Decimal] = None,
    ili_id: Optional[UUID] = None,
) -> MagicMock:
    li = MagicMock()
    li.id = ili_id or uuid4()
    li.invoice_id = invoice_id or uuid4()
    li.tenant_id = tenant_id
    li.item_desc = item_desc
    li.raw_item_desc = item_desc.title()
    li.quantity = quantity
    li.unit = unit
    li.unit_price = unit_price
    li.line_total = line_total if line_total is not None else quantity * unit_price
    return li


def make_purchase_order(
    tenant_id: UUID = TENANT_A_ID,
    vendor_id: Optional[UUID] = None,
    po_no: str = "PO-001",
    po_date: date = date(2024, 5, 1),
    po_id: Optional[UUID] = None,
) -> MagicMock:
    po = MagicMock()
    po.id = po_id or uuid4()
    po.tenant_id = tenant_id
    po.vendor_id = vendor_id or uuid4()
    po.po_no = po_no
    po.po_date = po_date
    return po


def make_po_line_item(
    po_id: Optional[UUID] = None,
    tenant_id: UUID = TENANT_A_ID,
    item_desc: str = "cement 43 grade",
    unit: str = "KG",
    ordered_qty: Decimal = Decimal("100"),
    unit_price: Decimal = Decimal("100"),
    pli_id: Optional[UUID] = None,
) -> MagicMock:
    pli = MagicMock()
    pli.id = pli_id or uuid4()
    pli.po_id = po_id or uuid4()
    pli.tenant_id = tenant_id
    pli.item_desc = item_desc
    pli.raw_item_desc = item_desc.title()
    pli.unit = unit
    pli.ordered_qty = ordered_qty
    pli.unit_price = unit_price
    return pli


def make_grn(
    tenant_id: UUID = TENANT_A_ID,
    po_id: Optional[UUID] = None,
    grn_no: str = "GRN-001",
    grn_date: date = date(2024, 6, 1),
    grn_id: Optional[UUID] = None,
) -> MagicMock:
    g = MagicMock()
    g.id = grn_id or uuid4()
    g.tenant_id = tenant_id
    g.po_id = po_id or uuid4()
    g.grn_no = grn_no
    g.grn_date = grn_date
    return g


def make_grn_line_item(
    grn_id: Optional[UUID] = None,
    tenant_id: UUID = TENANT_A_ID,
    item_desc: str = "cement 43 grade",
    unit: str = "KG",
    received_qty: Decimal = Decimal("80"),
    gli_id: Optional[UUID] = None,
) -> MagicMock:
    gli = MagicMock()
    gli.id = gli_id or uuid4()
    gli.grn_id = grn_id or uuid4()
    gli.tenant_id = tenant_id
    gli.item_desc = item_desc
    gli.raw_item_desc = item_desc.title()
    gli.unit = unit
    gli.received_qty = received_qty
    return gli


def make_leakage_record(
    tenant_id: UUID = TENANT_A_ID,
    run_id: UUID = RUN_ID,
    leakage_type: str = "PRICE_MISMATCH",
    amount: Decimal = Decimal("5000"),
    currency: str = "INR",
    confidence: float = 1.0,
    status: str = "PENDING",
    explanation: str = "Test overcharge of ₹5000 total",
    evidence_jsonb: Optional[dict] = None,
    record_id: Optional[UUID] = None,
    invoice_id: Optional[UUID] = None,
    invoice_line_item_id: Optional[UUID] = None,
    contract_line_item_id: Optional[UUID] = None,
) -> MagicMock:
    rec = MagicMock()
    rec.id = record_id or uuid4()
    rec.tenant_id = tenant_id
    rec.run_id = run_id
    rec.leakage_type = leakage_type
    rec.invoice_id = invoice_id or uuid4()
    rec.invoice_line_item_id = invoice_line_item_id
    rec.contract_line_item_id = contract_line_item_id
    rec.amount = amount
    rec.currency = currency
    rec.confidence = confidence
    rec.evidence_jsonb = evidence_jsonb or {}
    rec.rule_applied = f"RULE_{'1' if leakage_type == 'PRICE_MISMATCH' else '2' if leakage_type == 'DUPLICATE_INVOICE' else '3'}"
    rec.explanation = explanation
    rec.status = status
    rec.reviewed_by_user_id = None
    rec.reviewed_at = None
    rec.review_notes = None
    rec.created_at = datetime.now(timezone.utc)
    return rec


def make_analysis_run(
    tenant_id: UUID = TENANT_A_ID,
    status: str = "QUEUED",
    run_id: Optional[UUID] = None,
    total_documents: int = 1,
) -> MagicMock:
    run = MagicMock()
    run.id = run_id or RUN_ID
    run.tenant_id = tenant_id
    run.status = status
    run.total_documents = total_documents
    run.processed_documents = 0
    run.total_leakage_found = Decimal("0")
    run.leakage_record_count = 0
    run.error_summary = None
    run.started_at = None
    run.completed_at = None
    run.created_at = datetime.now(timezone.utc)
    return run


def make_document(
    tenant_id: UUID = TENANT_A_ID,
    doc_type: str = "INVOICE",
    run_id: Optional[UUID] = None,
    file_path: str = "/tmp/test.pdf",
    sha256_hash: str = "a" * 64,
    doc_id: Optional[UUID] = None,
) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id or uuid4()
    doc.tenant_id = tenant_id
    doc.run_id = run_id
    doc.file_path = file_path
    doc.original_filename = "test.pdf"
    doc.sha256_hash = sha256_hash
    doc.doc_type = doc_type
    doc.file_size = 1024
    doc.page_count = 1
    doc.mime_type = "application/pdf"
    doc.parse_status = "PENDING"
    doc.low_confidence_flag = False
    return doc


def make_notification(
    tenant_id: UUID = TENANT_A_ID,
    user_id: UUID = USER_A_ID,
    run_id: UUID = RUN_ID,
    notification_type: str = "RUN_COMPLETE",
    message: str = "Analysis complete",
    channel: str = "IN_APP",
    notif_id: Optional[UUID] = None,
) -> MagicMock:
    n = MagicMock()
    n.id = notif_id or uuid4()
    n.tenant_id = tenant_id
    n.user_id = user_id
    n.run_id = run_id
    n.notification_type = notification_type
    n.message = message
    n.channel = channel
    n.is_read = False
    n.read_at = None
    n.email_sent_at = None
    n.email_failed_reason = None
    n.created_at = datetime.now(timezone.utc)
    return n
