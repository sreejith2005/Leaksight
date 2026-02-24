"""
LeakSight V1 — Vendor Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.3, 3.4)
       docs/RULES_ENGINE.md (matching engine section)

vendors: Normalized vendor records. One per tenant.
vendor_aliases: Manual and auto-accepted aliases mapping variant names to canonical vendors.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base

# --- Enums ---
alias_source_enum = Enum(
    "MANUAL_REVIEW", "IMPORT", "AUTO_ACCEPTED",
    name="alias_source_enum",
    create_type=True,
)


class Vendor(Base):
    """Normalized vendor records. One vendor per tenant.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    normalized_name = Column(Text, nullable=False)
    raw_names_jsonb = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    gst_id = Column(Text, nullable=True)
    source_system_ref = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_name", name="uq_vendors_tenant_normalized_name"),
        Index("idx_vendors_tenant_id", "tenant_id"),
        Index("idx_vendors_gst_id", "gst_id"),
    )


class VendorAlias(Base):
    """Manual and auto-accepted aliases that map variant names to a canonical vendor.

    A hit on this table during matching returns 100% confidence.
    RLS-scoped by tenant_id.
    """

    __tablename__ = "vendor_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    alias_name = Column(Text, nullable=False)
    override_source = Column(alias_source_enum, nullable=False)
    applied_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "alias_name", name="uq_vendor_aliases_tenant_alias"),
        Index("idx_vendor_aliases_tenant_id", "tenant_id"),
        Index("idx_vendor_aliases_vendor_id", "vendor_id"),
        Index("idx_vendor_aliases_alias_name", "alias_name"),
    )
