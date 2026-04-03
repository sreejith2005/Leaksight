"""Pydantic schemas for Tool B."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class NumericChange(BaseModel):
    previous_value: float
    current_value: float
    context: str
    change_pct: float


class IntegrityReport(BaseModel):
    document_id: str
    filename: str
    doc_type: str
    risk_score: int
    risk_level: str
    comparison_status: str
    version_count: int
    flags: list[str]
    numeric_changes: list[NumericChange]
    metadata: dict[str, Any]
    analyzed_at: datetime


class IntegrityListItem(BaseModel):
    document_id: str
    filename: str
    doc_type: str
    risk_score: int | None
    risk_level: str | None
    comparison_status: str | None
    analyzed_at: datetime | None


class IntegrityListResponse(BaseModel):
    items: list[IntegrityListItem]
    total: int
    page: int
    page_size: int


class BatchAnalyzeRequest(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=50)
