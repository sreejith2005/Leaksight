"""
LeakSight V1 — Normalization Service

Source: docs/ARCHITECTURE.md (Section 6.3 — normalization_service.py)
       docs/PARSING_SPEC.md (Section 8 — confidence enforcement allows normalization to run)
       docs/DATABASE_SCHEMA.md (Sections 3.3, 3.11, 3.12)
       docs/RULES_ENGINE.md (matching engine)

Bridge from RAW layer (raw_parses / ParseResult) to Canonical layer
(vendors, invoices, invoice_line_items).

Pipeline steps:
  1. Vendor resolution — match_vendor() five-step chain; auto-create if NO_MATCH
  2. Item normalization — ItemNormalizer abbreviation dictionary
  3. Invoice header creation — Invoice canonical row
  4. Line item creation — InvoiceLineItem canonical rows
  5. Vendor raw_names_jsonb update — append new raw name variant

Skipped when parse_confidence == 0 (total failure).
Runs even when low_confidence_flag is True (PARTIAL_SUCCESS).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.matching.item_normalizer import ItemNormalizer, create_item_normalizer
from backend.app.matching.vendor_matcher import MatchMethod, VendorMatchResult, match_vendor
from backend.app.matching.vendor_normalizer import normalize_vendor_name
from backend.app.models.invoices import Invoice, InvoiceLineItem
from backend.app.models.vendors import Vendor
from backend.app.parsers.base_parser import DocType, ParseResult

logger = get_logger(__name__)


@dataclass
class NormalizationResult:
    """Outcome of the normalization pipeline for a single ParseResult.

    Attributes:
        document_id: UUID of the source document.
        vendor_id: Resolved/created vendor UUID.
        vendor_match_method: How the vendor was matched (GST_EXACT, ALIAS, FUZZY, AUTO_CREATED).
        vendor_match_confidence: Vendor match confidence (1.0 for auto-created).
        invoice_id: Created invoice UUID (None for non-invoice doc types).
        line_items_created: Number of line items written to canonical layer.
        skipped: True if normalization was skipped (e.g. total failure).
        skip_reason: Reason normalization was skipped.
    """

    document_id: UUID
    vendor_id: Optional[UUID] = None
    vendor_match_method: Optional[str] = None
    vendor_match_confidence: float = 0.0
    invoice_id: Optional[UUID] = None
    line_items_created: int = 0
    skipped: bool = False
    skip_reason: Optional[str] = None


async def normalize_parse_result(
    db: AsyncSession,
    parse_result: ParseResult,
    tenant_id: UUID,
) -> NormalizationResult:
    """Run the full normalization pipeline on a ParseResult.

    Steps:
      1. Check if normalization should be skipped (total failure / missing vendor)
      2. Resolve vendor via match_vendor five-step chain
      3. Auto-create vendor if NO_MATCH
      4. Create Invoice canonical row (for INVOICE doc_type)
      5. Normalize + create InvoiceLineItem rows
      6. Update vendor raw_names_jsonb with new raw name variant

    Args:
        db: Async database session.
        parse_result: The parsed document output.
        tenant_id: Tenant UUID.

    Returns:
        NormalizationResult summarizing what was written.
    """
    doc_id = parse_result.document_id

    # ------------------------------------------------------------------
    # Guard: skip on total failure
    # ------------------------------------------------------------------
    if parse_result.parse_confidence == 0.0:
        logger.info(
            "normalization_skipped",
            document_id=str(doc_id),
            reason="total_parse_failure",
        )
        return NormalizationResult(
            document_id=doc_id,
            skipped=True,
            skip_reason="total_parse_failure",
        )

    # ------------------------------------------------------------------
    # Guard: skip if no vendor name extracted
    # ------------------------------------------------------------------
    raw_vendor_name = parse_result.header.vendor_name
    if not raw_vendor_name or not raw_vendor_name.strip():
        logger.warning(
            "normalization_skipped",
            document_id=str(doc_id),
            reason="missing_vendor_name",
        )
        return NormalizationResult(
            document_id=doc_id,
            skipped=True,
            skip_reason="missing_vendor_name",
        )

    # ------------------------------------------------------------------
    # Step 1 — Vendor resolution (five-step chain)
    # ------------------------------------------------------------------
    gst_id = parse_result.header.vendor_gst_id
    vendor_result: VendorMatchResult = await match_vendor(
        raw_name=raw_vendor_name,
        gst_id=gst_id,
        tenant_id=tenant_id,
        db=db,
    )

    vendor_id = vendor_result.matched_vendor_id
    match_method = vendor_result.match_method.value

    # ------------------------------------------------------------------
    # Step 2 — Auto-create vendor if NO_MATCH
    # ------------------------------------------------------------------
    if vendor_result.match_method == MatchMethod.NO_MATCH:
        vendor_id = await _auto_create_vendor(
            db=db,
            raw_name=raw_vendor_name,
            gst_id=gst_id,
            tenant_id=tenant_id,
        )
        match_method = "AUTO_CREATED"
        logger.info(
            "vendor_auto_created",
            document_id=str(doc_id),
            vendor_id=str(vendor_id),
        )
    else:
        # Append raw name variant to existing vendor
        await _update_vendor_raw_names(
            db=db,
            vendor_id=vendor_id,
            raw_name=raw_vendor_name,
        )

    # ------------------------------------------------------------------
    # Step 3 — Create canonical invoice (INVOICE doc_type only)
    # ------------------------------------------------------------------
    invoice_id: Optional[UUID] = None
    line_items_created = 0

    if parse_result.doc_type == DocType.INVOICE:
        invoice_id = await _create_invoice(
            db=db,
            parse_result=parse_result,
            vendor_id=vendor_id,
            tenant_id=tenant_id,
        )

        # ------------------------------------------------------------------
        # Step 4 — Normalize + create line items
        # ------------------------------------------------------------------
        item_normalizer = await create_item_normalizer(
            tenant_id=tenant_id,
            db=db,
        )
        line_items_created = await _create_line_items(
            db=db,
            parse_result=parse_result,
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            item_normalizer=item_normalizer,
        )

    logger.info(
        "normalization_complete",
        document_id=str(doc_id),
        vendor_id=str(vendor_id),
        match_method=match_method,
        invoice_id=str(invoice_id) if invoice_id else None,
        line_items_created=line_items_created,
    )

    return NormalizationResult(
        document_id=doc_id,
        vendor_id=vendor_id,
        vendor_match_method=match_method,
        vendor_match_confidence=vendor_result.confidence,
        invoice_id=invoice_id,
        line_items_created=line_items_created,
    )


async def _auto_create_vendor(
    db: AsyncSession,
    raw_name: str,
    gst_id: Optional[str],
    tenant_id: UUID,
) -> UUID:
    """Create a new vendor in the canonical layer when NO_MATCH is found.

    The vendor is created with:
    - normalized_name from vendor_normalizer
    - raw_names_jsonb containing the first raw name variant
    - gst_id if available

    Args:
        db: Async database session.
        raw_name: The raw vendor name from the document.
        gst_id: GST/Tax ID if available.
        tenant_id: Tenant UUID.

    Returns:
        UUID of the created vendor.
    """
    normalized = normalize_vendor_name(raw_name)

    vendor = Vendor(
        tenant_id=tenant_id,
        normalized_name=normalized,
        raw_names_jsonb=[raw_name],
        gst_id=gst_id,
    )
    db.add(vendor)
    await db.flush()  # populate vendor.id

    return vendor.id


async def _update_vendor_raw_names(
    db: AsyncSession,
    vendor_id: UUID,
    raw_name: str,
) -> None:
    """Append a raw name variant to an existing vendor's raw_names_jsonb.

    Only appends if the raw_name is not already present (deduplication).

    Args:
        db: Async database session.
        vendor_id: Vendor UUID.
        raw_name: Raw vendor name to append.
    """
    result = await db.execute(
        select(Vendor.raw_names_jsonb).where(Vendor.id == vendor_id)
    )
    current_names = result.scalar_one_or_none()

    if current_names is None:
        current_names = []

    if raw_name not in current_names:
        updated_names = current_names + [raw_name]
        await db.execute(
            update(Vendor)
            .where(Vendor.id == vendor_id)
            .values(raw_names_jsonb=updated_names)
        )


async def _create_invoice(
    db: AsyncSession,
    parse_result: ParseResult,
    vendor_id: UUID,
    tenant_id: UUID,
) -> UUID:
    """Create a canonical Invoice row from the ParseResult header.

    Args:
        db: Async database session.
        parse_result: The parsed document output.
        vendor_id: Resolved vendor UUID.
        tenant_id: Tenant UUID.

    Returns:
        UUID of the created invoice.
    """
    header = parse_result.header

    # Ensure we have a document_number; fall back to empty string if missing
    invoice_no = header.document_number or ""

    # Ensure we have a date; fall back to today if missing
    invoice_date = header.document_date or date.today()

    # Ensure we have a total; fall back to 0 if missing
    total_amount = header.total_amount if header.total_amount is not None else Decimal("0")

    # Currency falls back to INR (server default)
    currency = header.currency or "INR"

    invoice = Invoice(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        total_amount=total_amount,
        currency=currency,
        source_document_id=parse_result.document_id,
    )
    db.add(invoice)
    await db.flush()  # populate invoice.id

    return invoice.id


async def _create_line_items(
    db: AsyncSession,
    parse_result: ParseResult,
    invoice_id: UUID,
    tenant_id: UUID,
    item_normalizer: ItemNormalizer,
) -> int:
    """Create canonical InvoiceLineItem rows from ParseResult line items.

    Each line item's description is normalized using the tenant's
    abbreviation dictionary before storage.

    Args:
        db: Async database session.
        parse_result: The parsed document output.
        invoice_id: Created invoice UUID.
        tenant_id: Tenant UUID.
        item_normalizer: Initialized ItemNormalizer for this tenant.

    Returns:
        Number of line items created.
    """
    created_count = 0

    for item in parse_result.line_items:
        raw_desc = item.item_desc or ""
        normalized_desc = item_normalizer.normalize_item_desc(raw_desc)

        # Safe decimal conversion with fallbacks
        quantity = _safe_decimal(item.quantity, Decimal("0"))
        unit_price = _safe_decimal(item.unit_price, Decimal("0"))
        line_total = _safe_decimal(item.line_total, quantity * unit_price)

        unit = item.unit or ""

        line_item = InvoiceLineItem(
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            item_desc=normalized_desc,
            raw_item_desc=raw_desc,
            quantity=quantity,
            unit=unit,
            unit_price=unit_price,
            line_total=line_total,
        )
        db.add(line_item)
        created_count += 1

    await db.flush()
    return created_count


def _safe_decimal(value: Optional[Decimal], default: Decimal) -> Decimal:
    """Safely convert a value to Decimal, returning a default on failure.

    Args:
        value: The value to convert.
        default: Fallback value if conversion fails.

    Returns:
        Decimal value.
    """
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
