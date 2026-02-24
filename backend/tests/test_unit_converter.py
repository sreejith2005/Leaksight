"""
Tests for the Unit Conversion Service.

Source: docs/RULES_ENGINE.md (unit conversion section),
       docs/DATABASE_SCHEMA.md (unit_conversion_factors section)

Covers:
  - KG to MT: valid, returns correct factor (0.001), factor_source SYSTEM
  - MT to KG: valid reverse lookup, returns correct factor (1000)
  - KG to L: cross-dimension, raises CrossDimensionConversionError
  - Same unit KG to KG: returns 1.0 factor immediately
  - Tenant override factor takes precedence over system default
  - Unknown unit raises appropriate error
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.core.unit_converter import (
    ConversionResult,
    CrossDimensionConversionError,
    NoConversionFactorError,
    UnknownUnitError,
    convert_units,
)


TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
KG_UNIT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MT_UNIT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
L_UNIT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _make_unit(unit_id: uuid.UUID, name: str, symbol: str, dimension: str) -> MagicMock:
    """Create a mock CanonicalUnit."""
    unit = MagicMock()
    unit.id = unit_id
    unit.name = name
    unit.symbol = symbol
    unit.dimension = dimension
    return unit


def _make_factor(
    factor: Decimal,
    tenant_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a mock UnitConversionFactor."""
    f = MagicMock()
    f.factor = factor
    f.tenant_id = tenant_id
    return f


class TestSameUnitConversion:
    """Same unit returns 1.0 factor immediately — no DB calls needed."""

    async def test_kg_to_kg(self) -> None:
        """KG to KG returns factor 1.0 immediately."""
        mock_db = AsyncMock()

        result = await convert_units(
            value=Decimal("100"),
            from_unit="KG",
            to_unit="KG",
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.converted_value == Decimal("100")
        assert result.factor_used == Decimal("1")
        assert result.factor_source == "SYSTEM"
        mock_db.execute.assert_not_called()


class TestKGtoMT:
    """KG → MT: valid conversion, factor 0.001, SYSTEM source."""

    async def test_kg_to_mt_system_factor(self) -> None:
        """KG to MT uses system default factor 0.001."""
        mock_db = AsyncMock()
        kg_unit = _make_unit(KG_UNIT_ID, "kilogram", "KG", "WEIGHT")
        mt_unit = _make_unit(MT_UNIT_ID, "metric_ton", "MT", "WEIGHT")
        system_factor = _make_factor(Decimal("0.001"))

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # from_unit lookup → KG
                result.scalar_one_or_none.return_value = kg_unit
            elif call_count == 2:
                # to_unit lookup → MT
                result.scalar_one_or_none.return_value = mt_unit
            elif call_count == 3:
                # tenant override → None
                result.scalar_one_or_none.return_value = None
            elif call_count == 4:
                # system default → factor 0.001
                result.scalar_one_or_none.return_value = system_factor
            return result

        mock_db.execute = side_effect

        result = await convert_units(
            value=Decimal("1000"),
            from_unit="KG",
            to_unit="MT",
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.converted_value == Decimal("1.000")
        assert result.factor_used == Decimal("0.001")
        assert result.factor_source == "SYSTEM"
        assert result.from_unit == "KG"
        assert result.to_unit == "MT"


class TestMTtoKG:
    """MT → KG: reverse lookup, factor 1000."""

    async def test_mt_to_kg_reverse_lookup(self) -> None:
        """MT to KG uses reverse lookup when direct not found."""
        mock_db = AsyncMock()
        mt_unit = _make_unit(MT_UNIT_ID, "metric_ton", "MT", "WEIGHT")
        kg_unit = _make_unit(KG_UNIT_ID, "kilogram", "KG", "WEIGHT")
        # Reverse factor: KG→MT = 0.001, so MT→KG = 1/0.001 = 1000
        reverse_factor = _make_factor(Decimal("0.001"))

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = mt_unit
            elif call_count == 2:
                result.scalar_one_or_none.return_value = kg_unit
            elif call_count == 3:
                # tenant override → None
                result.scalar_one_or_none.return_value = None
            elif call_count == 4:
                # system default direct → None
                result.scalar_one_or_none.return_value = None
            elif call_count == 5:
                # reverse lookup → found
                result.scalar_one_or_none.return_value = reverse_factor
            return result

        mock_db.execute = side_effect

        result = await convert_units(
            value=Decimal("1"),
            from_unit="MT",
            to_unit="KG",
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.converted_value == Decimal("1000")
        assert result.factor_source == "SYSTEM"


class TestCrossDimensionError:
    """KG → L: different dimensions, must raise error."""

    async def test_kg_to_l_raises_error(self) -> None:
        """Cross-dimension conversion raises CrossDimensionConversionError."""
        mock_db = AsyncMock()
        kg_unit = _make_unit(KG_UNIT_ID, "kilogram", "KG", "WEIGHT")
        l_unit = _make_unit(L_UNIT_ID, "litre", "L", "VOLUME")

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = kg_unit
            elif call_count == 2:
                result.scalar_one_or_none.return_value = l_unit
            return result

        mock_db.execute = side_effect

        with pytest.raises(CrossDimensionConversionError, match="different dimensions"):
            await convert_units(
                value=Decimal("100"),
                from_unit="KG",
                to_unit="L",
                tenant_id=TENANT_ID,
                db=mock_db,
            )


class TestTenantOverride:
    """Tenant override factor takes precedence over system default."""

    async def test_tenant_override_precedence(self) -> None:
        """Tenant-specific factor used over system default."""
        mock_db = AsyncMock()
        kg_unit = _make_unit(KG_UNIT_ID, "kilogram", "KG", "WEIGHT")
        mt_unit = _make_unit(MT_UNIT_ID, "metric_ton", "MT", "WEIGHT")
        tenant_factor = _make_factor(Decimal("0.0012"), tenant_id=TENANT_ID)

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = kg_unit
            elif call_count == 2:
                result.scalar_one_or_none.return_value = mt_unit
            elif call_count == 3:
                # tenant override → found!
                result.scalar_one_or_none.return_value = tenant_factor
            return result

        mock_db.execute = side_effect

        result = await convert_units(
            value=Decimal("1000"),
            from_unit="KG",
            to_unit="MT",
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.converted_value == Decimal("1.2000")
        assert result.factor_used == Decimal("0.0012")
        assert result.factor_source == "TENANT_OVERRIDE"


class TestUnknownUnit:
    """Unknown unit raises UnknownUnitError."""

    async def test_unknown_from_unit(self) -> None:
        """Unknown from_unit raises UnknownUnitError."""
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(UnknownUnitError, match="Unknown unit"):
            await convert_units(
                value=Decimal("100"),
                from_unit="XYZ",
                to_unit="KG",
                tenant_id=TENANT_ID,
                db=mock_db,
            )

    async def test_unknown_to_unit(self) -> None:
        """Unknown to_unit raises UnknownUnitError."""
        mock_db = AsyncMock()
        kg_unit = _make_unit(KG_UNIT_ID, "kilogram", "KG", "WEIGHT")

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = kg_unit
            elif call_count == 2:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = side_effect

        with pytest.raises(UnknownUnitError, match="Unknown unit"):
            await convert_units(
                value=Decimal("100"),
                from_unit="KG",
                to_unit="ZZZZ",
                tenant_id=TENANT_ID,
                db=mock_db,
            )
