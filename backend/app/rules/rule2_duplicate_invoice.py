"""
LeakSight V1 — Rule 2: Duplicate Invoice

Source: docs/RULES_ENGINE.md (Section 4)

Detects exact and near-duplicate invoices. Operates at the INVOICE HEADER
level, not per line item. Called once per invoice in the analysis run.

Leakage type: DUPLICATE_INVOICE.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.invoices import Invoice
from backend.app.models.tenant import TenantSettings
from backend.app.rules.rule1_price_mismatch import RuleResult


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
    )
    exact_result = await db.execute(exact_stmt)
    exact_dupes = list(exact_result.scalars().all())

    for dupe in exact_dupes:
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
            Invoice.id != invoice.id,
            Invoice.invoice_no != invoice.invoice_no,
        )
    )
    near_result = await db.execute(near_stmt)
    near_dupes = list(near_result.scalars().all())

    for dupe in near_dupes:
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
