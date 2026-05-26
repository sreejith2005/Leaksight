"""
LeakSight V1 — Invoice Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.11, 3.12)
       docs/RULES_ENGINE.md (Rule 2 — near-duplicate scanning)

invoices: Invoice header records. Primary Financial Truth document.
invoice_line_items: Atomic units of leakage detection.
"""

from sqlalchemy import (
    Column,
    Date,
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


class Invoice(Base):
    """Invoice header records. Primary Financial Truth document.

    The composite index (tenant_id, vendor_id, invoice_date) is mandatory
    for Rule 2 near-duplicate scanning at scale. Without it, queries
    degrade to full table scan at 10,000+ invoices.
    RLS-scoped by tenant_id.
    """

    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    invoice_no = Column(Text, nullable=False)
    invoice_date = Column(Date, nullable=False)
    total_amount = Column(Numeric(20, 6), nullable=False)
    currency = Column(String(3), nullable=False, server_default="INR")
    source_document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_no", name="uq_invoices_tenant_invoice_no"),
        Index("idx_invoices_tenant_id", "tenant_id"),
        Index("idx_invoices_vendor_id", "vendor_id"),
        Index("idx_invoices_tenant_vendor_date", "tenant_id", "vendor_id", "invoice_date"),
    )


class InvoiceLineItem(Base):
    """Individual line items from an invoice. Atomic units of leakage detection.

    RLS-scoped by tenant_id (denormalized).
    """

    __tablename__ = "invoice_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    item_desc = Column(Text, nullable=False)
    raw_item_desc = Column(Text, nullable=False)
    contract_ref = Column(Text, nullable=True)
    quantity = Column(Numeric(20, 6), nullable=False)
    unit = Column(Text, nullable=False)
    unit_price = Column(Numeric(20, 6), nullable=False)
    line_total = Column(Numeric(20, 6), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_invoice_line_items_invoice", "invoice_id"),
    )
