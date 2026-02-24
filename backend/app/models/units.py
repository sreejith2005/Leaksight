"""
LeakSight V1 — Unit & Currency Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.5, 3.6, 3.7)

canonical_units: System-wide unit definitions. Not tenant-scoped.
unit_conversion_factors: Conversion factors between units within same dimension.
fx_rates: Foreign exchange rates for currency conversion.
"""

from sqlalchemy import (
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base

# --- Enums ---
unit_dimension_enum = Enum(
    "WEIGHT", "VOLUME", "COUNT", "AREA", "LENGTH", "TIME",
    name="unit_dimension_enum",
    create_type=True,
)

fx_source_enum = Enum(
    "ECB", "RBI", "MANUAL_UPLOAD", "ADMIN_IMPORT",
    name="fx_source_enum",
    create_type=True,
)


class CanonicalUnit(Base):
    """System-wide unit definitions. Not tenant-scoped — global reference data."""

    __tablename__ = "canonical_units"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(Text, nullable=False, unique=True)
    symbol = Column(Text, nullable=False, unique=True)
    dimension = Column(unit_dimension_enum, nullable=False)


class UnitConversionFactor(Base):
    """Conversion factors between units within the same dimension.

    Cross-dimension conversion is an error, never allowed.
    tenant_id = NULL means system default; non-NULL = tenant override.
    """

    __tablename__ = "unit_conversion_factors"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    from_unit_id = Column(
        UUID(as_uuid=True), ForeignKey("canonical_units.id"), nullable=False
    )
    to_unit_id = Column(
        UUID(as_uuid=True), ForeignKey("canonical_units.id"), nullable=False
    )
    factor = Column(Numeric(20, 10), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "from_unit_id", "to_unit_id", "tenant_id",
            name="uq_conversion_from_to_tenant",
        ),
    )


class FxRate(Base):
    """Foreign exchange rates for currency conversion.

    The system never guesses an FX rate. If no rate found,
    leakage record is created with status PENDING_FX_RATE.
    RLS applied on tenant_id (nullable — NULL = system-wide rate).
    """

    __tablename__ = "fx_rates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    from_currency = Column(String(3), nullable=False)
    to_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(20, 10), nullable=False)
    rate_date = Column(Date, nullable=False)
    source = Column(fx_source_enum, nullable=False)
    uploaded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_fx_rates_currency_date", "from_currency", "to_currency", "rate_date"),
    )
