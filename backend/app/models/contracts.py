"""
LeakSight V1 — Contract Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.8, 3.9, 3.10)
       docs/RULES_ENGINE.md (contract version resolution section)

contracts: Contract header records. One per vendor-contract relationship.
contract_versions: Versioned contract terms with validity periods.
contract_line_items: Individual pricing entries within a contract version.
"""

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base


class Contract(Base):
    """Contract header records. One per vendor-contract relationship.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False)
    contract_ref = Column(Text, nullable=True)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_contracts_tenant_vendor", "tenant_id", "vendor_id"),
    )


class ContractVersion(Base):
    """Versioned contract terms with validity periods.

    A single contract may have multiple versions (amendments, renewals).
    The contract version resolution query requires the index on
    (tenant_id, valid_from, valid_to).
    RLS-scoped by tenant_id.
    """

    __tablename__ = "contract_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    contract_id = Column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    version_number = Column(Integer, nullable=False)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "contract_id", "version_number",
            name="uq_contract_versions_contract_version",
        ),
        Index("idx_contract_versions_vendor_dates", "tenant_id", "valid_from", "valid_to"),
    )


class ContractLineItem(Base):
    """Individual pricing entries within a contract version.

    This is Commercial Truth — the agreed prices.
    RLS-scoped by tenant_id.
    """

    __tablename__ = "contract_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    contract_version_id = Column(
        UUID(as_uuid=True), ForeignKey("contract_versions.id"), nullable=False
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    item_desc = Column(Text, nullable=False)
    raw_item_desc = Column(Text, nullable=False)
    unit = Column(Text, nullable=False)
    unit_price = Column(Numeric(20, 6), nullable=False)
    currency = Column(String(3), nullable=False, server_default="INR")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_contract_line_items_version", "contract_version_id"),
    )
