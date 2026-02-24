"""
LeakSight V1 — Derived Layer Models

Source: docs/DATABASE_SCHEMA.md (Sections 4.1, 4.2, 4.3)
       docs/DATABASE_SCHEMA.md (Section 4.2.2 — immutability trigger)

analysis_runs: Tracks each analysis run's lifecycle.
leakage_records: The most important data structure. Each row = one detected leakage.
document_hashes: Hash fingerprints for document integrity tracking.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base

# --- Enums ---
run_status_enum = Enum(
    "QUEUED", "PROCESSING", "PARTIAL_SUCCESS", "COMPLETE", "FAILED",
    name="run_status_enum",
    create_type=True,
)

leakage_type_enum = Enum(
    "PRICE_MISMATCH", "DUPLICATE_INVOICE", "QUANTITY_MISMATCH",
    name="leakage_type_enum",
    create_type=True,
)

leakage_status_enum = Enum(
    "PENDING", "ACCEPTED", "REJECTED", "PENDING_FX_RATE",
    name="leakage_status_enum",
    create_type=True,
)

hash_type_enum = Enum(
    "BASELINE", "REUPLOAD", "PERIODIC_CHECK",
    name="hash_type_enum",
    create_type=True,
)

comparison_status_enum = Enum(
    "NEW", "UNCHANGED", "MODIFIED", "INCONCLUSIVE",
    name="comparison_status_enum",
    create_type=True,
)


class AnalysisRun(Base):
    """Tracks each analysis run's lifecycle.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    status = Column(run_status_enum, nullable=False, server_default="QUEUED")
    total_documents = Column(Integer, nullable=False, server_default="0")
    processed_documents = Column(Integer, nullable=False, server_default="0")
    total_leakage_found = Column(Numeric(20, 6), nullable=False, server_default="0")
    leakage_record_count = Column(Integer, nullable=False, server_default="0")
    error_summary = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_analysis_runs_tenant", "tenant_id"),
        Index("idx_analysis_runs_status", "tenant_id", "status"),
    )


class LeakageRecord(Base):
    """The most important data structure. Each row = one detected financial leakage.

    Immutability trigger (created in migration) blocks modification of
    amount, leakage_type, confidence, evidence_jsonb, rule_applied
    once status = 'ACCEPTED'.
    RLS-scoped by tenant_id.
    """

    __tablename__ = "leakage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"), nullable=False)
    leakage_type = Column(leakage_type_enum, nullable=False)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    invoice_line_item_id = Column(
        UUID(as_uuid=True), ForeignKey("invoice_line_items.id"), nullable=True
    )
    contract_line_item_id = Column(
        UUID(as_uuid=True), ForeignKey("contract_line_items.id"), nullable=True
    )
    amount = Column(Numeric(20, 6), nullable=False)
    currency = Column(String(3), nullable=False)
    confidence = Column(Float, nullable=False)
    evidence_jsonb = Column(JSONB, nullable=False)
    rule_applied = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)
    status = Column(leakage_status_enum, nullable=False, server_default="PENDING")
    reviewed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_leakage_tenant", "tenant_id"),
        Index("idx_leakage_run", "run_id"),
        Index("idx_leakage_status", "tenant_id", "status"),
        Index("idx_leakage_type", "tenant_id", "leakage_type"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_leakage_confidence_range",
        ),
    )


class DocumentHash(Base):
    """Hash fingerprints for document integrity tracking.

    Used by shared hashing layer and Tool B (Document Integrity).
    RLS-scoped by tenant_id.
    """

    __tablename__ = "document_hashes"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    hash_sha256 = Column(String(64), nullable=False)
    hash_type = Column(hash_type_enum, nullable=False)
    upload_sequence = Column(Integer, nullable=False)
    comparison_status = Column(comparison_status_enum, nullable=False, server_default="NEW")
    comparison_against_id = Column(
        UUID(as_uuid=True), ForeignKey("document_hashes.id"), nullable=True
    )
    metadata_jsonb = Column(JSONB, nullable=True)
    risk_score = Column(Integer, nullable=True)
    flagged_anomalies_jsonb = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_doc_hashes_document", "document_id"),
        Index("idx_doc_hashes_tenant", "tenant_id"),
        CheckConstraint(
            "risk_score >= 0 AND risk_score <= 100",
            name="ck_doc_hashes_risk_score_range",
        ),
    )
