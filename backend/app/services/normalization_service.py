"""
LeakSight V1 - Normalization Service (FIXED for batch format + CONTRACT support)

Handles two paths:
1. Batch format (detected via raw_extracted_data["batch_rows"]):
   - INVOICE batch: groups by invoice_no, creates one Invoice per group
   - CONTRACT batch: groups by contract_id, creates Contract+ContractVersion+ContractLineItems
2. Single-document format (original path): unchanged
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.matching.item_normalizer import ItemNormalizer, create_item_normalizer
from backend.app.matching.vendor_matcher import MatchMethod, VendorMatchResult, match_vendor
from backend.app.matching.vendor_normalizer import normalize_vendor_name
from backend.app.models.contracts import Contract, ContractVersion, ContractLineItem
from backend.app.models.invoices import Invoice, InvoiceLineItem
from backend.app.models.purchase_orders import PurchaseOrder, PoLineItem
from backend.app.models.vendors import Vendor
from backend.app.parsers.base_parser import DocType, ParseResult

logger = get_logger(__name__)


@dataclass
class NormalizationResult:
    document_id: UUID
    vendor_id: Optional[UUID] = None
    vendor_match_method: Optional[str] = None
    vendor_match_confidence: float = 0.0
    invoice_id: Optional[UUID] = None
    line_items_created: int = 0
    contracts_created: int = 0
    skipped: bool = False
    skip_reason: Optional[str] = None


async def normalize_parse_result(
    db: AsyncSession,
    parse_result: ParseResult,
    tenant_id: UUID,
) -> NormalizationResult:
    doc_id = parse_result.document_id

    # Guard: skip on total failure
    if parse_result.parse_confidence == 0.0:
        logger.info("normalization_skipped", document_id=str(doc_id), reason="total_parse_failure")
        return NormalizationResult(document_id=doc_id, skipped=True, skip_reason="total_parse_failure")

    await _delete_existing_canonical_for_document(
        db=db,
        tenant_id=tenant_id,
        document_id=doc_id,
        doc_type=parse_result.doc_type,
    )

    # ── BATCH FORMAT PATH ─────────────────────────────────────────────
    raw_data = parse_result.raw_extracted_data or {}
    if "batch_rows" in raw_data:
        batch_rows = raw_data["batch_rows"]
        batch_type = raw_data.get("batch_type", "INVOICE")

        if not batch_rows:
            return NormalizationResult(document_id=doc_id, skipped=True, skip_reason="empty_batch")

        item_normalizer = await create_item_normalizer(tenant_id=tenant_id, db=db)

        if batch_type == "CONTRACT":
            contracts_created, line_items_created = await _process_contract_batch(
                db=db,
                batch_rows=batch_rows,
                tenant_id=tenant_id,
                item_normalizer=item_normalizer,
                document_id=doc_id,
            )
            logger.info(
                "batch_contract_normalization_complete",
                document_id=str(doc_id),
                contracts_created=contracts_created,
                line_items_created=line_items_created,
            )
            return NormalizationResult(
                document_id=doc_id,
                contracts_created=contracts_created,
                line_items_created=line_items_created,
            )
        elif batch_type == "PO":
            pos_created, line_items_created = await _process_po_batch(
                db=db,
                batch_rows=batch_rows,
                tenant_id=tenant_id,
                item_normalizer=item_normalizer,
                document_id=doc_id,
            )
            logger.info(
                "batch_po_normalization_complete",
                document_id=str(doc_id),
                pos_created=pos_created,
                line_items_created=line_items_created,
            )
            return NormalizationResult(
                document_id=doc_id,
                contracts_created=0,
                line_items_created=line_items_created,
            )
        else:
            invoices_created, line_items_created = await _process_invoice_batch(
                db=db,
                batch_rows=batch_rows,
                tenant_id=tenant_id,
                item_normalizer=item_normalizer,
                document_id=doc_id,
            )
            logger.info(
                "batch_invoice_normalization_complete",
                document_id=str(doc_id),
                invoices_created=invoices_created,
                line_items_created=line_items_created,
            )
            return NormalizationResult(
                document_id=doc_id,
                line_items_created=line_items_created,
            )

    # ── SINGLE-DOCUMENT FORMAT PATH (original) ────────────────────────
    raw_vendor_name = parse_result.header.vendor_name
    if not raw_vendor_name or not raw_vendor_name.strip():
        logger.warning("normalization_skipped", document_id=str(doc_id), reason="missing_vendor_name")
        return NormalizationResult(document_id=doc_id, skipped=True, skip_reason="missing_vendor_name")

    gst_id = parse_result.header.vendor_gst_id
    vendor_result: VendorMatchResult = await match_vendor(
        raw_name=raw_vendor_name, gst_id=gst_id, tenant_id=tenant_id, db=db,
    )

    vendor_id = vendor_result.matched_vendor_id
    match_method = vendor_result.match_method.value

    if vendor_result.match_method == MatchMethod.NO_MATCH:
        vendor_id = await _auto_create_vendor(db=db, raw_name=raw_vendor_name, gst_id=gst_id, tenant_id=tenant_id)
        match_method = "AUTO_CREATED"
    else:
        await _update_vendor_raw_names(db=db, vendor_id=vendor_id, raw_name=raw_vendor_name)

    invoice_id: Optional[UUID] = None
    line_items_created = 0

    if parse_result.doc_type == DocType.INVOICE:
        invoice_id = await _create_invoice(db=db, parse_result=parse_result, vendor_id=vendor_id, tenant_id=tenant_id)
        item_normalizer = await create_item_normalizer(tenant_id=tenant_id, db=db)
        line_items_created = await _create_line_items(
            db=db, parse_result=parse_result, invoice_id=invoice_id,
            tenant_id=tenant_id, item_normalizer=item_normalizer,
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


async def _delete_existing_canonical_for_document(
    db: AsyncSession,
    tenant_id: UUID,
    document_id: UUID,
    doc_type: DocType,
) -> None:
    """Remove canonical rows tied to this document before rebuilding them.

    Normalization can be retried for the same raw parse or re-triggered after a
    repair. Without a document-scoped cleanup, contract and PO records are
    duplicated and later analysis runs mix stale canonical rows into the run.
    """
    if doc_type == DocType.CONTRACT:
        contract_ids = (
            select(Contract.id)
            .where(
                Contract.tenant_id == tenant_id,
                Contract.source_document_id == document_id,
            )
            .scalar_subquery()
        )
        version_ids = (
            select(ContractVersion.id)
            .where(
                ContractVersion.tenant_id == tenant_id,
                ContractVersion.contract_id.in_(contract_ids),
            )
            .scalar_subquery()
        )
        await db.execute(
            delete(ContractLineItem).where(
                ContractLineItem.tenant_id == tenant_id,
                ContractLineItem.contract_version_id.in_(version_ids),
            )
        )
        await db.execute(
            delete(ContractVersion).where(
                ContractVersion.tenant_id == tenant_id,
                ContractVersion.contract_id.in_(contract_ids),
            )
        )
        await db.execute(
            delete(Contract).where(
                Contract.tenant_id == tenant_id,
                Contract.source_document_id == document_id,
            )
        )
        return

    if doc_type == DocType.PO:
        po_ids = (
            select(PurchaseOrder.id)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.source_document_id == document_id,
            )
            .scalar_subquery()
        )
        await db.execute(
            delete(PoLineItem).where(
                PoLineItem.tenant_id == tenant_id,
                PoLineItem.po_id.in_(po_ids),
            )
        )
        await db.execute(
            delete(PurchaseOrder).where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.source_document_id == document_id,
            )
        )
        return

    if doc_type == DocType.INVOICE:
        invoice_ids = (
            select(Invoice.id)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.source_document_id == document_id,
            )
            .scalar_subquery()
        )
        await db.execute(
            delete(InvoiceLineItem).where(
                InvoiceLineItem.tenant_id == tenant_id,
                InvoiceLineItem.invoice_id.in_(invoice_ids),
            )
        )
        await db.execute(
            delete(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.source_document_id == document_id,
            )
        )


# ── BATCH INVOICE PROCESSING ──────────────────────────────────────────

async def _process_invoice_batch(
    db: AsyncSession,
    batch_rows: list[dict],
    tenant_id: UUID,
    item_normalizer: ItemNormalizer,
    document_id: UUID,
) -> tuple[int, int]:
    """
    Group batch rows by invoice_no, create one Invoice + line items per group.
    Returns (invoices_created, total_line_items_created).
    """
    # Group rows by invoice_no (use row index as fallback key)
    groups: dict[str, list[dict]] = defaultdict(list)
    for i, row in enumerate(batch_rows):
        key = row.get("invoice_no") or f"__row_{i}"
        groups[key].append(row)

    invoices_created = 0
    total_line_items = 0

    # Cache vendor lookups to avoid repeated DB queries
    vendor_cache: dict[str, UUID] = {}

    for inv_no, rows in groups.items():
        first_row = rows[0]
        raw_vendor = first_row.get("vendor_name") or ""

        if not raw_vendor.strip():
            logger.warning("batch_invoice_skip_no_vendor", invoice_no=inv_no)
            continue

        # Resolve vendor (with cache)
        vendor_id = await _resolve_or_create_vendor(
            db=db, raw_name=raw_vendor, tenant_id=tenant_id, cache=vendor_cache
        )

        # Parse date
        inv_date = None
        if first_row.get("invoice_date"):
            try:
                from datetime import date as dt_date
                inv_date = dt_date.fromisoformat(first_row["invoice_date"])
            except (ValueError, TypeError):
                pass
        if inv_date is None:
            inv_date = date.today()

        currency = first_row.get("currency") or "INR"

        # Calculate total from line items
        total = sum(
            Decimal(str(r["unit_price"])) * Decimal(str(r["quantity"]))
            for r in rows
            if r.get("unit_price") is not None and r.get("quantity") is not None
        )

        stored_invoice_no = inv_no if not inv_no.startswith("__row_") else ""

        # Idempotency: if invoice_no already exists for this tenant,
        # refresh it instead of failing on unique constraint.
        existing_invoice = None
        if stored_invoice_no:
            existing_stmt = select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.invoice_no == stored_invoice_no,
            )
            existing_result = await db.execute(existing_stmt)
            existing_invoice = existing_result.scalar_one_or_none()

        if existing_invoice is not None:
            invoice = existing_invoice
            # Keep existing invoice/line-item history intact; only relink
            # source document so analysis_run can include this invoice.
            invoice.source_document_id = document_id
            await db.flush()

            existing_li_stmt = select(func.count()).select_from(InvoiceLineItem).where(
                InvoiceLineItem.invoice_id == invoice.id,
                InvoiceLineItem.tenant_id == tenant_id,
            )
            existing_li_count = (await db.execute(existing_li_stmt)).scalar() or 0

            # If line items already exist, keep them and avoid duplicates.
            if existing_li_count > 0:
                invoices_created += 1
                continue
        else:
            invoice = Invoice(
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                invoice_no=stored_invoice_no,
                invoice_date=inv_date,
                total_amount=total,
                currency=currency,
                source_document_id=document_id,
            )
            db.add(invoice)
            await db.flush()

        # Create line items
        for row in rows:
            raw_desc = row.get("item_desc") or ""
            norm_desc = item_normalizer.normalize_item_desc(raw_desc)
            qty = Decimal(str(row["quantity"])) if row.get("quantity") is not None else Decimal("0")
            price = Decimal(str(row["unit_price"])) if row.get("unit_price") is not None else Decimal("0")

            line_item = InvoiceLineItem(
                invoice_id=invoice.id,
                tenant_id=tenant_id,
                item_desc=norm_desc,
                raw_item_desc=raw_desc,
                contract_ref=(row.get("contract_id") or None),
                quantity=qty,
                unit=row.get("unit") or "",
                unit_price=price,
                line_total=qty * price,
            )
            db.add(line_item)
            total_line_items += 1

        await db.flush()
        invoices_created += 1

    return invoices_created, total_line_items


# ── BATCH CONTRACT PROCESSING ─────────────────────────────────────────

async def _process_contract_batch(
    db: AsyncSession,
    batch_rows: list[dict],
    tenant_id: UUID,
    item_normalizer: ItemNormalizer,
    document_id: UUID,
) -> tuple[int, int]:
    """
    Group batch rows by contract_id, create Contract+ContractVersion+ContractLineItems.
    Returns (contracts_created, total_line_items_created).
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in batch_rows:
        key = row.get("contract_id") or row.get("item_desc") or "unknown"
        groups[key].append(row)

    contracts_created = 0
    total_line_items = 0
    vendor_cache: dict[str, UUID] = {}

    for contract_ref, rows in groups.items():
        first_row = rows[0]
        raw_vendor = first_row.get("vendor_name") or ""

        if not raw_vendor.strip():
            logger.warning("batch_contract_skip_no_vendor", contract_ref=contract_ref)
            continue

        vendor_id = await _resolve_or_create_vendor(
            db=db, raw_name=raw_vendor, tenant_id=tenant_id, cache=vendor_cache
        )

        # Parse dates
        valid_from = None
        valid_to = None
        if first_row.get("effective_start_date"):
            try:
                valid_from = date.fromisoformat(first_row["effective_start_date"])
            except (ValueError, TypeError):
                pass
        if first_row.get("effective_end_date"):
            try:
                valid_to = date.fromisoformat(first_row["effective_end_date"])
            except (ValueError, TypeError):
                pass

        if valid_from is None:
            valid_from = date.today()
        if valid_to is None:
            from datetime import timedelta
            valid_to = valid_from.replace(year=valid_from.year + 1)

        version_number = 1
        try:
            version_number = int(first_row.get("version_number") or 1)
        except (ValueError, TypeError):
            pass

        # Create Contract
        contract = Contract(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            contract_ref=contract_ref,
            source_document_id=document_id,
        )
        db.add(contract)
        await db.flush()

        # Create ContractVersion
        version = ContractVersion(
            contract_id=contract.id,
            tenant_id=tenant_id,
            version_number=version_number,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        db.add(version)
        await db.flush()

        # Create ContractLineItems
        for row in rows:
            raw_desc = row.get("item_desc") or ""
            norm_desc = item_normalizer.normalize_item_desc(raw_desc)
            price = Decimal(str(row["unit_price"])) if row.get("unit_price") is not None else Decimal("0")
            currency = row.get("currency") or "INR"

            line_item = ContractLineItem(
                contract_version_id=version.id,
                tenant_id=tenant_id,
                item_desc=norm_desc,
                raw_item_desc=raw_desc,
                contract_quantity=(
                    Decimal(str(row["quantity"]))
                    if row.get("quantity") is not None else None
                ),
                unit=row.get("unit") or "",
                unit_price=price,
                currency=currency,
            )
            db.add(line_item)
            total_line_items += 1

        await db.flush()
        contracts_created += 1

    return contracts_created, total_line_items


# ── BATCH PO PROCESSING ───────────────────────────────────────────────

async def _process_po_batch(
    db: AsyncSession,
    batch_rows: list[dict],
    tenant_id: UUID,
    item_normalizer: ItemNormalizer,
    document_id: UUID,
) -> tuple[int, int]:
    """
    Group batch rows by po_no, create one PurchaseOrder + PoLineItems per group.
    Returns (pos_created, total_line_items_created).
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for i, row in enumerate(batch_rows):
        key = row.get("po_no") or f"__row_{i}"
        groups[key].append(row)

    pos_created = 0
    total_line_items = 0
    vendor_cache: dict[str, UUID] = {}

    for po_no, rows in groups.items():
        first_row = rows[0]
        raw_vendor = first_row.get("vendor_name") or ""

        if not raw_vendor.strip():
            logger.warning("batch_po_skip_no_vendor", po_no=po_no)
            continue

        vendor_id = await _resolve_or_create_vendor(
            db=db, raw_name=raw_vendor, tenant_id=tenant_id, cache=vendor_cache
        )

        # Parse PO date
        po_date = None
        if first_row.get("po_date"):
            try:
                po_date = date.fromisoformat(first_row["po_date"])
            except (ValueError, TypeError):
                pass
        if po_date is None:
            po_date = date.today()

        po = PurchaseOrder(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            po_no=po_no if not po_no.startswith("__row_") else "",
            po_date=po_date,
            source_document_id=document_id,
        )
        db.add(po)
        await db.flush()

        for row in rows:
            raw_desc = row.get("item_desc") or ""
            norm_desc = item_normalizer.normalize_item_desc(raw_desc)
            ordered_qty = Decimal(str(row["ordered_qty"])) if row.get("ordered_qty") is not None else (
                Decimal(str(row["quantity"])) if row.get("quantity") is not None else Decimal("0")
            )
            price = Decimal(str(row["unit_price"])) if row.get("unit_price") is not None else Decimal("0")

            po_line = PoLineItem(
                po_id=po.id,
                tenant_id=tenant_id,
                item_desc=norm_desc,
                raw_item_desc=raw_desc,
                unit=row.get("unit") or "",
                ordered_qty=ordered_qty,
                unit_price=price,
            )
            db.add(po_line)
            total_line_items += 1

        await db.flush()
        pos_created += 1

    return pos_created, total_line_items


# ── SHARED HELPERS ────────────────────────────────────────────────────

async def _resolve_or_create_vendor(
    db: AsyncSession,
    raw_name: str,
    tenant_id: UUID,
    cache: dict[str, UUID],
) -> UUID:
    """Resolve vendor by name with an in-memory cache to avoid redundant DB queries."""
    cache_key = raw_name.strip().lower()
    if cache_key in cache:
        return cache[cache_key]

    result: VendorMatchResult = await match_vendor(
        raw_name=raw_name, gst_id=None, tenant_id=tenant_id, db=db,
    )

    if result.match_method == MatchMethod.NO_MATCH:
        vendor_id = await _auto_create_vendor(
            db=db, raw_name=raw_name, gst_id=None, tenant_id=tenant_id
        )
    else:
        vendor_id = result.matched_vendor_id
        await _update_vendor_raw_names(db=db, vendor_id=vendor_id, raw_name=raw_name)

    cache[cache_key] = vendor_id
    return vendor_id


async def _auto_create_vendor(
    db: AsyncSession, raw_name: str, gst_id: Optional[str], tenant_id: UUID,
) -> UUID:
    normalized = normalize_vendor_name(raw_name)
    vendor = Vendor(
        tenant_id=tenant_id,
        normalized_name=normalized,
        raw_names_jsonb=[raw_name],
        gst_id=gst_id,
    )
    db.add(vendor)
    await db.flush()
    return vendor.id


async def _update_vendor_raw_names(
    db: AsyncSession, vendor_id: UUID, raw_name: str,
) -> None:
    result = await db.execute(select(Vendor.raw_names_jsonb).where(Vendor.id == vendor_id))
    current_names = result.scalar_one_or_none() or []
    if raw_name not in current_names:
        await db.execute(
            update(Vendor).where(Vendor.id == vendor_id).values(raw_names_jsonb=current_names + [raw_name])
        )


async def _create_invoice(
    db: AsyncSession, parse_result: ParseResult, vendor_id: UUID, tenant_id: UUID,
) -> UUID:
    header = parse_result.header
    invoice = Invoice(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        invoice_no=header.document_number or "",
        invoice_date=header.document_date or date.today(),
        total_amount=header.total_amount if header.total_amount is not None else Decimal("0"),
        currency=header.currency or "INR",
        source_document_id=parse_result.document_id,
    )
    db.add(invoice)
    await db.flush()
    return invoice.id


async def _create_line_items(
    db: AsyncSession,
    parse_result: ParseResult,
    invoice_id: UUID,
    tenant_id: UUID,
    item_normalizer: ItemNormalizer,
) -> int:
    created_count = 0
    for item in parse_result.line_items:
        raw_desc = item.item_desc or ""
        normalized_desc = item_normalizer.normalize_item_desc(raw_desc)
        quantity = _safe_decimal(item.quantity, Decimal("0"))
        unit_price = _safe_decimal(item.unit_price, Decimal("0"))
        line_total = _safe_decimal(item.line_total, quantity * unit_price)

        line_item = InvoiceLineItem(
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            item_desc=normalized_desc,
            raw_item_desc=raw_desc,
            quantity=quantity,
            unit=item.unit or "",
            unit_price=unit_price,
            line_total=line_total,
        )
        db.add(line_item)
        created_count += 1

    await db.flush()
    return created_count


def _safe_decimal(value: Optional[Decimal], default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
