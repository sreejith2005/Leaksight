"""Pydantic schemas for Tool A API endpoints."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateStructuringRunRequest(BaseModel):
    document_ids: list[UUID]
    run_label: str = Field(min_length=1, max_length=255)


class UpdateLineItemRequest(BaseModel):
    item_description: str | None = None
    unit_raw: str | None = None
    unit_price: Decimal | None = None
    currency: str | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    reviewer_notes: str | None = None

    @field_validator("unit_price")
    @classmethod
    def validate_unit_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("unit_price must be greater than zero")
        return value


class RejectLineItemRequest(BaseModel):
    reason: str = Field(min_length=1)


class UpdateClauseRequest(BaseModel):
    extracted_value: str | None = None
    reviewer_notes: str | None = None
    review_status: str | None = None


class StructuringRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    run_label: str | None
    status: str
    total_documents: int
    processed_documents: int
    total_line_items_found: int
    total_clauses_found: int
    started_at: datetime | None
    completed_at: datetime | None
    created_by_user_id: UUID | None
    created_at: datetime


class StructuringRunStatusResponse(BaseModel):
    run_id: UUID
    status: str
    processed_documents: int
    total_documents: int
    progress_percentage: float
    total_line_items_found: int
    total_clauses_found: int


class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    run_id: UUID
    document_id: UUID
    raw_table_id: UUID
    contract_id: str | None = None
    item_description: str | None
    normalized_item_id: UUID | None
    unit_raw: str | None
    normalized_unit_id: UUID | None
    unit_price: Decimal | None
    currency: str | None
    slab_info: dict | list | None
    effective_date: date | None
    expiry_date: date | None
    version_number: int
    source_page: int | None
    extraction_method: str | None = None
    item_confidence: float
    price_confidence: float
    unit_confidence: float
    review_status: str
    needs_review: bool
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    reviewer_notes: str | None
    created_at: datetime


class ClauseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    run_id: UUID
    document_id: UUID
    clause_type: str
    raw_text: str
    extracted_value: str | None
    reviewer_notes: str | None
    source_page: int | None
    confidence: float
    needs_review: bool
    review_status: str
    created_at: datetime


class RunDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    run_id: UUID
    document_id: UUID
    task_status: str
    error_message: str | None
    processing_time_seconds: float | None
    created_at: datetime
    line_items: list[LineItemResponse] = Field(default_factory=list)
    clauses: list[ClauseResponse] = Field(default_factory=list)


class StructuringRunResultsResponse(BaseModel):
    run: StructuringRunResponse
    documents: list[RunDocumentResponse]


class ExportTriggerResponse(BaseModel):
    message: str
    export_format: str
    run_id: UUID


class StructuringExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    run_id: UUID
    export_format: str
    file_path: str | None
    line_items_included: int | None
    generated_by_user_id: UUID | None
    created_at: datetime


class PaginatedRunsResponse(BaseModel):
    items: list[StructuringRunResponse]
    total: int
    page: int
    page_size: int
