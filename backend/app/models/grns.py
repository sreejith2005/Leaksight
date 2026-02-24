"""
LeakSight V1 — GRN Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.15, 3.16)

grns: Goods Received Note header records. GRN overrides PO for quantity truth.
grn_line_items: Individual GRN line items with received quantities.
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


class Grn(Base):
    """Goods Received Note header records. GRN overrides PO for quantity truth.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "grns"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    po_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False)
    grn_no = Column(Text, nullable=False)
    grn_date = Column(Date, nullable=False)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "grn_no", name="uq_grns_tenant_grn_no"),
        Index("idx_grns_tenant_po", "tenant_id", "po_id"),
    )


class GrnLineItem(Base):
    """Individual GRN line items. Received quantities.

    RLS-scoped by tenant_id (denormalized).
    """

    __tablename__ = "grn_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    grn_id = Column(UUID(as_uuid=True), ForeignKey("grns.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    item_desc = Column(Text, nullable=False)
    raw_item_desc = Column(Text, nullable=False)
    unit = Column(Text, nullable=False)
    received_qty = Column(Numeric(20, 6), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_grn_line_items_grn", "grn_id"),
    )
