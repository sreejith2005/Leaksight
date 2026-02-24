"""
LeakSight V1 — Admin Endpoints

Source: docs/API_CONTRACTS.md (Section 8 — Admin Endpoints)

Endpoints:
  POST /api/v1/admin/fx-rates/upload    — Bulk upload FX rates (ADMIN only)
  GET  /api/v1/admin/fx-rates           — List FX rates
  PUT  /api/v1/admin/tenant-settings    — Update tenant settings (ADMIN only)
  GET  /api/v1/admin/tenant-settings    — Get current tenant settings
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.tenant import DEFAULT_ABBREVIATION_DICTIONARY, TenantSettings
from backend.app.models.units import FxRate

logger = get_logger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────


class FxRateItem(BaseModel):
    """Single FX rate in upload request."""

    from_currency: str
    to_currency: str
    rate: Decimal
    rate_date: date
    source: str = "MANUAL_UPLOAD"


class FxRateUploadRequest(BaseModel):
    """Request schema for POST /admin/fx-rates/upload."""

    rates: list[FxRateItem]


class TenantSettingsUpdate(BaseModel):
    """Request schema for PUT /admin/tenant-settings."""

    fuzzy_threshold: Optional[float] = None
    duplicate_window_days: Optional[int] = None
    manual_review_threshold: Optional[float] = None
    base_currency: Optional[str] = None
    abbreviation_dictionary_additions: Optional[dict[str, str]] = None


# ── Helper: require ADMIN role ─────────────────────────────────────────


def _require_admin(current_user: CurrentUser) -> None:
    """Raise 403 if user is not ADMIN."""
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "This endpoint requires ADMIN role",
                }
            },
        )


# ── POST /fx-rates/upload — Bulk upload FX rates ──────────────────────


@router.post("/fx-rates/upload", status_code=status.HTTP_201_CREATED)
async def upload_fx_rates(
    body: FxRateUploadRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bulk upload FX rates. ADMIN only.

    After uploading, PENDING_FX_RATE leakage records may become
    resolvable on the next analysis run.
    """
    _require_admin(current_user)

    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    if not body.rates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "rates list must not be empty",
                }
            },
        )

    uploaded = []
    for rate_item in body.rates:
        fx_rate = FxRate(
            tenant_id=tenant_id,
            from_currency=rate_item.from_currency.upper(),
            to_currency=rate_item.to_currency.upper(),
            rate=rate_item.rate,
            rate_date=rate_item.rate_date,
            source=rate_item.source,
            uploaded_by_user_id=current_user.user_id,
        )
        db.add(fx_rate)
        uploaded.append(fx_rate)

    await db.flush()

    logger.info(
        "fx_rates_uploaded",
        count=len(uploaded),
        tenant_id=str(tenant_id),
    )

    return {
        "uploaded_count": len(uploaded),
        "rates": [
            {
                "id": str(r.id) if r.id else None,
                "from_currency": r.from_currency,
                "to_currency": r.to_currency,
                "rate": float(r.rate),
                "rate_date": str(r.rate_date),
            }
            for r in uploaded
        ],
    }


# ── GET /fx-rates — List FX rates ─────────────────────────────────────


@router.get("/fx-rates")
async def list_fx_rates(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    from_currency: Optional[str] = Query(None),
    to_currency: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List FX rates for the tenant."""
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    base_filter = [FxRate.tenant_id == tenant_id]

    if from_currency:
        base_filter.append(FxRate.from_currency == from_currency.upper())
    if to_currency:
        base_filter.append(FxRate.to_currency == to_currency.upper())
    if date_from:
        base_filter.append(FxRate.rate_date >= date_from)
    if date_to:
        base_filter.append(FxRate.rate_date <= date_to)

    # Count
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(FxRate).where(*base_filter)
    count_result = await db.execute(count_stmt)
    total_records = count_result.scalar() or 0
    total_pages = max(1, (total_records + page_size - 1) // page_size)

    # Data
    data_stmt = (
        select(FxRate)
        .where(*base_filter)
        .order_by(FxRate.rate_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(data_stmt)
    rates = result.scalars().all()

    return {
        "data": [
            {
                "id": str(r.id),
                "from_currency": r.from_currency,
                "to_currency": r.to_currency,
                "rate": float(r.rate),
                "rate_date": str(r.rate_date),
                "source": r.source,
                "uploaded_by": str(r.uploaded_by_user_id) if r.uploaded_by_user_id else None,
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in rates
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


# ── PUT /tenant-settings — Update tenant settings ─────────────────────


@router.put("/tenant-settings")
async def update_tenant_settings(
    body: TenantSettingsUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update tenant-specific settings. ADMIN only.

    abbreviation_dictionary_additions are MERGED into existing dict.
    System defaults cannot be removed.
    """
    _require_admin(current_user)

    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Load settings
    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Tenant settings not found",
                }
            },
        )

    # Update scalar fields if provided
    if body.fuzzy_threshold is not None:
        settings.fuzzy_threshold = body.fuzzy_threshold
    if body.duplicate_window_days is not None:
        settings.duplicate_window_days = body.duplicate_window_days
    if body.manual_review_threshold is not None:
        settings.manual_review_threshold = body.manual_review_threshold
    if body.base_currency is not None:
        settings.base_currency = body.base_currency

    # Merge abbreviation dictionary additions
    if body.abbreviation_dictionary_additions:
        current_dict = dict(settings.abbreviation_dictionary or {})
        # Ensure system defaults are preserved
        for key, value in DEFAULT_ABBREVIATION_DICTIONARY.items():
            current_dict.setdefault(key, value)
        # Merge additions
        current_dict.update(body.abbreviation_dictionary_additions)
        settings.abbreviation_dictionary = current_dict

    await db.flush()

    logger.info(
        "tenant_settings_updated",
        tenant_id=str(tenant_id),
    )

    return {
        "tenant_id": str(tenant_id),
        "fuzzy_threshold": settings.fuzzy_threshold,
        "duplicate_window_days": settings.duplicate_window_days,
        "manual_review_threshold": settings.manual_review_threshold,
        "base_currency": settings.base_currency,
        "abbreviation_dictionary": settings.abbreviation_dictionary,
        "updated_at": str(datetime.now(timezone.utc)),
    }


# ── GET /tenant-settings — Get current settings ───────────────────────


@router.get("/tenant-settings")
async def get_tenant_settings(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get current tenant settings."""
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Tenant settings not found",
                }
            },
        )

    return {
        "tenant_id": str(tenant_id),
        "fuzzy_threshold": settings.fuzzy_threshold,
        "duplicate_window_days": settings.duplicate_window_days,
        "manual_review_threshold": settings.manual_review_threshold,
        "base_currency": settings.base_currency,
        "abbreviation_dictionary": settings.abbreviation_dictionary,
        "updated_at": str(settings.updated_at) if hasattr(settings, "updated_at") and settings.updated_at else None,
    }
