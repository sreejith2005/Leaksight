"""
LeakSight V1 — Rule 2: Duplicate Invoice

Source: docs/RULES_ENGINE.md (Section 4)

Detects exact and near-duplicate invoices. Operates at the INVOICE HEADER
level, not per line item. Called once per invoice in the analysis run.

Leakage type: DUPLICATE_INVOICE.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.invoices import Invoice, InvoiceLineItem
from backend.app.models.tenant import TenantSettings
from backend.app.rules.rule1_price_mismatch import RuleResult


def _invoice_sort_key(invoice) -> tuple:
    created_at = getattr(invoice, "created_at", None)
    if not isinstance(created_at, datetime):
        created_at = datetime.min
    invoice_no = getattr(invoice, "invoice_no", "") or ""
    invoice_id = str(getattr(invoice, "id", ""))
    return (created_at, invoice_no, invoice_id)


def _prior_candidates(candidates: list, invoice) -> list:
    current_key = _invoice_sort_key(invoice)
    prior = [candidate for candidate in candidates if _invoice_sort_key(candidate) < current_key]
    prior.sort(key=_invoice_sort_key)
    return prior


async def _get_duplicate_window_days(tenant_id: UUID, db: AsyncSession) -> int:
    """Load the tenant's duplicate window or fall back to default 30."""
    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    return int(settings.duplicate_window_days) if settings else 30


async def evaluate(
    invoice,
    vendor_name: str,
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
) -> List[RuleResult]:
    """Evaluate Rule 2 for a single invoice.

    Returns a list of RuleResult for each duplicate found (may be empty).
    Checks exact duplicates first, then near-duplicates.
    """
    results: List[RuleResult] = []

    # ── Step 1: Exact Duplicates ───────────────────────────────────────
    exact_stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_no == invoice.invoice_no,
            Invoice.vendor_id == invoice.vendor_id,
            Invoice.id != invoice.id,
        )
        .order_by(Invoice.created_at.asc(), Invoice.invoice_no.asc(), Invoice.id.asc())
    )
    exact_result = await db.execute(exact_stmt)
    exact_dupes = _prior_candidates(list(exact_result.scalars().all()), invoice)

    if exact_dupes:
        dupe = exact_dupes[0]
        temporal_distance = abs((invoice.invoice_date - dupe.invoice_date).days)
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} for "
            f"\u20b9{invoice.total_amount} appears to be an exact "
            f"duplicate of a previously uploaded invoice (same invoice "
            f"number, same vendor). Total duplicate amount: "
            f"\u20b9{invoice.total_amount}."
        )
        evidence = {
            "duplicate_reference": {
                "original_invoice_id": str(dupe.id),
                "original_invoice_no": dupe.invoice_no,
                "duplicate_type": "EXACT",
                "temporal_distance_days": temporal_distance,
            },
            "invoice_reference": {
                "invoice_id": str(invoice.id),
                "invoice_no": invoice.invoice_no,
                "vendor_id": str(invoice.vendor_id),
                "total_amount": str(invoice.total_amount),
                "invoice_date": str(invoice.invoice_date),
                "currency": invoice.currency,
            },
        }
        results.append(
            RuleResult(
                leakage_type="DUPLICATE_INVOICE",
                amount=Decimal(str(invoice.total_amount)),
                currency=invoice.currency,
                confidence=1.0,
                evidence_jsonb=evidence,
                rule_applied="RULE_2_DUPLICATE_INVOICE",
                explanation=explanation,
                status="PENDING",
                invoice_id=invoice.id,
            )
        )

    # If exact duplicates found, don't also check near-duplicates
    if results:
        return results

    # ── Step 2: Near Duplicates ────────────────────────────────────────
    window_days = await _get_duplicate_window_days(tenant_id, db)
    date_start = invoice.invoice_date - timedelta(days=window_days)
    date_end = invoice.invoice_date + timedelta(days=window_days)

    near_stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.vendor_id == invoice.vendor_id,
            Invoice.total_amount == invoice.total_amount,
            Invoice.invoice_date >= date_start,
            Invoice.invoice_date <= date_end,
            Invoice.invoice_no != invoice.invoice_no,
        )
        .order_by(Invoice.created_at.asc(), Invoice.invoice_no.asc(), Invoice.id.asc())
    )
    near_result = await db.execute(near_stmt)
    near_dupes = _prior_candidates(list(near_result.scalars().all()), invoice)

    # ── Step 2b: Filter near-duplicates by matching item descriptions ──
    # Only consider a near-duplicate valid if at least one line item
    # description matches between the two invoices. This prevents
    # false positives from same-vendor, same-amount invoices for
    # completely different items.
    if near_dupes:
        # Load line items for the current invoice
        src_li_stmt = select(InvoiceLineItem.item_desc).where(
            InvoiceLineItem.invoice_id == invoice.id,
        )
        src_li_result = await db.execute(src_li_stmt)
        src_item_descs = set(row[0] for row in src_li_result.fetchall())

        filtered_dupes = []
        for dupe in near_dupes:
            dupe_li_stmt = select(InvoiceLineItem.item_desc).where(
                InvoiceLineItem.invoice_id == dupe.id,
            )
            dupe_li_result = await db.execute(dupe_li_stmt)
            dupe_item_descs = set(row[0] for row in dupe_li_result.fetchall())

            # At least one common normalized item_desc required
            if src_item_descs & dupe_item_descs:
                filtered_dupes.append(dupe)

        near_dupes = filtered_dupes

    if near_dupes:
        dupe = near_dupes[0]
        temporal_distance = abs((invoice.invoice_date - dupe.invoice_date).days)
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} for "
            f"\u20b9{invoice.total_amount} dated {invoice.invoice_date} "
            f"may be a duplicate of Invoice {dupe.invoice_no} for "
            f"\u20b9{dupe.total_amount} dated {dupe.invoice_date} "
            f"({temporal_distance} days apart). Same vendor, same amount, "
            f"within the {window_days}-day duplicate detection window."
        )
        evidence = {
            "duplicate_reference": {
                "original_invoice_id": str(dupe.id),
                "original_invoice_no": dupe.invoice_no,
                "duplicate_type": "NEAR_DUPLICATE",
                "temporal_distance_days": temporal_distance,
            },
            "invoice_reference": {
                "invoice_id": str(invoice.id),
                "invoice_no": invoice.invoice_no,
                "vendor_id": str(invoice.vendor_id),
                "total_amount": str(invoice.total_amount),
                "invoice_date": str(invoice.invoice_date),
                "currency": invoice.currency,
            },
        }
        results.append(
            RuleResult(
                leakage_type="DUPLICATE_INVOICE",
                amount=Decimal(str(invoice.total_amount)),
                currency=invoice.currency,
                confidence=0.85,
                evidence_jsonb=evidence,
                rule_applied="RULE_2_DUPLICATE_INVOICE",
                explanation=explanation,
                status="PENDING",
                invoice_id=invoice.id,
            )
        )

    return results
