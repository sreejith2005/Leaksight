"""
LeakSight V1 — RAW Layer Models

Source: docs/DATABASE_SCHEMA.md (Sections 2.1, 2.2)
       docs/ARCHITECTURE.md (immutability rules)

documents: Metadata about every uploaded file. One row per upload.
raw_parses: Append-only parse output records. Never updated.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base

# --- Enums ---
doc_type_enum = Enum(
    "INVOICE", "CONTRACT", "PO", "GRN",
    name="doc_type_enum",
    create_type=True,
)

parse_status_enum = Enum(
    "PENDING", "PARSING", "PARSED", "FAILED",
    name="parse_status_enum",
    create_type=True,
)


class Document(Base):
    """Stores metadata about every uploaded file. One row per uploaded file.

    RLS-scoped by tenant_id.
    """

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), nullable=True)  # FK added later to avoid circular dep
    file_path = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    doc_type = Column(doc_type_enum, nullable=False)
    file_size = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=True)
    mime_type = Column(Text, nullable=False)
    parse_status = Column(parse_status_enum, nullable=False, server_default="PENDING")
    low_confidence_flag = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_documents_tenant_id", "tenant_id"),
        Index("idx_documents_tenant_doc_type", "tenant_id", "doc_type"),
        Index("idx_documents_sha256", "sha256_hash"),
    )


class RawParse(Base):
    """Stores the output of each parse attempt. Append-only — never updated.

    Re-parsing creates a new row with incremented raw_version.
    RLS-scoped by tenant_id.
    """

    __tablename__ = "raw_parses"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    raw_version = Column(Integer, nullable=False)
    parser_used = Column(Text, nullable=False)
    parser_version = Column(Text, nullable=False)
    structured_output_jsonb = Column(JSONB, nullable=False)
    parse_confidence = Column(
        Float,
        nullable=False,
    )
    failure_flags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("document_id", "raw_version", name="uq_raw_parses_doc_version"),
        Index("idx_raw_parses_document_id", "document_id"),
        Index("idx_raw_parses_tenant_id", "tenant_id"),
        CheckConstraint(
            "parse_confidence >= 0 AND parse_confidence <= 1",
            name="ck_raw_parses_confidence_range",
        ),
    )
