"""
LeakSight V1 — Report Data Assembler

Source: docs/ARCHITECTURE.md (Section 6.7 — reporting layer),
       docs/RULES_ENGINE.md (Section 7 — evidence requirements),
       docs/API_CONTRACTS.md (Section 7 — report endpoints)

The assembler collects all data needed for a report. It never generates files.
It never calls WeasyPrint or openpyxl. It only queries the database and
assembles structured Python objects that the renderers consume.

Standing rule: financial totals must only ever include ACCEPTED records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.contracts import (
    Contract,
    ContractLineItem,
    ContractVersion,
)
from backend.app.models.derived import AnalysisRun, LeakageRecord
from backend.app.models.invoices import Invoice, InvoiceLineItem
from backend.app.models.tenant import Tenant, TenantSettings
from backend.app.models.vendors import Vendor


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class VendorLeakageSummary:
    """Per-vendor leakage summary row."""

    vendor_name: str
    total_amount: Decimal
    record_count: int


@dataclass
class RuleLeakageSummary:
    """Per-rule leakage summary row."""

    rule_type: str
    total_amount: Decimal
    record_count: int


@dataclass
class ConfidenceBandSummary:
    """Confidence band breakdown: high >= 0.9, medium 0.7-0.89, low < 0.7."""

    high_count: int = 0
    high_amount: Decimal = Decimal("0")
    medium_count: int = 0
    medium_amount: Decimal = Decimal("0")
    low_count: int = 0
    low_amount: Decimal = Decimal("0")


@dataclass
class CFOSummaryData:
    """All data needed to render the CFO summary report."""

    run_id: UUID
    run_status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_leakage_amount: Decimal
    currency: str
    leakage_by_vendor: List[VendorLeakageSummary]
    leakage_by_rule: List[RuleLeakageSummary]
    leakage_by_confidence_band: ConfidenceBandSummary
    pending_review_count: int
    pending_fx_rate_count: int
    partial_success_notes: Optional[str]
    report_generated_at: datetime


@dataclass
class EvidenceFinding:
    """One evidence finding per ACCEPTED leakage record."""

    record_id: UUID
    leakage_type: str
    amount: Decimal
    currency: str
    confidence: float
    confidence_label: str
    explanation: str
    vendor_name: str
    invoice_number: str
    invoice_date: Optional[date]
    invoice_line_item: Dict[str, Any]
    contract_reference: Dict[str, Any]
    unit_conversion_applied: bool
    unit_conversion_details: Optional[Dict[str, Any]]
    fx_rate_applied: Optional[Dict[str, Any]]
    rule_applied: str


@dataclass
class EvidencePackData:
    """All data needed to render the evidence pack."""

    run_id: UUID
    tenant_name: str
    report_generated_at: datetime
    total_leakage_amount: Decimal
    currency: str
    findings: List[EvidenceFinding]


@dataclass
class LeakageRowData:
    """A single leakage record row for Excel export sheets."""

    record_id: UUID
    vendor_name: str
    invoice_number: str
    invoice_date: Optional[date]
    item_description: str
    leakage_type: str
    amount: Decimal
    currency: str
    confidence: float
    explanation: str
    # Rule-1 specific
    invoice_unit_price: Optional[Decimal] = None
    contract_unit_price: Optional[Decimal] = None
    quantity: Optional[Decimal] = None
    # Rule-2 specific
    duplicate_of_invoice_no: Optional[str] = None
    match_type: Optional[str] = None
    # Rule-3 specific
    invoice_quantity: Optional[Decimal] = None
    authority_quantity: Optional[Decimal] = None
    authority_document_type: Optional[str] = None
    excess_quantity: Optional[Decimal] = None
    unit: Optional[str] = None


@dataclass
class VendorBreakdownRowData:
    """Vendor breakdown row for Excel export."""

    vendor_name: str
    total_leakage_amount: Decimal
    currency: str
    record_count: int
    rules_triggered: str


@dataclass
class SummarySheetData:
    """Summary sheet data for Excel export."""

    run_id: UUID
    generated_at: datetime
    total_leakage_amount: Decimal
    currency: str
    vendor_breakdown: List[VendorLeakageSummary]
    rule_breakdown: List[RuleLeakageSummary]


@dataclass
class ExcelExportData:
    """All data needed to generate the Excel export."""

    run_id: UUID
    generated_at: datetime
    summary_sheet: SummarySheetData
    price_mismatch_sheet: List[LeakageRowData]
    duplicate_invoice_sheet: List[LeakageRowData]
    quantity_mismatch_sheet: List[LeakageRowData]
    vendor_breakdown_sheet: List[VendorBreakdownRowData]


# ═══════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════


def _confidence_label(confidence: float) -> str:
    """Map a confidence score to a label: High >= 0.9, Medium 0.7-0.89, Low < 0.7."""
    if confidence >= 0.9:
        return "High"
    elif confidence >= 0.7:
        return "Medium"
    else:
        return "Low"


def _safe_decimal(val: Any) -> Decimal:
    """Safely convert a value to Decimal."""
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _safe_dict(val: Any) -> dict:
    """Safely convert to dict, returning empty dict if None."""
    if isinstance(val, dict):
        return val
    return {}


async def _get_run_and_validate(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> AnalysisRun:
    """Fetch an analysis run and validate tenant ownership.

    Raises ValueError if run not found or not owned by tenant.
    """
    stmt = select(AnalysisRun).where(
        AnalysisRun.id == run_id,
        AnalysisRun.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise ValueError(
            f"Analysis run {run_id} not found or not owned by tenant {tenant_id}"
        )

    return run


async def _get_tenant_currency(
    tenant_id: UUID,
    db: AsyncSession,
) -> str:
    """Get the base currency for a tenant from tenant_settings."""
    stmt = select(TenantSettings.base_currency).where(
        TenantSettings.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    currency = result.scalar_one_or_none()
    return currency or "INR"


async def _get_tenant_name(
    tenant_id: UUID,
    db: AsyncSession,
) -> str:
    """Get the tenant name."""
    stmt = select(Tenant.name).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    name = result.scalar_one_or_none()
    return name or "Unknown Tenant"


async def _get_accepted_records(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> list:
    """Fetch all ACCEPTED leakage records for a run."""
    stmt = (
        select(LeakageRecord)
        .where(
            LeakageRecord.run_id == run_id,
            LeakageRecord.tenant_id == tenant_id,
            LeakageRecord.status == "ACCEPTED",
        )
        .order_by(LeakageRecord.amount.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════════
# Assembler Functions
# ═══════════════════════════════════════════════════════════════════════


async def assemble_cfo_summary(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> CFOSummaryData:
    """Assemble all data needed for the CFO summary report.

    Financial totals use ACCEPTED records only (standing rule).

    Args:
        run_id: Analysis run UUID.
        tenant_id: Tenant UUID.
        db: Async database session.

    Returns:
        CFOSummaryData with all summary aggregates.

    Raises:
        ValueError: If run not found or not owned by tenant.
    """
    run = await _get_run_and_validate(run_id, tenant_id, db)
    currency = await _get_tenant_currency(tenant_id, db)

    accepted_filter = [
        LeakageRecord.run_id == run_id,
        LeakageRecord.tenant_id == tenant_id,
        LeakageRecord.status == "ACCEPTED",
    ]

    # ── Total leakage (ACCEPTED only) ─────────────────────────────
    total_stmt = select(
        func.coalesce(func.sum(LeakageRecord.amount), Decimal("0"))
    ).where(*accepted_filter)
    total_result = await db.execute(total_stmt)
    total_leakage = _safe_decimal(total_result.scalar())

    # ── Leakage by vendor (ACCEPTED only) ─────────────────────────
    vendor_stmt = (
        select(
            Vendor.normalized_name.label("vendor_name"),
            func.coalesce(func.sum(LeakageRecord.amount), Decimal("0")).label(
                "total_amount"
            ),
            func.count().label("record_count"),
        )
        .select_from(LeakageRecord)
        .join(Invoice, LeakageRecord.invoice_id == Invoice.id)
        .join(Vendor, Invoice.vendor_id == Vendor.id)
        .where(*accepted_filter)
        .group_by(Vendor.normalized_name)
        .order_by(func.sum(LeakageRecord.amount).desc())
    )
    vendor_result = await db.execute(vendor_stmt)
    leakage_by_vendor = [
        VendorLeakageSummary(
            vendor_name=row.vendor_name,
            total_amount=_safe_decimal(row.total_amount),
            record_count=row.record_count,
        )
        for row in vendor_result.all()
    ]

    # ── Leakage by rule (ACCEPTED only) ───────────────────────────
    rule_stmt = (
        select(
            LeakageRecord.leakage_type.label("rule_type"),
            func.coalesce(func.sum(LeakageRecord.amount), Decimal("0")).label(
                "total_amount"
            ),
            func.count().label("record_count"),
        )
        .where(*accepted_filter)
        .group_by(LeakageRecord.leakage_type)
    )
    rule_result = await db.execute(rule_stmt)
    leakage_by_rule = [
        RuleLeakageSummary(
            rule_type=row.rule_type,
            total_amount=_safe_decimal(row.total_amount),
            record_count=row.record_count,
        )
        for row in rule_result.all()
    ]

    # ── Confidence band breakdown (ACCEPTED only) ─────────────────
    records = await _get_accepted_records(run_id, tenant_id, db)
    band = ConfidenceBandSummary()
    for r in records:
        amount = _safe_decimal(r.amount)
        if r.confidence >= 0.9:
            band.high_count += 1
            band.high_amount += amount
        elif r.confidence >= 0.7:
            band.medium_count += 1
            band.medium_amount += amount
        else:
            band.low_count += 1
            band.low_amount += amount

    # ── Pending review count ──────────────────────────────────────
    pending_stmt = select(func.count()).where(
        LeakageRecord.run_id == run_id,
        LeakageRecord.tenant_id == tenant_id,
        LeakageRecord.status == "PENDING",
    )
    pending_result = await db.execute(pending_stmt)
    pending_review_count = pending_result.scalar() or 0

    # ── Pending FX rate count ─────────────────────────────────────
    fx_stmt = select(func.count()).where(
        LeakageRecord.run_id == run_id,
        LeakageRecord.tenant_id == tenant_id,
        LeakageRecord.status == "PENDING_FX_RATE",
    )
    fx_result = await db.execute(fx_stmt)
    pending_fx_rate_count = fx_result.scalar() or 0

    # ── Partial success notes ─────────────────────────────────────
    partial_success_notes = None
    if run.status == "PARTIAL_SUCCESS":
        notes_parts = []
        if pending_fx_rate_count > 0:
            notes_parts.append(
                f"{pending_fx_rate_count} record(s) are pending FX rate upload."
            )
        if run.error_summary:
            notes_parts.append(run.error_summary)
        if notes_parts:
            partial_success_notes = " ".join(notes_parts)
        else:
            partial_success_notes = (
                "Analysis completed with partial issues. "
                "Some documents may have had low parse confidence."
            )

    return CFOSummaryData(
        run_id=run_id,
        run_status=run.status if isinstance(run.status, str) else str(run.status),
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_leakage_amount=total_leakage,
        currency=currency,
        leakage_by_vendor=leakage_by_vendor,
        leakage_by_rule=leakage_by_rule,
        leakage_by_confidence_band=band,
        pending_review_count=pending_review_count,
        pending_fx_rate_count=pending_fx_rate_count,
        partial_success_notes=partial_success_notes,
        report_generated_at=datetime.now(timezone.utc),
    )


async def assemble_evidence_pack(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> EvidencePackData:
    """Assemble all data needed for the evidence pack.

    Each finding is fully self-contained — a reader must not need to
    look up anything else to understand it.

    Financial totals use ACCEPTED records only (standing rule).

    Args:
        run_id: Analysis run UUID.
        tenant_id: Tenant UUID.
        db: Async database session.

    Returns:
        EvidencePackData with all findings.

    Raises:
        ValueError: If run not found or not owned by tenant.
    """
    await _get_run_and_validate(run_id, tenant_id, db)
    currency = await _get_tenant_currency(tenant_id, db)
    tenant_name = await _get_tenant_name(tenant_id, db)

    records = await _get_accepted_records(run_id, tenant_id, db)

    findings: List[EvidenceFinding] = []
    total_amount = Decimal("0")

    for r in records:
        evidence = _safe_dict(r.evidence_jsonb)
        amount = _safe_decimal(r.amount)
        total_amount += amount

        # Extract invoice details
        invoice_ref = evidence.get("invoice_reference", {})
        invoice_line = {
            "item_desc": invoice_ref.get("item_desc", ""),
            "quantity": invoice_ref.get("quantity"),
            "unit": invoice_ref.get("unit", ""),
            "unit_price": invoice_ref.get("unit_price"),
        }

        # Extract contract reference
        contract_ref = evidence.get("contract_reference", {})
        contract_reference = {
            "valid_from": contract_ref.get("valid_from"),
            "valid_to": contract_ref.get("valid_to"),
            "unit_price": contract_ref.get("unit_price"),
            "unit": contract_ref.get("unit", ""),
            "version_number": contract_ref.get("version_number"),
        }

        # Extract unit conversion details
        unit_conv = evidence.get("unit_conversion_details")
        unit_conversion_applied = bool(
            unit_conv and unit_conv.get("applied", False)
        )

        # Extract FX rate details
        fx_rate = evidence.get("fx_rate_applied")

        # Get vendor name and invoice details via DB joins
        vendor_name = ""
        invoice_number = ""
        invoice_date_val = None

        if r.invoice_id:
            inv_stmt = (
                select(Invoice, Vendor)
                .join(Vendor, Invoice.vendor_id == Vendor.id)
                .where(Invoice.id == r.invoice_id)
            )
            inv_result = await db.execute(inv_stmt)
            inv_row = inv_result.first()
            if inv_row:
                invoice_obj = inv_row[0]
                vendor_obj = inv_row[1]
                vendor_name = vendor_obj.normalized_name
                invoice_number = invoice_obj.invoice_no
                invoice_date_val = invoice_obj.invoice_date

        # If invoice_line_item_id is present, get line item details
        if r.invoice_line_item_id and not invoice_line.get("item_desc"):
            ili_stmt = select(InvoiceLineItem).where(
                InvoiceLineItem.id == r.invoice_line_item_id
            )
            ili_result = await db.execute(ili_stmt)
            ili = ili_result.scalar_one_or_none()
            if ili:
                invoice_line = {
                    "item_desc": ili.item_desc,
                    "quantity": float(ili.quantity) if ili.quantity else None,
                    "unit": ili.unit,
                    "unit_price": float(ili.unit_price) if ili.unit_price else None,
                }

        # If contract_line_item_id is present, get contract details
        if r.contract_line_item_id and not contract_reference.get("unit_price"):
            cli_stmt = (
                select(ContractLineItem, ContractVersion)
                .join(
                    ContractVersion,
                    ContractLineItem.contract_version_id == ContractVersion.id,
                )
                .where(ContractLineItem.id == r.contract_line_item_id)
            )
            cli_result = await db.execute(cli_stmt)
            cli_row = cli_result.first()
            if cli_row:
                cli_obj = cli_row[0]
                cv_obj = cli_row[1]
                contract_reference = {
                    "valid_from": str(cv_obj.valid_from) if cv_obj.valid_from else None,
                    "valid_to": str(cv_obj.valid_to) if cv_obj.valid_to else None,
                    "unit_price": float(cli_obj.unit_price) if cli_obj.unit_price else None,
                    "unit": cli_obj.unit,
                    "version_number": cv_obj.version_number,
                }

        findings.append(
            EvidenceFinding(
                record_id=r.id,
                leakage_type=r.leakage_type if isinstance(r.leakage_type, str) else str(r.leakage_type),
                amount=amount,
                currency=r.currency,
                confidence=r.confidence,
                confidence_label=_confidence_label(r.confidence),
                explanation=r.explanation,
                vendor_name=vendor_name,
                invoice_number=invoice_number,
                invoice_date=invoice_date_val,
                invoice_line_item=invoice_line,
                contract_reference=contract_reference,
                unit_conversion_applied=unit_conversion_applied,
                unit_conversion_details=unit_conv if unit_conversion_applied else None,
                fx_rate_applied=fx_rate,
                rule_applied=r.rule_applied,
            )
        )

    return EvidencePackData(
        run_id=run_id,
        tenant_name=tenant_name,
        report_generated_at=datetime.now(timezone.utc),
        total_leakage_amount=total_amount,
        currency=currency,
        findings=findings,
    )


async def assemble_excel_export(
    run_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> ExcelExportData:
    """Assemble all data needed for the Excel export.

    Financial totals use ACCEPTED records only (standing rule).
    Per-type sheets contain all ACCEPTED records with all relevant fields.
    Vendor breakdown: one row per vendor with total leakage and record count.

    Args:
        run_id: Analysis run UUID.
        tenant_id: Tenant UUID.
        db: Async database session.

    Returns:
        ExcelExportData with all sheet data.

    Raises:
        ValueError: If run not found or not owned by tenant.
    """
    await _get_run_and_validate(run_id, tenant_id, db)
    currency = await _get_tenant_currency(tenant_id, db)

    # Fetch ALL accepted records with vendor info
    stmt = (
        select(LeakageRecord, Vendor.normalized_name.label("vendor_name"),
               Invoice.invoice_no, Invoice.invoice_date)
        .select_from(LeakageRecord)
        .join(Invoice, LeakageRecord.invoice_id == Invoice.id)
        .join(Vendor, Invoice.vendor_id == Vendor.id)
        .where(
            LeakageRecord.run_id == run_id,
            LeakageRecord.tenant_id == tenant_id,
            LeakageRecord.status == "ACCEPTED",
        )
        .order_by(LeakageRecord.amount.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    price_mismatch_sheet: List[LeakageRowData] = []
    duplicate_invoice_sheet: List[LeakageRowData] = []
    quantity_mismatch_sheet: List[LeakageRowData] = []

    # Vendor aggregation
    vendor_agg: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        record = row[0]
        vendor_name = row.vendor_name
        invoice_no = row.invoice_no
        invoice_date_val = row.invoice_date

        evidence = _safe_dict(record.evidence_jsonb)
        invoice_ref = evidence.get("invoice_reference", {})
        contract_ref = evidence.get("contract_reference", {})
        calc = evidence.get("calculation", {})
        dup_ref = evidence.get("duplicate_reference", {})
        qty_ref = evidence.get("quantity_reference", {})

        leakage_type = record.leakage_type if isinstance(record.leakage_type, str) else str(record.leakage_type)
        amount = _safe_decimal(record.amount)

        # Vendor aggregation
        if vendor_name not in vendor_agg:
            vendor_agg[vendor_name] = {
                "total_amount": Decimal("0"),
                "count": 0,
                "rules": set(),
            }
        vendor_agg[vendor_name]["total_amount"] += amount
        vendor_agg[vendor_name]["count"] += 1
        vendor_agg[vendor_name]["rules"].add(leakage_type)

        base_row = LeakageRowData(
            record_id=record.id,
            vendor_name=vendor_name,
            invoice_number=invoice_no,
            invoice_date=invoice_date_val,
            item_description=invoice_ref.get("item_desc", ""),
            leakage_type=leakage_type,
            amount=amount,
            currency=record.currency,
            confidence=record.confidence,
            explanation=record.explanation,
        )

        if leakage_type == "PRICE_MISMATCH":
            base_row.invoice_unit_price = _safe_decimal(
                invoice_ref.get("unit_price")
            ) if invoice_ref.get("unit_price") is not None else None
            base_row.contract_unit_price = _safe_decimal(
                contract_ref.get("unit_price")
            ) if contract_ref.get("unit_price") is not None else None
            base_row.quantity = _safe_decimal(
                invoice_ref.get("quantity")
            ) if invoice_ref.get("quantity") is not None else None
            price_mismatch_sheet.append(base_row)

        elif leakage_type == "DUPLICATE_INVOICE":
            base_row.duplicate_of_invoice_no = dup_ref.get("original_invoice_no", "")
            base_row.match_type = dup_ref.get("duplicate_type", "")
            duplicate_invoice_sheet.append(base_row)

        elif leakage_type == "QUANTITY_MISMATCH":
            base_row.invoice_quantity = _safe_decimal(
                qty_ref.get("invoiced_quantity")
            ) if qty_ref.get("invoiced_quantity") is not None else None
            base_row.authority_quantity = _safe_decimal(
                qty_ref.get("grn_quantity") or qty_ref.get("po_quantity")
            ) if (qty_ref.get("grn_quantity") or qty_ref.get("po_quantity")) is not None else None
            base_row.authority_document_type = qty_ref.get("authority_used", "")
            base_row.excess_quantity = _safe_decimal(
                qty_ref.get("quantity_difference")
            ) if qty_ref.get("quantity_difference") is not None else None
            base_row.unit = invoice_ref.get("unit", "")
            quantity_mismatch_sheet.append(base_row)

    # Build vendor breakdown
    vendor_breakdown = [
        VendorBreakdownRowData(
            vendor_name=vname,
            total_leakage_amount=vdata["total_amount"],
            currency=currency,
            record_count=vdata["count"],
            rules_triggered=", ".join(sorted(vdata["rules"])),
        )
        for vname, vdata in vendor_agg.items()
    ]
    vendor_breakdown.sort(key=lambda x: x.total_leakage_amount, reverse=True)

    # Summary aggregates (reuse vendor and rule logic)
    total_leakage = sum(
        (r[0].amount for r in rows), Decimal("0")
    )

    # Rule breakdown for summary
    rule_agg: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        record = row[0]
        lt = record.leakage_type if isinstance(record.leakage_type, str) else str(record.leakage_type)
        if lt not in rule_agg:
            rule_agg[lt] = {"total_amount": Decimal("0"), "count": 0}
        rule_agg[lt]["total_amount"] += _safe_decimal(record.amount)
        rule_agg[lt]["count"] += 1

    vendor_summary = [
        VendorLeakageSummary(
            vendor_name=vname,
            total_amount=vdata["total_amount"],
            record_count=vdata["count"],
        )
        for vname, vdata in vendor_agg.items()
    ]
    vendor_summary.sort(key=lambda x: x.total_amount, reverse=True)

    rule_summary = [
        RuleLeakageSummary(
            rule_type=rtype,
            total_amount=rdata["total_amount"],
            record_count=rdata["count"],
        )
        for rtype, rdata in rule_agg.items()
    ]

    generated_at = datetime.now(timezone.utc)

    return ExcelExportData(
        run_id=run_id,
        generated_at=generated_at,
        summary_sheet=SummarySheetData(
            run_id=run_id,
            generated_at=generated_at,
            total_leakage_amount=total_leakage,
            currency=currency,
            vendor_breakdown=vendor_summary,
            rule_breakdown=rule_summary,
        ),
        price_mismatch_sheet=price_mismatch_sheet,
        duplicate_invoice_sheet=duplicate_invoice_sheet,
        quantity_mismatch_sheet=quantity_mismatch_sheet,
        vendor_breakdown_sheet=vendor_breakdown,
    )
