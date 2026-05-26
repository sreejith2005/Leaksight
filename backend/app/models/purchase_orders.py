"""
LeakSight V1 — Purchase Order Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.13, 3.14)

purchase_orders: PO header records. Part of Operational Truth.
po_line_items: Individual PO line items.
"""

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base


class PurchaseOrder(Base):
    """Purchase order header records. Part of Operational Truth.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "purchase_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    po_no = Column(Text, nullable=False)
    po_date = Column(Date, nullable=False)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "po_no", name="uq_po_tenant_po_no"),
        Index("idx_po_tenant_vendor", "tenant_id", "vendor_id"),
    )


class PoLineItem(Base):
    """Individual PO line items.

    RLS-scoped by tenant_id (denormalized).
    """

    __tablename__ = "po_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    item_desc = Column(Text, nullable=False)
    raw_item_desc = Column(Text, nullable=False)
    unit = Column(Text, nullable=False)
    ordered_qty = Column(Numeric(20, 6), nullable=False)
    unit_price = Column(Numeric(20, 6), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_po_line_items_po", "po_id"),
    )
