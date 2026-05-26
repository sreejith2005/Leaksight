"""Tool A contract structuring ORM models."""

from sqlalchemy import (
    Boolean,
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base


structuring_run_status_enum = Enum(
    "PENDING",
    "PROCESSING",
    "COMPLETE",
    "PARTIAL_SUCCESS",
    "FAILED",
    name="structuring_run_status_enum",
    create_type=True,
)

structuring_task_status_enum = Enum(
    "PENDING",
    "PROCESSING",
    "COMPLETE",
    "FAILED",
    name="structuring_task_status_enum",
    create_type=True,
)

extraction_method_enum = Enum(
    "CAMELOT_LATTICE",
    "CAMELOT_STREAM",
    "PDFPLUMBER",
    "PADDLE_OCR",
    "DOCX_TABLE",
    "EXCEL_SHEET",
    name="structuring_extraction_method_enum",
    create_type=True,
)

line_item_review_status_enum = Enum(
    "PENDING_REVIEW",
    "CONFIRMED",
    "REJECTED",
    name="structuring_line_item_review_status_enum",
    create_type=True,
)

clause_type_enum = Enum(
    "EFFECTIVE_DATE",
    "EXPIRY_DATE",
    "AMENDMENT_REF",
    "ESCALATION",
    "VENDOR_NAME",
    "CONTRACT_REF",
    name="structuring_clause_type_enum",
    create_type=True,
)

clause_review_status_enum = Enum(
    "PENDING_REVIEW",
    "CONFIRMED",
    "REJECTED",
    name="structuring_clause_review_status_enum",
    create_type=True,
)

export_format_enum = Enum(
    "EXCEL",
    "ERP_JSON",
    "ERP_CSV",
    "LEAKSIGHT_IMPORT",
    name="structuring_export_format_enum",
    create_type=True,
)


class ContractStructuringRun(Base):
    """One row per Tool A batch structuring run."""

    __tablename__ = "contract_structuring_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_label = Column(String(255), nullable=True)
    status = Column(structuring_run_status_enum, nullable=False, server_default="PENDING")
    total_documents = Column(Integer, nullable=False, server_default="0")
    processed_documents = Column(Integer, nullable=False, server_default="0")
    total_line_items_found = Column(Integer, nullable=False, server_default="0")
    total_clauses_found = Column(Integer, nullable=False, server_default="0")
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_structuring_runs_tenant", "tenant_id"),
        Index("idx_structuring_runs_status", "tenant_id", "status"),
    )


class ContractStructuringRunDocument(Base):
    """Links a structuring run with each document being processed."""

    __tablename__ = "contract_structuring_run_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("contract_structuring_runs.id"),
        nullable=False,
    )
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    task_status = Column(structuring_task_status_enum, nullable=False, server_default="PENDING")
    error_message = Column(Text, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "document_id",
            name="uq_structuring_run_docs_tenant_run_document",
        ),
        Index("idx_structuring_run_docs_tenant", "tenant_id"),
        Index("idx_structuring_run_docs_run", "tenant_id", "run_id"),
        Index("idx_structuring_run_docs_doc", "tenant_id", "document_id"),
    )


class RawContractTable(Base):
    """Immutable raw extraction output before normalization."""

    __tablename__ = "raw_contract_tables"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    run_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("contract_structuring_run_documents.id"),
        nullable=False,
    )
    source_page = Column(Integer, nullable=True)
    extraction_method = Column(extraction_method_enum, nullable=False)
    raw_table_json = Column(JSONB, nullable=False)
    table_confidence = Column(Float, nullable=False)
    column_count = Column(Integer, nullable=True)
    row_count = Column(Integer, nullable=True)
    is_continuation = Column(Boolean, nullable=False, server_default="false")
    continued_from_id = Column(UUID(as_uuid=True), ForeignKey("raw_contract_tables.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_raw_contract_tables_tenant", "tenant_id"),
        Index("idx_raw_contract_tables_document", "tenant_id", "document_id"),
        CheckConstraint(
            "table_confidence >= 0 AND table_confidence <= 1",
            name="ck_raw_contract_tables_confidence_range",
        ),
        CheckConstraint(
            "is_continuation IN (true, false)",
            name="ck_raw_contract_tables_is_continuation",
        ),
    )


class ExtractedLineItem(Base):
    """Canonical normalized pricing rows from raw contract tables."""

    __tablename__ = "extracted_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("contract_structuring_runs.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    raw_table_id = Column(UUID(as_uuid=True), ForeignKey("raw_contract_tables.id"), nullable=False)
    contract_id = Column(String(100), nullable=True)
    item_description = Column(Text, nullable=True)
    normalized_item_id = Column(UUID(as_uuid=True), nullable=True)
    unit_raw = Column(String(100), nullable=True)
    normalized_unit_id = Column(UUID(as_uuid=True), ForeignKey("canonical_units.id"), nullable=True)
    unit_price = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(10), nullable=True, server_default="INR")
    slab_info = Column(JSONB, nullable=True)
    effective_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    version_number = Column(Integer, nullable=False, server_default="1")
    source_page = Column(Integer, nullable=True)
    item_confidence = Column(Float, nullable=False)
    price_confidence = Column(Float, nullable=False)
    unit_confidence = Column(Float, nullable=False)
    review_status = Column(
        line_item_review_status_enum,
        nullable=False,
        server_default="PENDING_REVIEW",
    )
    needs_review = Column(Boolean, nullable=False, server_default="false")
    reviewed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_extracted_line_items_tenant", "tenant_id"),
        Index("idx_extracted_line_items_run", "tenant_id", "run_id"),
        Index("idx_extracted_line_items_doc", "tenant_id", "document_id"),
        Index("idx_extracted_line_items_status", "tenant_id", "review_status"),
        CheckConstraint(
            "item_confidence >= 0 AND item_confidence <= 1",
            name="ck_extracted_line_items_item_confidence",
        ),
        CheckConstraint(
            "price_confidence >= 0 AND price_confidence <= 1",
            name="ck_extracted_line_items_price_confidence",
        ),
        CheckConstraint(
            "unit_confidence >= 0 AND unit_confidence <= 1",
            name="ck_extracted_line_items_unit_confidence",
        ),
        CheckConstraint(
            "needs_review IN (true, false)",
            name="ck_extracted_line_items_needs_review",
        ),
    )


class ExtractedClause(Base):
    """Extracted commercial clause values from contract text."""

    __tablename__ = "extracted_clauses"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("contract_structuring_runs.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    clause_type = Column(clause_type_enum, nullable=False)
    raw_text = Column(Text, nullable=False)
    extracted_value = Column(Text, nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    source_page = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=False)
    needs_review = Column(Boolean, nullable=False, server_default="false")
    review_status = Column(
        clause_review_status_enum,
        nullable=False,
        server_default="PENDING_REVIEW",
    )
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_extracted_clauses_tenant", "tenant_id"),
        Index("idx_extracted_clauses_run", "tenant_id", "run_id"),
        Index("idx_extracted_clauses_doc", "tenant_id", "document_id"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_extracted_clauses_confidence_range",
        ),
        CheckConstraint(
            "needs_review IN (true, false)",
            name="ck_extracted_clauses_needs_review",
        ),
    )


class ContractStructuringExport(Base):
    """Audit trail for generated Tool A exports."""

    __tablename__ = "contract_structuring_exports"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("contract_structuring_runs.id"), nullable=False)
    export_format = Column(export_format_enum, nullable=False)
    file_path = Column(Text, nullable=True)
    line_items_included = Column(Integer, nullable=True)
    generated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_structuring_exports_tenant", "tenant_id"),
        Index("idx_structuring_exports_run", "tenant_id", "run_id"),
    )
