"""
LeakSight V1 — Rule 1: Invoice vs Contract Price Mismatch

Source: docs/RULES_ENGINE.md (Section 3)

Detects when a vendor charges more on an invoice than the contractually
agreed price. Leakage type: PRICE_MISMATCH.

Eight-step evaluation:
  1. Contract validity check (via contract_resolver)
  2. Item matching (exact then fuzzy via RapidFuzz)
  3. Unit conversion check (via unit_converter)
  4. Currency check (via fx_service)
  5. Price comparison
  6. Confidence calculation
  7. Evidence population
  8. Human-readable explanation
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from rapidfuzz.fuzz import token_sort_ratio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.contract_resolver import (
    ContractResolutionStatus,
    get_valid_contract_version,
)
from backend.app.core.fx_service import PENDING_FX_RATE, get_rate
from backend.app.core.unit_converter import (
    CrossDimensionConversionError,
    NoConversionFactorError,
    UnknownUnitError,
    convert_units,
)
from backend.app.models.contracts import ContractLineItem
from backend.app.models.tenant import TenantSettings


@dataclass
class RuleResult:
    """Standard result returned by any rule evaluation.

    The orchestrator collects these and the leakage service writes them
    to the database.
    """

    leakage_type: str
    amount: Decimal
    currency: str
    confidence: float
    evidence_jsonb: dict
    rule_applied: str
    explanation: str
    status: str  # PENDING or PENDING_FX_RATE
    invoice_id: UUID
    invoice_line_item_id: Optional[UUID] = None
    contract_line_item_id: Optional[UUID] = None


async def _get_fuzzy_threshold(tenant_id: UUID, db: AsyncSession) -> float:
    """Load the tenant's fuzzy threshold or fall back to default 0.85."""
    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    return float(settings.fuzzy_threshold) if settings else 0.85


async def _match_item(
    invoice_item_desc: str,
    contract_version_id: UUID,
    fuzzy_threshold: float,
    db: AsyncSession,
) -> tuple:
    """Match an invoice item description against contract line items.

    Returns (matched_contract_line_item, item_match_confidence, match_method)
    or (None, 0.0, "NONE") if no match found.
    """
    stmt = select(ContractLineItem).where(
        ContractLineItem.contract_version_id == contract_version_id
    )
    result = await db.execute(stmt)
    contract_items: List = list(result.scalars().all())

    if not contract_items:
        return None, 0.0, "NONE"

    # Step 1: Exact match (after normalization — both sides already normalized)
    for cli in contract_items:
        if cli.item_desc == invoice_item_desc:
            return cli, 1.0, "EXACT"

    # Step 2: Fuzzy match — find highest score >= threshold
    best_match = None
    best_score = 0.0
    for cli in contract_items:
        score = token_sort_ratio(invoice_item_desc, cli.item_desc) / 100.0
        if score >= fuzzy_threshold and score > best_score:
            best_match = cli
            best_score = score

    if best_match:
        return best_match, best_score, "FUZZY"

    return None, 0.0, "NONE"


async def evaluate(
    invoice_line_item,
    invoice,
    vendor_name: str,
    vendor_match_confidence: float,
    tenant_id: UUID,
    run_id: UUID,
    db: AsyncSession,
) -> Optional[RuleResult]:
    """Evaluate Rule 1 for a single invoice line item.

    Returns a RuleResult if leakage detected, None if clean/skipped.

    Edge cases handled:
    - Zero quantity → skip
    - Negative amount → skip
    - Zero contract price → skip
    - Contract overlap → manual review (confidence 0.5)
    - Cross-dimension unit mismatch → skip with warning
    - Missing FX rate → PENDING_FX_RATE
    """
    # ── Edge case: zero qty or negative amount ─────────────────────────
    if invoice_line_item.quantity <= 0 or invoice_line_item.unit_price < 0:
        return None

    # ── Step 1: Contract Validity Check ────────────────────────────────
    contract_result = await get_valid_contract_version(
        vendor_id=invoice.vendor_id,
        invoice_date=invoice.invoice_date,
        tenant_id=tenant_id,
        db=db,
    )

    if contract_result.status == ContractResolutionStatus.NONE:
        return None  # No contract for this period — skip

    if contract_result.status == ContractResolutionStatus.OVERLAP:
        explanation = (
            f"Multiple overlapping contract versions found for vendor "
            f"{vendor_name} on {invoice.invoice_date}. Manual review "
            f"required to determine correct contract price."
        )
        return RuleResult(
            leakage_type="PRICE_MISMATCH",
            amount=Decimal("0"),
            currency=invoice.currency,
            confidence=0.5,
            evidence_jsonb={
                "contract_overlap": True,
                "version_count": len(contract_result.versions),
            },
            rule_applied="RULE_1_PRICE_MISMATCH",
            explanation=explanation,
            status="PENDING",
            invoice_id=invoice.id,
            invoice_line_item_id=invoice_line_item.id,
        )

    # Exactly 1 valid version
    contract_version = contract_result.versions[0]

    # ── Step 2: Item Matching ──────────────────────────────────────────
    fuzzy_threshold = await _get_fuzzy_threshold(tenant_id, db)
    matched_cli, item_confidence, item_method = await _match_item(
        invoice_item_desc=invoice_line_item.item_desc,
        contract_version_id=contract_version.id,
        fuzzy_threshold=fuzzy_threshold,
        db=db,
    )

    if matched_cli is None:
        return None  # No matching contract line item — skip

    # Edge case: zero contract price
    if matched_cli.unit_price <= 0:
        return None  # Data quality issue — skip

    # ── Step 3: Unit Conversion ────────────────────────────────────────
    invoice_unit_price = Decimal(str(invoice_line_item.unit_price))
    invoice_unit = invoice_line_item.unit
    contract_unit = matched_cli.unit
    unit_conversion_details = {"applied": False}

    if invoice_unit != contract_unit:
        try:
            conv_result = await convert_units(
                value=invoice_unit_price,
                from_unit=invoice_unit,
                to_unit=contract_unit,
                tenant_id=tenant_id,
                db=db,
            )
            invoice_unit_price = conv_result.converted_value
            unit_conversion_details = {
                "applied": True,
                "from_unit": invoice_unit,
                "to_unit": contract_unit,
                "factor": str(conv_result.factor_used),
                "source": conv_result.factor_source,
            }
        except CrossDimensionConversionError:
            # Cross-dimension — skip with warning (logged at orchestrator)
            return None
        except (UnknownUnitError, NoConversionFactorError):
            # Unknown unit or no factor — skip
            return None

    # ── Step 4: Currency Check ─────────────────────────────────────────
    invoice_currency = invoice.currency
    contract_currency = matched_cli.currency
    fx_details = {"applied": False}

    if invoice_currency != contract_currency:
        fx_result = await get_rate(
            from_currency=invoice_currency,
            to_currency=contract_currency,
            invoice_date=invoice.invoice_date,
            tenant_id=tenant_id,
            db=db,
        )

        if fx_result == PENDING_FX_RATE:
            explanation = (
                f"Price mismatch suspected but FX rate for "
                f"{invoice_currency} to {contract_currency} on "
                f"{invoice.invoice_date} is not available. Upload the "
                f"FX rate to complete this calculation."
            )
            return RuleResult(
                leakage_type="PRICE_MISMATCH",
                amount=Decimal("0"),
                currency=contract_currency,
                confidence=min(vendor_match_confidence, item_confidence),
                evidence_jsonb={
                    "invoice_reference": {
                        "invoice_id": str(invoice.id),
                        "invoice_no": invoice.invoice_no,
                        "line_item_id": str(invoice_line_item.id),
                        "item_desc": invoice_line_item.item_desc,
                        "unit_price": str(invoice_line_item.unit_price),
                        "quantity": str(invoice_line_item.quantity),
                        "unit": invoice_line_item.unit,
                        "currency": invoice_currency,
                    },
                    "contract_reference": {
                        "contract_line_item_id": str(matched_cli.id),
                        "item_desc": matched_cli.item_desc,
                        "unit_price": str(matched_cli.unit_price),
                        "unit": matched_cli.unit,
                        "currency": contract_currency,
                    },
                    "fx_rate_applied": {
                        "applied": False,
                        "pending": True,
                        "from_currency": invoice_currency,
                        "to_currency": contract_currency,
                    },
                    "unit_conversion_details": unit_conversion_details,
                },
                rule_applied="RULE_1_PRICE_MISMATCH",
                explanation=explanation,
                status="PENDING_FX_RATE",
                invoice_id=invoice.id,
                invoice_line_item_id=invoice_line_item.id,
                contract_line_item_id=matched_cli.id,
            )

        # FX rate found — convert
        invoice_unit_price = invoice_unit_price * fx_result.rate
        fx_details = {
            "applied": True,
            "rate": str(fx_result.rate),
            "rate_date": str(fx_result.rate_date),
            "source": fx_result.source,
            "from_currency": invoice_currency,
            "to_currency": contract_currency,
        }

    # ── Step 5: Price Comparison ───────────────────────────────────────
    contract_unit_price = Decimal(str(matched_cli.unit_price))
    price_difference = invoice_unit_price - contract_unit_price

    if price_difference <= 0:
        return None  # Invoice price at or below contract price — clean

    quantity = Decimal(str(invoice_line_item.quantity))
    total_leakage = price_difference * quantity

    # ── Step 6: Confidence ─────────────────────────────────────────────
    confidence = min(vendor_match_confidence, item_confidence)

    # ── Step 7: Evidence ───────────────────────────────────────────────
    evidence = {
        "invoice_reference": {
            "invoice_id": str(invoice.id),
            "invoice_no": invoice.invoice_no,
            "line_item_id": str(invoice_line_item.id),
            "item_desc": invoice_line_item.item_desc,
            "unit_price": str(invoice_line_item.unit_price),
            "quantity": str(quantity),
            "unit": invoice_line_item.unit,
            "currency": invoice_currency,
        },
        "contract_reference": {
            "contract_line_item_id": str(matched_cli.id),
            "item_desc": matched_cli.item_desc,
            "unit_price": str(contract_unit_price),
            "unit": matched_cli.unit,
            "currency": matched_cli.currency,
            "version_number": contract_version.version_number,
            "valid_from": str(contract_version.valid_from),
            "valid_to": str(contract_version.valid_to),
        },
        "calculation": {
            "price_difference_per_unit": str(price_difference),
            "quantity": str(quantity),
            "total_leakage": str(total_leakage),
            "currency": matched_cli.currency,
        },
        "unit_conversion_details": unit_conversion_details,
        "fx_rate_applied": fx_details,
        "match_confidence_breakdown": {
            "vendor_match_confidence": vendor_match_confidence,
            "item_match_method": item_method,
            "item_match_confidence": item_confidence,
            "overall_confidence": confidence,
        },
    }

    # ── Step 8: Explanation ────────────────────────────────────────────
    if unit_conversion_details["applied"]:
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} charges "
            f"\u20b9{invoice_line_item.unit_price}/{invoice_unit} for "
            f"'{invoice_line_item.item_desc}'. After converting to "
            f"{contract_unit} (factor: {unit_conversion_details['factor']}), "
            f"this equals \u20b9{invoice_unit_price}/{contract_unit}. "
            f"The contract (version {contract_version.version_number}, "
            f"valid {contract_version.valid_from} to "
            f"{contract_version.valid_to}) specifies "
            f"\u20b9{contract_unit_price}/{contract_unit}. "
            f"Overcharge of \u20b9{price_difference}/{contract_unit} "
            f"\u00d7 {quantity} {contract_unit} = "
            f"\u20b9{total_leakage} total."
        )
    elif fx_details["applied"]:
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} charges "
            f"{invoice_currency} {invoice_line_item.unit_price}/unit for "
            f"'{invoice_line_item.item_desc}'. Using FX rate "
            f"{fx_details['rate']} ({fx_details['source']}, "
            f"{fx_details['rate_date']}), this equals "
            f"\u20b9{invoice_unit_price}/unit. "
            f"The contract specifies \u20b9{contract_unit_price}/unit. "
            f"Overcharge of \u20b9{price_difference}/unit \u00d7 "
            f"{quantity} units = \u20b9{total_leakage} total."
        )
    else:
        explanation = (
            f"Invoice {invoice.invoice_no} from {vendor_name} charges "
            f"\u20b9{invoice_unit_price}/unit for "
            f"'{invoice_line_item.item_desc}' but the contract "
            f"(version {contract_version.version_number}, valid "
            f"{contract_version.valid_from} to "
            f"{contract_version.valid_to}) specifies "
            f"\u20b9{contract_unit_price}/unit. Overcharge of "
            f"\u20b9{price_difference}/unit \u00d7 {quantity} units "
            f"= \u20b9{total_leakage} total."
        )

    # Append fuzzy match indicators if applicable
    if item_method == "FUZZY":
        explanation += (
            f" (item matched by description similarity at "
            f"{item_confidence * 100:.0f}%)"
        )

    return RuleResult(
        leakage_type="PRICE_MISMATCH",
        amount=total_leakage,
        currency=matched_cli.currency,
        confidence=confidence,
        evidence_jsonb=evidence,
        rule_applied="RULE_1_PRICE_MISMATCH",
        explanation=explanation,
        status="PENDING",
        invoice_id=invoice.id,
        invoice_line_item_id=invoice_line_item.id,
        contract_line_item_id=matched_cli.id,
    )
