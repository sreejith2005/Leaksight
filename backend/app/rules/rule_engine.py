"""
LeakSight V1 — Rules Engine Orchestrator

Source: docs/RULES_ENGINE.md (Section 2 — Rule Execution Flow)
       docs/ARCHITECTURE.md (Detect stage)

Called once per invoice line item. Runs each rule in sequence:
  1. Rule 1 — Price Mismatch
  2. Rule 2 — Duplicate Invoice (invoice-level, tracked to run once)
  3. Rule 3 — Quantity Mismatch

Collects all non-None results. Rule 2 is evaluated once per invoice,
not per line item.
"""

import logging
from typing import Dict, List, Set
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.rules.rule1_price_mismatch import RuleResult
from backend.app.rules import (
    rule1_price_mismatch,
    rule2_duplicate_invoice,
    rule3_quantity_mismatch,
)

logger = logging.getLogger("leaksight.rules_engine")


async def evaluate_line_item(
    invoice_line_item,
    invoice,
    vendor_name: str,
    vendor_match_confidence: float,
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
    checked_invoice_ids: Set[UUID],
) -> List[RuleResult]:
    """Run all three rules for a single invoice line item.

    Args:
        invoice_line_item: InvoiceLineItem ORM instance.
        invoice: Invoice ORM instance (parent).
        vendor_name: Resolved vendor name for explanations.
        vendor_match_confidence: Confidence from vendor matching stage.
        tenant_id: Current tenant UUID.
        run_id: Current analysis run UUID.
        db: Async database session.
        checked_invoice_ids: Mutable set tracking which invoices have
            already been checked for duplicates (Rule 2). The caller
            passes this across all line items in a run.

    Returns:
        List of RuleResult for all leakage detected (may be empty).
    """
    results: List[RuleResult] = []

    # ── Rule 1: Price Mismatch ─────────────────────────────────────────
    try:
        r1 = await rule1_price_mismatch.evaluate(
            invoice_line_item=invoice_line_item,
            invoice=invoice,
            vendor_name=vendor_name,
            vendor_match_confidence=vendor_match_confidence,
            tenant_id=tenant_id,
            run_id=run_id,
            db=db,
        )
        if r1 is not None:
            results.append(r1)
    except Exception:
        logger.exception(
            "Rule 1 failed for invoice_line_item_id=%s",
            invoice_line_item.id,
        )

    # ── Rule 2: Duplicate Invoice (once per invoice) ───────────────────
    if invoice.id not in checked_invoice_ids:
        checked_invoice_ids.add(invoice.id)
        try:
            r2_list = await rule2_duplicate_invoice.evaluate(
                invoice=invoice,
                vendor_name=vendor_name,
                tenant_id=tenant_id,
                run_id=run_id,
                db=db,
            )
            results.extend(r2_list)
        except Exception:
            logger.exception(
                "Rule 2 failed for invoice_id=%s",
                invoice.id,
            )

    # ── Rule 3: Quantity Mismatch ──────────────────────────────────────
    try:
        r3 = await rule3_quantity_mismatch.evaluate(
            invoice_line_item=invoice_line_item,
            invoice=invoice,
            vendor_name=vendor_name,
            tenant_id=tenant_id,
            run_id=run_id,
            db=db,
        )
        if r3 is not None:
            results.append(r3)
    except Exception:
        logger.exception(
            "Rule 3 failed for invoice_line_item_id=%s",
            invoice_line_item.id,
        )

    return results
