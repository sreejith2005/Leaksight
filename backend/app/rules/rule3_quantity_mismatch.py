"""
LeakSight V1 — Rule 3: Quantity Mismatch

Source: docs/RULES_ENGINE.md (Section 5)

Detects when an invoice claims a higher quantity than what was actually
received (GRN) or ordered (PO). Authority hierarchy: GRN > PO > Nothing.

Leakage type: QUANTITY_MISMATCH.
"""

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from rapidfuzz.fuzz import token_sort_ratio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.grns import Grn, GrnLineItem
from backend.app.models.invoices import Invoice
from backend.app.models.purchase_orders import PurchaseOrder, PoLineItem
from backend.app.models.tenant import TenantSettings
from backend.app.rules.rule1_price_mismatch import RuleResult


async def _get_fuzzy_threshold(tenant_id: UUID, db: AsyncSession) -> float:
    """Load the tenant's fuzzy threshold or fall back to default 0.85."""
    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    return float(settings.fuzzy_threshold) if settings else 0.85


def _best_item_match(
    target_desc: str,
    candidates: list,
    desc_attr: str,
    fuzzy_threshold: float,
) -> tuple:
    """Find the best matching item from candidates by description.

    Returns (matched_item, confidence, method) or (None, 0.0, "NONE").
    """
    # Exact match first
    for item in candidates:
        if getattr(item, desc_attr) == target_desc:
            return item, 1.0, "EXACT"

    # Fuzzy match
    best = None
    best_score = 0.0
    for item in candidates:
        score = token_sort_ratio(target_desc, getattr(item, desc_attr)) / 100.0
        if score >= fuzzy_threshold and score > best_score:
            best = item
            best_score = score

    if best:
        return best, best_score, "FUZZY"

    return None, 0.0, "NONE"


async def evaluate(
    invoice_line_item,
    invoice,
    vendor_name: str,
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
) -> Optional[RuleResult]:
    """Evaluate Rule 3 for a single invoice line item.

    Returns a RuleResult if quantity leakage detected, None if clean/skipped.

    Edge cases:
    - Zero quantity → skip
    - Negative amount → skip
    - No GRN and no PO → skip (no false positive)
    """
    # Edge cases
    if invoice_line_item.quantity <= 0 or invoice_line_item.unit_price < 0:
        return None

    fuzzy_threshold = await _get_fuzzy_threshold(tenant_id, db)

    # ── Step 1: Find matching GRN ──────────────────────────────────────
    # GRNs are linked to POs from the same vendor:
    #   grns.po_id → purchase_orders.vendor_id = invoice.vendor_id
    grn_line_item = None
    grn_header = None
    grn_confidence = 0.0
    grn_method = "NONE"

    # Find POs for this vendor
    po_stmt = select(PurchaseOrder).where(
        PurchaseOrder.vendor_id == invoice.vendor_id,
        PurchaseOrder.tenant_id == tenant_id,
    ).order_by(PurchaseOrder.id.asc())
    po_result = await db.execute(po_stmt)
    vendor_pos = list(po_result.scalars().all())

    if vendor_pos:
        po_ids = [po.id for po in vendor_pos]

        # Find GRNs linked to those POs
        grn_stmt = select(Grn).where(
            Grn.po_id.in_(po_ids),
            Grn.tenant_id == tenant_id,
        )
        grn_result = await db.execute(grn_stmt)
        grns = list(grn_result.scalars().all())

        if grns:
            grn_ids = [g.id for g in grns]

            # Find GRN line items
            gli_stmt = select(GrnLineItem).where(
                GrnLineItem.grn_id.in_(grn_ids),
                GrnLineItem.tenant_id == tenant_id,
            ).order_by(GrnLineItem.id.asc())
            gli_result = await db.execute(gli_stmt)
            grn_line_items = list(gli_result.scalars().all())

            if grn_line_items:
                matched, conf, method = _best_item_match(
                    invoice_line_item.item_desc,
                    grn_line_items,
                    "item_desc",
                    fuzzy_threshold,
                )
                if matched:
                    grn_line_item = matched
                    grn_confidence = conf
                    grn_method = method
                    # Find the parent GRN header for reporting
                    for g in grns:
                        if g.id == matched.grn_id:
                            grn_header = g
                            break

    # ── Step 2: Determine authority ────────────────────────────────────
    po_line_item = None
    po_header = None
    po_confidence = 0.0
    po_method = "NONE"

    if grn_line_item is None and vendor_pos:
        # No GRN match — try PO fallback
        po_ids = [po.id for po in vendor_pos]
        pli_stmt = select(PoLineItem).where(
            PoLineItem.po_id.in_(po_ids),
            PoLineItem.tenant_id == tenant_id,
        ).order_by(PoLineItem.id.asc())
        pli_result = await db.execute(pli_stmt)
        po_line_items = list(pli_result.scalars().all())

        if po_line_items:
            matched, conf, method = _best_item_match(
                invoice_line_item.item_desc,
                po_line_items,
                "item_desc",
                fuzzy_threshold,
            )
            if matched:
                po_line_item = matched
                po_confidence = conf
                po_method = method
                for po in vendor_pos:
                    if po.id == matched.po_id:
                        po_header = po
                        break

    # No GRN and no PO match → skip
    if grn_line_item is None and po_line_item is None:
        return None

    # ── Step 3: Quantity comparison ────────────────────────────────────
    invoice_qty = Decimal(str(invoice_line_item.quantity))
    unit_price = Decimal(str(invoice_line_item.unit_price))

    if grn_line_item is not None:
        # GRN authority
        authority_qty = Decimal(str(grn_line_item.received_qty))
        authority_used = "GRN"
        item_confidence = grn_confidence
        item_method = grn_method
    else:
        # PO fallback
        authority_qty = Decimal(str(po_line_item.ordered_qty))
        authority_used = "PO"
        item_confidence = po_confidence
        item_method = po_method

    quantity_difference = invoice_qty - authority_qty

    if quantity_difference <= 0:
        return None  # Invoice qty at or below authority qty — clean

    # ── Step 4: Leakage amount ─────────────────────────────────────────
    leakage_amount = quantity_difference * unit_price

    # ── Step 5: Confidence ─────────────────────────────────────────────
    if authority_used == "GRN":
        if item_method == "EXACT":
            confidence = 1.0
        else:
            confidence = item_confidence
    else:  # PO
        if item_method == "EXACT":
            confidence = 0.90
        else:
            confidence = min(0.90, item_confidence)

    # ── Step 6: Evidence ───────────────────────────────────────────────
    evidence = {
        "quantity_reference": {
            "po_id": str(po_header.id) if po_header else None,
            "po_quantity": str(po_line_item.ordered_qty) if po_line_item else None,
            "grn_id": str(grn_header.id) if grn_header else None,
            "grn_quantity": str(grn_line_item.received_qty) if grn_line_item else None,
            "invoiced_quantity": str(invoice_qty),
            "authority_used": authority_used,
            "quantity_difference": str(quantity_difference),
        },
        "invoice_reference": {
            "invoice_id": str(invoice.id),
            "invoice_no": invoice.invoice_no,
            "line_item_id": str(invoice_line_item.id),
            "item_desc": invoice_line_item.item_desc,
            "quantity": str(invoice_qty),
            "unit": invoice_line_item.unit,
            "unit_price": str(unit_price),
        },
        "calculation": {
            "quantity_difference": str(quantity_difference),
            "unit_price": str(unit_price),
            "leakage_amount": str(leakage_amount),
        },
        "match_confidence_breakdown": {
            "item_match_method": item_method,
            "item_match_confidence": item_confidence,
            "authority_used": authority_used,
            "overall_confidence": confidence,
        },
    }

    # ── Step 7: Explanation ────────────────────────────────────────────
    if authority_used == "GRN":
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} claims "
            f"{invoice_qty} {invoice_line_item.unit} of "
            f"'{invoice_line_item.item_desc}' but the GRN "
            f"(received on {grn_header.grn_date}) records only "
            f"{authority_qty} {invoice_line_item.unit} received. "
            f"Over-invoiced by {quantity_difference} "
            f"{invoice_line_item.unit} \u00d7 "
            f"\u20b9{unit_price} = \u20b9{leakage_amount}."
        )
    else:
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} claims "
            f"{invoice_qty} {invoice_line_item.unit} of "
            f"'{invoice_line_item.item_desc}' but the PO "
            f"({po_header.po_no}) only authorized "
            f"{authority_qty} {invoice_line_item.unit}. "
            f"No GRN available to confirm receipt. Over-invoiced by "
            f"{quantity_difference} {invoice_line_item.unit} \u00d7 "
            f"\u20b9{unit_price} = \u20b9{leakage_amount}. "
            f"Note: PO used as authority because no GRN found."
        )

    return RuleResult(
        leakage_type="QUANTITY_MISMATCH",
        amount=leakage_amount,
        currency=invoice.currency,
        confidence=confidence,
        evidence_jsonb=evidence,
        rule_applied="RULE_3_QUANTITY_MISMATCH",
        explanation=explanation,
        status="PENDING",
        invoice_id=invoice.id,
        invoice_line_item_id=invoice_line_item.id,
    )
