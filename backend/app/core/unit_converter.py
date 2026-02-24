"""
LeakSight V1 — Unit Conversion Service

Source: docs/RULES_ENGINE.md (unit conversion section),
       docs/DATABASE_SCHEMA.md (unit_conversion_factors section, evidence_jsonb section)

Converts between units within the same dimension. Cross-dimension conversion
is an error — never silently converts. Supports tenant-specific overrides.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.units import CanonicalUnit, UnitConversionFactor


class CrossDimensionConversionError(Exception):
    """Raised when attempting to convert between different dimensions."""


class NoConversionFactorError(Exception):
    """Raised when no conversion factor is found for the given unit pair."""


class UnknownUnitError(Exception):
    """Raised when a unit is not found in canonical_units."""


@dataclass
class ConversionResult:
    """Result of a unit conversion.

    Attributes:
        converted_value: The value after conversion.
        factor_used: The conversion factor applied.
        factor_source: "SYSTEM" or "TENANT_OVERRIDE".
        from_unit: The source unit symbol.
        to_unit: The target unit symbol.
    """

    converted_value: Decimal
    factor_used: Decimal
    factor_source: str  # "SYSTEM" or "TENANT_OVERRIDE"
    from_unit: str
    to_unit: str


async def convert_units(
    value: Decimal,
    from_unit: str,
    to_unit: str,
    tenant_id: UUID,
    db: AsyncSession,
) -> ConversionResult:
    """Convert a value from one unit to another.

    Looks up units in canonical_units, validates dimensions match,
    finds conversion factor (tenant override first, then system default),
    and applies it.

    Args:
        value: The numeric value to convert.
        from_unit: Source unit symbol (e.g., "KG").
        to_unit: Target unit symbol (e.g., "MT").
        tenant_id: Tenant UUID for override factor lookup.
        db: Async database session.

    Returns:
        ConversionResult with converted value and factor details.

    Raises:
        UnknownUnitError: If either unit is not in canonical_units.
        CrossDimensionConversionError: If units have different dimensions.
        NoConversionFactorError: If no conversion factor is found.
    """
    # Same unit — return immediately with factor 1.0
    if from_unit == to_unit:
        return ConversionResult(
            converted_value=value,
            factor_used=Decimal("1"),
            factor_source="SYSTEM",
            from_unit=from_unit,
            to_unit=to_unit,
        )

    # Look up both units in canonical_units
    from_unit_stmt = select(CanonicalUnit).where(CanonicalUnit.symbol == from_unit)
    to_unit_stmt = select(CanonicalUnit).where(CanonicalUnit.symbol == to_unit)

    from_result = await db.execute(from_unit_stmt)
    from_canonical = from_result.scalar_one_or_none()

    to_result = await db.execute(to_unit_stmt)
    to_canonical = to_result.scalar_one_or_none()

    if from_canonical is None:
        raise UnknownUnitError(f"Unknown unit: '{from_unit}'")
    if to_canonical is None:
        raise UnknownUnitError(f"Unknown unit: '{to_unit}'")

    # Check dimensions match
    if from_canonical.dimension != to_canonical.dimension:
        raise CrossDimensionConversionError(
            f"Cannot convert between different dimensions: "
            f"'{from_unit}' ({from_canonical.dimension}) → "
            f"'{to_unit}' ({to_canonical.dimension}). "
            f"Cross-dimension conversion is never allowed."
        )

    # Look up conversion factor — tenant override first, then system default
    # Try tenant-specific factor first
    tenant_factor_stmt = select(UnitConversionFactor).where(
        UnitConversionFactor.from_unit_id == from_canonical.id,
        UnitConversionFactor.to_unit_id == to_canonical.id,
        UnitConversionFactor.tenant_id == tenant_id,
    )
    tenant_result = await db.execute(tenant_factor_stmt)
    tenant_factor = tenant_result.scalar_one_or_none()

    if tenant_factor is not None:
        converted = value * tenant_factor.factor
        return ConversionResult(
            converted_value=converted,
            factor_used=tenant_factor.factor,
            factor_source="TENANT_OVERRIDE",
            from_unit=from_unit,
            to_unit=to_unit,
        )

    # Try system default (tenant_id IS NULL)
    system_factor_stmt = select(UnitConversionFactor).where(
        UnitConversionFactor.from_unit_id == from_canonical.id,
        UnitConversionFactor.to_unit_id == to_canonical.id,
        UnitConversionFactor.tenant_id.is_(None),
    )
    system_result = await db.execute(system_factor_stmt)
    system_factor = system_result.scalar_one_or_none()

    if system_factor is not None:
        converted = value * system_factor.factor
        return ConversionResult(
            converted_value=converted,
            factor_used=system_factor.factor,
            factor_source="SYSTEM",
            from_unit=from_unit,
            to_unit=to_unit,
        )

    # Try reverse direction — system default
    reverse_stmt = select(UnitConversionFactor).where(
        UnitConversionFactor.from_unit_id == to_canonical.id,
        UnitConversionFactor.to_unit_id == from_canonical.id,
        UnitConversionFactor.tenant_id.is_(None),
    )
    reverse_result = await db.execute(reverse_stmt)
    reverse_factor = reverse_result.scalar_one_or_none()

    if reverse_factor is not None:
        inverse = Decimal("1") / reverse_factor.factor
        converted = value * inverse
        return ConversionResult(
            converted_value=converted,
            factor_used=inverse,
            factor_source="SYSTEM",
            from_unit=from_unit,
            to_unit=to_unit,
        )

    raise NoConversionFactorError(
        f"No conversion factor found for '{from_unit}' → '{to_unit}'"
    )
