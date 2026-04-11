"""Tool C document revalidation ORM models."""

from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base


class RevalidationSubject(Base):
    """Company employee or vendor that requires recurring document checks."""

    __tablename__ = "revalidation_subjects"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    subject_type = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)
    identifier = Column(String(255), nullable=False)
    department = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    documents = relationship("RevalidationDocument", back_populates="subject")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_type",
            "identifier",
            name="uq_revalidation_subjects_tenant_type_identifier",
        ),
    )


class RevalidationDocCatalog(Base):
    """Tenant-specific or system-default catalog rows for required documents."""

    __tablename__ = "revalidation_doc_catalog"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    subject_type = Column(String(20), nullable=False)
    category = Column(String(50), nullable=False)
    display_name = Column(String(255), nullable=False)
    is_required = Column(Boolean, nullable=False, server_default="false")
    has_expiry = Column(Boolean, nullable=False, server_default="true")
    alert_days_before = Column(Integer, nullable=False, server_default="30")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class RevalidationDocument(Base):
    """Tracked document requirement instance for a subject."""

    __tablename__ = "revalidation_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("revalidation_subjects.id"), nullable=False)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    category = Column(String(50), nullable=False)
    display_name = Column(String(255), nullable=False)
    issue_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    has_expiry = Column(Boolean, nullable=False, server_default="true")
    manually_reviewed = Column(Boolean, nullable=False, server_default="false")
    status = Column(String(30), nullable=False, server_default="PENDING_UPLOAD")
    extraction_confidence = Column(Float, nullable=True)
    alert_days_before = Column(Integer, nullable=False, server_default="30")
    last_checked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    subject = relationship("RevalidationSubject", back_populates="documents")
    document = relationship("Document")


class RevalidationAlert(Base):
    """Alert row created for expiring or expired revalidation documents."""

    __tablename__ = "revalidation_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    revalidation_doc_id = Column(
        UUID(as_uuid=True),
        ForeignKey("revalidation_documents.id"),
        nullable=False,
    )
    alert_type = Column(String(30), nullable=False)
    message = Column(Text, nullable=False)
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
