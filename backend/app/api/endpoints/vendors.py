"""
LeakSight V1 — Vendor Endpoints

Source: docs/API_CONTRACTS.md (Section 5 — Vendor Endpoints)

Endpoints:
  GET  /api/v1/vendors              — List vendors with optional fuzzy search
  GET  /api/v1/vendors/{id}         — Get vendor with all aliases
  POST /api/v1/vendors/{id}/aliases — Add manual alias
  PUT  /api/v1/vendors/{id}/aliases/{alias_id}/deactivate — Deactivate alias
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.vendors import Vendor, VendorAlias

logger = get_logger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────


class AddAliasRequest(BaseModel):
    """Request schema for POST /vendors/{id}/aliases."""

    alias_name: str


# ── GET /vendors — List vendors ────────────────────────────────────────


@router.get("/")
async def list_vendors(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List vendors for the tenant with optional fuzzy search.

    When search is provided, uses ILIKE for name matching.
    pg_trgm similarity search can be added when the extension is available.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    base_filter = [Vendor.tenant_id == tenant_id]

    if search:
        base_filter.append(
            Vendor.normalized_name.ilike(f"%{search}%")
        )

    # Count query
    count_stmt = select(func.count()).select_from(Vendor).where(*base_filter)
    count_result = await db.execute(count_stmt)
    total_records = count_result.scalar() or 0
    total_pages = max(1, (total_records + page_size - 1) // page_size)

    # Data query with alias count subquery
    alias_count_sq = (
        select(func.count())
        .select_from(VendorAlias)
        .where(
            VendorAlias.vendor_id == Vendor.id,
            VendorAlias.is_active.is_(True),
        )
        .correlate(Vendor)
        .scalar_subquery()
    )

    data_stmt = (
        select(
            Vendor.id,
            Vendor.normalized_name,
            Vendor.raw_names_jsonb,
            Vendor.gst_id,
            Vendor.created_at,
            alias_count_sq.label("alias_count"),
        )
        .where(*base_filter)
        .order_by(Vendor.normalized_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(data_stmt)
    rows = result.all()

    data = [
        {
            "id": str(row.id),
            "normalized_name": row.normalized_name,
            "raw_names": row.raw_names_jsonb if row.raw_names_jsonb else [],
            "gst_id": row.gst_id,
            "alias_count": row.alias_count or 0,
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


# ── GET /vendors/{id} — Single vendor with aliases ────────────────────


@router.get("/{vendor_id}")
async def get_vendor(
    vendor_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a single vendor with all aliases.

    Cross-tenant returns 404, never 403.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Load vendor
    vendor_stmt = select(Vendor).where(
        Vendor.id == vendor_id,
        Vendor.tenant_id == tenant_id,
    )
    result = await db.execute(vendor_stmt)
    vendor = result.scalar_one_or_none()

    if vendor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Vendor {vendor_id} not found",
                }
            },
        )

    # Load aliases
    alias_stmt = (
        select(VendorAlias)
        .where(VendorAlias.vendor_id == vendor_id)
        .order_by(VendorAlias.created_at.desc())
    )
    alias_result = await db.execute(alias_stmt)
    aliases = alias_result.scalars().all()

    return {
        "id": str(vendor.id),
        "normalized_name": vendor.normalized_name,
        "raw_names": vendor.raw_names_jsonb if vendor.raw_names_jsonb else [],
        "gst_id": vendor.gst_id,
        "aliases": [
            {
                "id": str(a.id),
                "alias_name": a.alias_name,
                "override_source": a.override_source,
                "applied_by": str(a.applied_by_user_id) if a.applied_by_user_id else None,
                "is_active": a.is_active,
                "created_at": str(a.created_at) if a.created_at else None,
            }
            for a in aliases
        ],
        "created_at": str(vendor.created_at) if vendor.created_at else None,
    }


# ── POST /vendors/{id}/aliases — Add manual alias ─────────────────────


@router.post("/{vendor_id}/aliases", status_code=status.HTTP_201_CREATED)
async def add_vendor_alias(
    vendor_id: uuid.UUID,
    body: AddAliasRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add a manual alias for a vendor.

    Alias name is lowercased before storage. Duplicate alias for same
    tenant returns 409.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Verify vendor exists and belongs to tenant
    vendor_stmt = select(Vendor).where(
        Vendor.id == vendor_id,
        Vendor.tenant_id == tenant_id,
    )
    vendor_result = await db.execute(vendor_stmt)
    vendor = vendor_result.scalar_one_or_none()

    if vendor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Vendor {vendor_id} not found",
                }
            },
        )

    # Normalize alias name
    normalized_alias = body.alias_name.strip().lower()
    if not normalized_alias:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "alias_name cannot be empty",
                }
            },
        )

    # Check for duplicate alias in tenant
    dup_stmt = select(VendorAlias).where(
        VendorAlias.tenant_id == tenant_id,
        VendorAlias.alias_name == normalized_alias,
    )
    dup_result = await db.execute(dup_stmt)
    existing = dup_result.scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "DUPLICATE_RESOURCE",
                    "message": f"Alias '{normalized_alias}' already exists for this tenant",
                }
            },
        )

    alias = VendorAlias(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        alias_name=normalized_alias,
        override_source="MANUAL_REVIEW",
        applied_by_user_id=current_user.user_id,
    )
    db.add(alias)
    await db.flush()

    logger.info(
        "vendor_alias_added",
        vendor_id=str(vendor_id),
        alias_name=normalized_alias,
        tenant_id=str(tenant_id),
    )

    return {
        "id": str(alias.id),
        "vendor_id": str(vendor_id),
        "alias_name": alias.alias_name,
        "override_source": alias.override_source,
        "applied_by": str(current_user.user_id),
        "is_active": True,
        "created_at": str(alias.created_at) if alias.created_at else None,
    }


# ── PUT /vendors/{id}/aliases/{alias_id}/deactivate ───────────────────


@router.put("/{vendor_id}/aliases/{alias_id}/deactivate")
async def deactivate_alias(
    vendor_id: uuid.UUID,
    alias_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Deactivate a vendor alias. Sets is_active = false (not deleted)."""
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    alias_stmt = select(VendorAlias).where(
        VendorAlias.id == alias_id,
        VendorAlias.vendor_id == vendor_id,
        VendorAlias.tenant_id == tenant_id,
    )
    result = await db.execute(alias_stmt)
    alias = result.scalar_one_or_none()

    if alias is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Alias {alias_id} not found",
                }
            },
        )

    alias.is_active = False

    logger.info(
        "vendor_alias_deactivated",
        alias_id=str(alias_id),
        vendor_id=str(vendor_id),
        tenant_id=str(tenant_id),
    )

    return {
        "id": str(alias.id),
        "alias_name": alias.alias_name,
        "is_active": False,
        "deactivated_at": str(datetime.now(timezone.utc)),
    }
