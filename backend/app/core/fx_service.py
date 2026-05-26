"""
LeakSight V1 — FX Rate Service

Source: docs/RULES_ENGINE.md (PENDING_FX_RATE section),
       docs/DATABASE_SCHEMA.md (fx_rates section),
       docs/DECISIONS.md (ADR-006 — no outbound internet)

This service reads FX rates from the database ONLY. It never makes an
outbound API call under any circumstances. If no rate is found, it returns
the PENDING_FX_RATE sentinel — it does not raise an error and it does not
guess.

No HTTP client is imported in this file. This is a structural enforcement
of the no-outbound-internet rule.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Union
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.units import FxRate

# Sentinel value returned when no FX rate is available
PENDING_FX_RATE: str = "PENDING_FX_RATE"


@dataclass
class FXResult:
    """Result of an FX rate lookup.

    Attributes:
        rate: The exchange rate.
        rate_date: The date of the rate used.
        source: Rate source (ECB, RBI, MANUAL_UPLOAD, ADMIN_IMPORT).
        from_currency: Source currency code.
        to_currency: Target currency code.
    """

    rate: Decimal
    rate_date: date
    source: str  # ECB, RBI, MANUAL_UPLOAD, ADMIN_IMPORT
    from_currency: str
    to_currency: str


async def get_rate(
    from_currency: str,
    to_currency: str,
    invoice_date: date,
    tenant_id: UUID,
    db: AsyncSession,
) -> Union[FXResult, str]:
    """Look up an FX rate from the database.

    Returns the closest rate_date that is less than or equal to invoice_date.
    Checks tenant-specific rates first, then falls back to system rates.
    If no rate found, returns the string literal PENDING_FX_RATE — does not
    raise an error, does not guess, does not use a rate from a future date.

    This function NEVER makes an outbound API call.

    Args:
        from_currency: Source currency code (e.g., "USD").
        to_currency: Target currency code (e.g., "INR").
        invoice_date: The invoice date for rate lookup.
        tenant_id: Tenant UUID for tenant-specific rate overrides.
        db: Async database session.

    Returns:
        FXResult with rate details, or the string "PENDING_FX_RATE" if no
        rate is available.
    """
    # Same currency — return 1.0 immediately
    if from_currency == to_currency:
        return FXResult(
            rate=Decimal("1"),
            rate_date=invoice_date,
            source="SYSTEM",
            from_currency=from_currency,
            to_currency=to_currency,
        )

    # Try tenant-specific rate first (closest date <= invoice_date)
    tenant_rate_stmt = (
        select(FxRate)
        .where(
            FxRate.tenant_id == tenant_id,
            FxRate.from_currency == from_currency,
            FxRate.to_currency == to_currency,
            FxRate.rate_date <= invoice_date,
        )
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )
    tenant_result = await db.execute(tenant_rate_stmt)
    tenant_rate = tenant_result.scalar_one_or_none()

    if tenant_rate is not None:
        return FXResult(
            rate=tenant_rate.rate,
            rate_date=tenant_rate.rate_date,
            source=tenant_rate.source.value if hasattr(tenant_rate.source, "value") else str(tenant_rate.source),
            from_currency=from_currency,
            to_currency=to_currency,
        )

    # Fall back to system rate (tenant_id IS NULL)
    system_rate_stmt = (
        select(FxRate)
        .where(
            FxRate.tenant_id.is_(None),
            FxRate.from_currency == from_currency,
            FxRate.to_currency == to_currency,
            FxRate.rate_date <= invoice_date,
        )
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )
    system_result = await db.execute(system_rate_stmt)
    system_rate = system_result.scalar_one_or_none()

    if system_rate is not None:
        return FXResult(
            rate=system_rate.rate,
            rate_date=system_rate.rate_date,
            source=system_rate.source.value if hasattr(system_rate.source, "value") else str(system_rate.source),
            from_currency=from_currency,
            to_currency=to_currency,
        )

    # No rate found — return PENDING_FX_RATE sentinel
    return PENDING_FX_RATE
