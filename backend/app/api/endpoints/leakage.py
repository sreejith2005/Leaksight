"""
LeakSight V1 — Leakage Record Endpoints

Source: docs/API_CONTRACTS.md (Section 4 — Leakage Record Endpoints),
       docs/CLAUDE.md, docs/DECISIONS.md

Endpoints:
  GET  /api/v1/leakage/records           — List leakage records with filtering
  GET  /api/v1/leakage/records/{id}      — Get single record with full evidence
  POST /api/v1/leakage/records/{id}/accept — Accept a leakage record
  POST /api/v1/leakage/records/{id}/reject — Reject a leakage record (notes required)
  GET  /api/v1/leakage/summary           — Aggregate leakage summary

Rules enforced at API layer:
  - Reject requires notes (422 if missing)
  - Accept PENDING_FX_RATE → 422
  - Already reviewed (ACCEPTED) → 409 IMMUTABLE_RECORD
  - Cross-tenant → 404 (never 403)
  - List response excludes evidence_jsonb
  - Summary financial totals use ACCEPTED-only records
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.derived import LeakageRecord
from backend.app.models.invoices import Invoice
from backend.app.models.vendors import Vendor
from backend.app.services.leakage_service import (
    ImmutabilityError,
    accept_leakage_record,
    reject_leakage_record,
)

logger = get_logger(__name__)

router = APIRouter()


# ── Request / Response Schemas ─────────────────────────────────────────


class ReviewRequest(BaseModel):
    """Request schema for accept/reject actions."""

    notes: Optional[str] = None


class PaginationMeta(BaseModel):
    """Standard pagination metadata."""

    page: int
    page_size: int
    total_records: int
    total_pages: int


# ── GET /records — List leakage records ────────────────────────────────


@router.get("/records")
async def list_leakage_records(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    # Filters
    leakage_status: Optional[str] = Query(None, alias="status"),
    leakage_type: Optional[str] = Query(None),
    vendor_id: Optional[uuid.UUID] = Query(None),
    run_id: Optional[uuid.UUID] = Query(None),
    min_amount: Optional[Decimal] = Query(None),
    max_amount: Optional[Decimal] = Query(None),
    min_confidence: Optional[float] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    # Pagination
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List leakage records with filtering and pagination.

    Response excludes evidence_jsonb (use detail endpoint for full evidence).
    Cross-tenant records are never returned (filtered by RLS + tenant_id).
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Base query — join Invoice for invoice_no and invoice_date,
    # join Vendor for vendor_name
    base_stmt = (
        select(
            LeakageRecord.id,
            LeakageRecord.run_id,
            LeakageRecord.leakage_type,
            LeakageRecord.amount,
            LeakageRecord.currency,
            LeakageRecord.confidence,
            LeakageRecord.rule_applied,
            LeakageRecord.explanation,
            LeakageRecord.status,
            LeakageRecord.created_at,
            Invoice.invoice_no.label("invoice_no"),
            Invoice.invoice_date.label("invoice_date"),
            Vendor.normalized_name.label("vendor_name"),
        )
        .join(Invoice, LeakageRecord.invoice_id == Invoice.id)
        .join(Vendor, Invoice.vendor_id == Vendor.id)
        .where(LeakageRecord.tenant_id == tenant_id)
    )

    # Count query
    count_stmt = (
        select(func.count())
        .select_from(LeakageRecord)
        .join(Invoice, LeakageRecord.invoice_id == Invoice.id)
        .where(LeakageRecord.tenant_id == tenant_id)
    )

    # Apply filters
    if leakage_status:
        base_stmt = base_stmt.where(LeakageRecord.status == leakage_status)
        count_stmt = count_stmt.where(LeakageRecord.status == leakage_status)

    if leakage_type:
        base_stmt = base_stmt.where(LeakageRecord.leakage_type == leakage_type)
        count_stmt = count_stmt.where(LeakageRecord.leakage_type == leakage_type)

    if vendor_id:
        base_stmt = base_stmt.where(Invoice.vendor_id == vendor_id)
        count_stmt = count_stmt.where(Invoice.vendor_id == vendor_id)

    if run_id:
        base_stmt = base_stmt.where(LeakageRecord.run_id == run_id)
        count_stmt = count_stmt.where(LeakageRecord.run_id == run_id)

    if min_amount is not None:
        base_stmt = base_stmt.where(LeakageRecord.amount >= min_amount)
        count_stmt = count_stmt.where(LeakageRecord.amount >= min_amount)

    if max_amount is not None:
        base_stmt = base_stmt.where(LeakageRecord.amount <= max_amount)
        count_stmt = count_stmt.where(LeakageRecord.amount <= max_amount)

    if min_confidence is not None:
        base_stmt = base_stmt.where(LeakageRecord.confidence >= min_confidence)
        count_stmt = count_stmt.where(LeakageRecord.confidence >= min_confidence)

    if date_from:
        base_stmt = base_stmt.where(Invoice.invoice_date >= date_from)
        count_stmt = count_stmt.where(Invoice.invoice_date >= date_from)

    if date_to:
        base_stmt = base_stmt.where(Invoice.invoice_date <= date_to)
        count_stmt = count_stmt.where(Invoice.invoice_date <= date_to)

    # Execute count
    total_result = await db.execute(count_stmt)
    total_records = total_result.scalar() or 0
    total_pages = max(1, (total_records + page_size - 1) // page_size)

    # Apply pagination and ordering
    base_stmt = (
        base_stmt
        .order_by(LeakageRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(base_stmt)
    rows = result.all()

    data = [
        {
            "id": str(row.id),
            "run_id": str(row.run_id) if row.run_id else None,
            "leakage_type": row.leakage_type,
            "amount": float(row.amount),
            "currency": row.currency,
            "confidence": row.confidence,
            "rule_applied": row.rule_applied,
            "explanation": row.explanation,
            "status": row.status,
            "vendor_name": row.vendor_name,
            "invoice_no": row.invoice_no,
            "invoice_date": str(row.invoice_date) if row.invoice_date else None,
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in rows
    ]

    return {
        "data": data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


# ── GET /records/{id} — Single record with full evidence ──────────────


@router.get("/records/{record_id}")
async def get_leakage_record(
    record_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a single leakage record with full evidence.

    Returns evidence_jsonb which is excluded from the list endpoint.
    Cross-tenant access returns 404, never 403.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    stmt = select(LeakageRecord).where(
        LeakageRecord.id == record_id,
        LeakageRecord.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Leakage record {record_id} not found",
                }
            },
        )

    return {
        "id": str(record.id),
        "leakage_type": record.leakage_type,
        "amount": float(record.amount),
        "currency": record.currency,
        "confidence": record.confidence,
        "rule_applied": record.rule_applied,
        "explanation": record.explanation,
        "status": record.status,
        "evidence": record.evidence_jsonb,
        "reviewed_by": str(record.reviewed_by_user_id) if record.reviewed_by_user_id else None,
        "reviewed_at": str(record.reviewed_at) if record.reviewed_at else None,
        "review_notes": record.review_notes,
        "created_at": str(record.created_at) if record.created_at else None,
    }


# ── POST /records/{id}/accept — Accept a leakage record ───────────────


@router.post("/records/{record_id}/accept")
async def accept_record(
    record_id: uuid.UUID,
    body: ReviewRequest = ReviewRequest(),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Accept a leakage record.

    PENDING_FX_RATE records cannot be accepted (422).
    Already ACCEPTED → 409 IMMUTABLE_RECORD.
    notes are optional on acceptance.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Pre-check for PENDING_FX_RATE status
    pre_stmt = select(LeakageRecord).where(
        LeakageRecord.id == record_id,
        LeakageRecord.tenant_id == tenant_id,
    )
    pre_result = await db.execute(pre_stmt)
    pre_record = pre_result.scalar_one_or_none()

    if pre_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Leakage record {record_id} not found",
                }
            },
        )

    if pre_record.status == "PENDING_FX_RATE":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": (
                        "Cannot accept a record with status PENDING_FX_RATE. "
                        "Upload the required FX rate first."
                    ),
                }
            },
        )

    try:
        record = await accept_leakage_record(
            record_id=record_id,
            user_id=current_user.user_id,
            tenant_id=tenant_id,
            db=db,
            notes=body.notes,
        )
    except ImmutabilityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "IMMUTABLE_RECORD",
                    "message": (
                        f"Leakage record {record_id} is already ACCEPTED "
                        f"and cannot be modified"
                    ),
                }
            },
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Leakage record {record_id} not found",
                }
            },
        )

    return {
        "id": str(record.id),
        "status": record.status,
        "reviewed_by": str(record.reviewed_by_user_id),
        "reviewed_at": str(record.reviewed_at),
        "review_notes": record.review_notes,
    }


# ── POST /records/{id}/reject — Reject a leakage record ───────────────


@router.post("/records/{record_id}/reject")
async def reject_record(
    record_id: uuid.UUID,
    body: ReviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reject a leakage record.

    Notes are REQUIRED on rejection — a reviewer must explain why.
    Returns 422 if notes are missing or empty.
    Already ACCEPTED → 409 IMMUTABLE_RECORD.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Reject requires notes — enforce at API level
    if not body.notes or not body.notes.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Notes are required when rejecting a leakage record",
                }
            },
        )

    try:
        record = await reject_leakage_record(
            record_id=record_id,
            user_id=current_user.user_id,
            tenant_id=tenant_id,
            db=db,
            notes=body.notes.strip(),
        )
    except ImmutabilityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "IMMUTABLE_RECORD",
                    "message": (
                        f"Leakage record {record_id} is already ACCEPTED "
                        f"and cannot be modified"
                    ),
                }
            },
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Leakage record {record_id} not found",
                }
            },
        )

    return {
        "id": str(record.id),
        "status": record.status,
        "reviewed_by": str(record.reviewed_by_user_id),
        "reviewed_at": str(record.reviewed_at),
        "review_notes": record.review_notes,
    }


# ── GET /summary — Aggregate leakage summary ──────────────────────────


@router.get("/summary")
async def get_leakage_summary(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    run_id: Optional[uuid.UUID] = Query(None),
    leakage_status: Optional[str] = Query(None, alias="status"),
) -> dict[str, Any]:
    """Get aggregate leakage summary for the tenant.

    Financial totals (total_leakage_amount) use ACCEPTED records only
    unless a specific status filter is applied. By-status counts
    include all records.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Base filter
    base_filter = [LeakageRecord.tenant_id == tenant_id]
    if run_id:
        base_filter.append(LeakageRecord.run_id == run_id)

    # ── Total leakage amount (ACCEPTED only unless status filter) ──
    amount_filter = list(base_filter)
    if leakage_status:
        amount_filter.append(LeakageRecord.status == leakage_status)
    else:
        amount_filter.append(LeakageRecord.status == "ACCEPTED")

    total_stmt = select(func.coalesce(func.sum(LeakageRecord.amount), 0)).where(
        *amount_filter
    )
    total_result = await db.execute(total_stmt)
    total_leakage = total_result.scalar() or Decimal("0")

    # ── By leakage_type breakdown ──────────────────────────────────
    type_stmt = (
        select(
            LeakageRecord.leakage_type,
            func.count().label("count"),
            func.coalesce(func.sum(LeakageRecord.amount), 0).label("total_amount"),
        )
        .where(*amount_filter)
        .group_by(LeakageRecord.leakage_type)
    )
    type_result = await db.execute(type_stmt)
    by_type = {
        row.leakage_type: {
            "count": row.count,
            "total_amount": float(row.total_amount),
        }
        for row in type_result.all()
    }

    # ── By status breakdown (all records, no ACCEPTED filter) ──────
    status_filter = list(base_filter)
    if leakage_status:
        status_filter.append(LeakageRecord.status == leakage_status)

    status_stmt = (
        select(
            LeakageRecord.status,
            func.count().label("count"),
        )
        .where(*status_filter)
        .group_by(LeakageRecord.status)
    )
    status_result = await db.execute(status_stmt)
    by_status = {row.status: row.count for row in status_result.all()}

    # ── By vendor breakdown (uses same filter as totals) ───────────
    vendor_stmt = (
        select(
            Vendor.id.label("vendor_id"),
            Vendor.normalized_name.label("vendor_name"),
            func.coalesce(func.sum(LeakageRecord.amount), 0).label("total_amount"),
            func.count().label("record_count"),
        )
        .select_from(LeakageRecord)
        .join(Invoice, LeakageRecord.invoice_id == Invoice.id)
        .join(Vendor, Invoice.vendor_id == Vendor.id)
        .where(*amount_filter)
        .group_by(Vendor.id, Vendor.normalized_name)
        .order_by(func.sum(LeakageRecord.amount).desc())
    )
    vendor_result = await db.execute(vendor_stmt)
    by_vendor = [
        {
            "vendor_id": str(row.vendor_id),
            "vendor_name": row.vendor_name,
            "total_amount": float(row.total_amount),
            "record_count": row.record_count,
        }
        for row in vendor_result.all()
    ]

    # ── Average confidence (same filter as totals) ─────────────────
    conf_stmt = select(func.avg(LeakageRecord.confidence)).where(*amount_filter)
    conf_result = await db.execute(conf_stmt)
    avg_confidence = conf_result.scalar()

    return {
        "total_leakage_amount": float(total_leakage),
        "currency": "INR",  # V1 base currency
        "by_type": by_type,
        "by_status": by_status,
        "by_vendor": by_vendor,
        "average_confidence": round(float(avg_confidence), 2) if avg_confidence else None,
    }
