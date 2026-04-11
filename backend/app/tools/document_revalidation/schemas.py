"""Pydantic schemas for Tool C document revalidation."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubjectCreate(BaseModel):
    subject_type: Literal["EMPLOYEE", "VENDOR"]
    name: str
    identifier: str
    department: str | None = None
    email: str | None = None


class SubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    subject_type: str
    name: str
    identifier: str
    department: str | None
    email: str | None
    is_active: bool
    created_at: datetime
    compliance_summary: dict | None = None


class DocCatalogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_type: str
    category: str
    display_name: str
    is_required: bool
    has_expiry: bool
    alert_days_before: int


class RevalidationDocCreate(BaseModel):
    subject_id: UUID
    category: str
    display_name: str
    has_expiry: bool = True
    alert_days_before: int = 30
    notes: str | None = None


class RevalidationDocResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    subject_id: UUID
    document_id: UUID | None
    category: str
    display_name: str
    issue_date: date | None
    expiry_date: date | None
    has_expiry: bool
    manually_reviewed: bool
    status: str
    extraction_confidence: float | None
    alert_days_before: int
    last_checked_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    days_until_expiry: int | None = None


class ManualDateUpdate(BaseModel):
    issue_date: date | None = None
    expiry_date: date | None = None
    has_expiry: bool = True
    notes: str | None = None


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    revalidation_doc_id: UUID
    alert_type: str
    message: str
    sent_at: datetime | None
    created_at: datetime


class AttachDocumentRequest(BaseModel):
    document_id: UUID
