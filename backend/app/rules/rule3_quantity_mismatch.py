"""
LeakSight V1 - Rule 3: Quantity Mismatch

Source: docs/RULES_ENGINE.md (Section 5)

Detects when an invoice claims a higher quantity than what was actually
received (GRN) or ordered (PO). When neither exists, the uploaded contract
quantity is used as the last fallback authority for batch workbook data.

Leakage type: QUANTITY_MISMATCH.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from rapidfuzz.fuzz import token_sort_ratio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.contract_resolver import (
    ContractResolutionStatus,
    get_valid_contract_version,
)
from backend.app.models.contracts import ContractLineItem
from backend.app.models.grns import Grn, GrnLineItem
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
    """Find the best matching item from candidates by description."""
    for item in candidates:
        if getattr(item, desc_attr) == target_desc:
            return item, 1.0, "EXACT"

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


async def _resolve_contract_authority(
    invoice_line_item,
    invoice,
    tenant_id: UUID,
    fuzzy_threshold: float,
    db: AsyncSession,
) -> tuple:
    """Resolve contract line item quantity when PO/GRN data is absent."""
    contract_ref = getattr(invoice_line_item, "contract_ref", None)
    if not isinstance(contract_ref, str) or not contract_ref.strip():
        return None, 0.0, "NONE"

    contract_result = await get_valid_contract_version(
        vendor_id=invoice.vendor_id,
        invoice_date=invoice.invoice_date,
        tenant_id=tenant_id,
        db=db,
        contract_ref=contract_ref,
    )
    if contract_result.status == ContractResolutionStatus.NONE:
        return None, 0.0, "NONE"

    contract_version = contract_result.versions[0]
    stmt = select(ContractLineItem).where(
        ContractLineItem.contract_version_id == contract_version.id,
        ContractLineItem.tenant_id == tenant_id,
    ).order_by(ContractLineItem.id.asc())
    result = await db.execute(stmt)
    contract_line_items = list(result.scalars().all())

    if not contract_line_items:
        return None, 0.0, "NONE"

    matched, confidence, method = _best_item_match(
        invoice_line_item.item_desc,
        contract_line_items,
        "item_desc",
        fuzzy_threshold,
    )
    if matched is None or matched.contract_quantity is None:
        return None, 0.0, "NONE"

    return matched, confidence, method


async def evaluate(
    invoice_line_item,
    invoice,
    vendor_name: str,
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
) -> Optional[RuleResult]:
    """Evaluate Rule 3 for a single invoice line item."""
    if invoice_line_item.quantity <= 0 or invoice_line_item.unit_price < 0:
        return None

    fuzzy_threshold = await _get_fuzzy_threshold(tenant_id, db)

    grn_line_item = None
    grn_header = None
    grn_confidence = 0.0
    grn_method = "NONE"

    po_stmt = select(PurchaseOrder).where(
        PurchaseOrder.vendor_id == invoice.vendor_id,
        PurchaseOrder.tenant_id == tenant_id,
    ).order_by(PurchaseOrder.id.asc())
    po_result = await db.execute(po_stmt)
    vendor_pos = list(po_result.scalars().all())

    if vendor_pos:
        po_ids = [po.id for po in vendor_pos]
        grn_stmt = select(Grn).where(
            Grn.po_id.in_(po_ids),
            Grn.tenant_id == tenant_id,
        )
        grn_result = await db.execute(grn_stmt)
        grns = list(grn_result.scalars().all())

        if grns:
            grn_ids = [g.id for g in grns]
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
                    for grn in grns:
                        if grn.id == matched.grn_id:
                            grn_header = grn
                            break

    po_line_item = None
    po_header = None
    po_confidence = 0.0
    po_method = "NONE"

    if grn_line_item is None and vendor_pos:
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

    contract_line_item = None
    contract_confidence = 0.0
    contract_method = "NONE"
    if grn_line_item is None and po_line_item is None:
        contract_line_item, contract_confidence, contract_method = (
            await _resolve_contract_authority(
                invoice_line_item=invoice_line_item,
                invoice=invoice,
                tenant_id=tenant_id,
                fuzzy_threshold=fuzzy_threshold,
                db=db,
            )
        )

    if grn_line_item is None and po_line_item is None and contract_line_item is None:
        return None

    invoice_qty = Decimal(str(invoice_line_item.quantity))
    unit_price = Decimal(str(invoice_line_item.unit_price))

    if grn_line_item is not None:
        authority_qty = Decimal(str(grn_line_item.received_qty))
        authority_used = "GRN"
        item_confidence = grn_confidence
        item_method = grn_method
    elif po_line_item is not None:
        authority_qty = Decimal(str(po_line_item.ordered_qty))
        authority_used = "PO"
        item_confidence = po_confidence
        item_method = po_method
    else:
        authority_qty = Decimal(str(contract_line_item.contract_quantity))
        authority_used = "CONTRACT"
        item_confidence = contract_confidence
        item_method = contract_method

    quantity_difference = invoice_qty - authority_qty
    if quantity_difference <= 0:
        return None

    leakage_amount = (quantity_difference * unit_price).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    if authority_used == "GRN":
        confidence = 1.0 if item_method == "EXACT" else item_confidence
    elif authority_used == "PO":
        confidence = 0.90 if item_method == "EXACT" else min(0.90, item_confidence)
    else:
        confidence = 0.95 if item_method == "EXACT" else min(0.95, item_confidence)

    evidence = {
        "quantity_reference": {
            "po_id": str(po_header.id) if po_header else None,
            "po_quantity": str(po_line_item.ordered_qty) if po_line_item else None,
            "grn_id": str(grn_header.id) if grn_header else None,
            "grn_quantity": str(grn_line_item.received_qty) if grn_line_item else None,
            "contract_id": getattr(invoice_line_item, "contract_ref", None),
            "contract_quantity": (
                str(contract_line_item.contract_quantity)
                if contract_line_item and contract_line_item.contract_quantity is not None else None
            ),
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

    if authority_used == "GRN":
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} claims "
            f"{invoice_qty} {invoice_line_item.unit} of "
            f"'{invoice_line_item.item_desc}' but the GRN "
            f"(received on {grn_header.grn_date}) records only "
            f"{authority_qty} {invoice_line_item.unit} received. "
            f"Over-invoiced by {quantity_difference} "
            f"{invoice_line_item.unit} x "
            f"₹{unit_price} = ₹{leakage_amount}."
        )
    elif authority_used == "PO":
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} claims "
            f"{invoice_qty} {invoice_line_item.unit} of "
            f"'{invoice_line_item.item_desc}' but the PO "
            f"({po_header.po_no}) only authorized "
            f"{authority_qty} {invoice_line_item.unit}. "
            f"No GRN available to confirm receipt. Over-invoiced by "
            f"{quantity_difference} {invoice_line_item.unit} x "
            f"₹{unit_price} = ₹{leakage_amount}. "
            f"Note: PO used as authority because no GRN found."
        )
    else:
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} claims "
            f"{invoice_qty} {invoice_line_item.unit} of "
            f"'{invoice_line_item.item_desc}' but the referenced contract "
            f"({invoice_line_item.contract_ref}) only authorizes "
            f"{authority_qty} {invoice_line_item.unit}. Over-invoiced by "
            f"{quantity_difference} {invoice_line_item.unit} x "
            f"₹{unit_price} = ₹{leakage_amount}. "
            f"Note: contract quantity used as authority because no GRN or PO matched."
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
