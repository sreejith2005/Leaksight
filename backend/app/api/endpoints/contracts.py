"""
LeakSight V1 — Contract Endpoints

Source: docs/API_CONTRACTS.md (Section 6 — Contract Endpoints)

Endpoints:
  GET  /api/v1/contracts                 — List contracts with active versions
  GET  /api/v1/contracts/{id}/versions   — List all versions of a contract
  POST /api/v1/contracts                 — Create contract with first version + line items
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.contracts import Contract, ContractLineItem, ContractVersion
from backend.app.models.vendors import Vendor

logger = get_logger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────


class LineItemCreate(BaseModel):
    """Schema for a contract line item in creation request."""

    item_desc: str
    unit: str
    unit_price: Decimal
    currency: str = "INR"


class VersionCreate(BaseModel):
    """Schema for a contract version in creation request."""

    valid_from: date
    valid_to: date
    line_items: list[LineItemCreate]


class ContractCreate(BaseModel):
    """Request schema for POST /contracts."""

    vendor_id: uuid.UUID
    contract_ref: Optional[str] = None
    source_document_id: Optional[uuid.UUID] = None
    version: VersionCreate


# ── GET /contracts — List contracts ────────────────────────────────────


@router.get("/")
async def list_contracts(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    vendor_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List contracts with their current active versions."""
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    base_filter = [Contract.tenant_id == tenant_id]
    if vendor_id:
        base_filter.append(Contract.vendor_id == vendor_id)

    # Count
    count_stmt = select(func.count()).select_from(Contract).where(*base_filter)
    count_result = await db.execute(count_stmt)
    total_records = count_result.scalar() or 0
    total_pages = max(1, (total_records + page_size - 1) // page_size)

    # Data — join Vendor for name, subquery for latest version
    latest_version_sq = (
        select(
            ContractVersion.contract_id,
            func.max(ContractVersion.version_number).label("max_version"),
        )
        .group_by(ContractVersion.contract_id)
        .subquery()
    )

    data_stmt = (
        select(
            Contract.id,
            Contract.vendor_id,
            Vendor.normalized_name.label("vendor_name"),
            Contract.contract_ref,
            Contract.created_at,
            latest_version_sq.c.max_version.label("latest_version_number"),
        )
        .join(Vendor, Contract.vendor_id == Vendor.id)
        .outerjoin(
            latest_version_sq,
            Contract.id == latest_version_sq.c.contract_id,
        )
        .where(*base_filter)
        .order_by(Contract.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(data_stmt)
    rows = result.all()

    # For each contract, get the active version details
    data = []
    for row in rows:
        active_version = None
        total_versions = 0

        if row.latest_version_number is not None:
            # Count versions
            ver_count_stmt = (
                select(func.count())
                .select_from(ContractVersion)
                .where(ContractVersion.contract_id == row.id)
            )
            ver_count_result = await db.execute(ver_count_stmt)
            total_versions = ver_count_result.scalar() or 0

            # Get the latest version details
            ver_stmt = select(ContractVersion).where(
                ContractVersion.contract_id == row.id,
                ContractVersion.version_number == row.latest_version_number,
            )
            ver_result = await db.execute(ver_stmt)
            version = ver_result.scalar_one_or_none()

            if version:
                # Count line items
                li_count_stmt = (
                    select(func.count())
                    .select_from(ContractLineItem)
                    .where(ContractLineItem.contract_version_id == version.id)
                )
                li_count_result = await db.execute(li_count_stmt)
                li_count = li_count_result.scalar() or 0

                active_version = {
                    "version_number": version.version_number,
                    "valid_from": str(version.valid_from),
                    "valid_to": str(version.valid_to),
                    "line_item_count": li_count,
                }

        data.append({
            "id": str(row.id),
            "vendor_id": str(row.vendor_id),
            "vendor_name": row.vendor_name,
            "contract_ref": row.contract_ref,
            "active_version": active_version,
            "total_versions": total_versions,
            "created_at": str(row.created_at) if row.created_at else None,
        })

    return {
        "data": data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


# ── GET /contracts/{id}/versions — List versions ──────────────────────


@router.get("/{contract_id}/versions")
async def get_contract_versions(
    contract_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all versions of a contract with line items."""
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Load contract
    contract_stmt = select(Contract).where(
        Contract.id == contract_id,
        Contract.tenant_id == tenant_id,
    )
    contract_result = await db.execute(contract_stmt)
    contract = contract_result.scalar_one_or_none()

    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Contract {contract_id} not found",
                }
            },
        )

    # Get vendor name
    vendor_stmt = select(Vendor.normalized_name).where(Vendor.id == contract.vendor_id)
    vendor_result = await db.execute(vendor_stmt)
    vendor_name = vendor_result.scalar() or "Unknown"

    # Load all versions
    versions_stmt = (
        select(ContractVersion)
        .where(ContractVersion.contract_id == contract_id)
        .order_by(ContractVersion.version_number)
    )
    ver_result = await db.execute(versions_stmt)
    versions = ver_result.scalars().all()

    versions_data = []
    for v in versions:
        # Load line items for this version
        li_stmt = (
            select(ContractLineItem)
            .where(ContractLineItem.contract_version_id == v.id)
        )
        li_result = await db.execute(li_stmt)
        line_items = li_result.scalars().all()

        versions_data.append({
            "id": str(v.id),
            "version_number": v.version_number,
            "valid_from": str(v.valid_from),
            "valid_to": str(v.valid_to),
            "line_items": [
                {
                    "id": str(li.id),
                    "item_desc": li.item_desc,
                    "unit": li.unit,
                    "unit_price": float(li.unit_price),
                    "currency": li.currency,
                }
                for li in line_items
            ],
        })

    return {
        "contract_id": str(contract_id),
        "vendor_name": vendor_name,
        "contract_ref": contract.contract_ref,
        "versions": versions_data,
    }


# ── POST /contracts — Create contract ─────────────────────────────────


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_contract(
    body: ContractCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new contract with first version and line items (atomic).

    Validates vendor exists, date range is valid, and at least one
    line item is provided.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # Validate vendor exists and belongs to tenant
    vendor_stmt = select(Vendor).where(
        Vendor.id == body.vendor_id,
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
                    "message": f"Vendor {body.vendor_id} not found",
                }
            },
        )

    # Validate date range
    if body.version.valid_from >= body.version.valid_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "valid_from must be before valid_to",
                }
            },
        )

    # Validate line items
    if not body.version.line_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "At least one line item is required",
                }
            },
        )

    # Create contract
    contract = Contract(
        tenant_id=tenant_id,
        vendor_id=body.vendor_id,
        contract_ref=body.contract_ref,
        source_document_id=body.source_document_id,
    )
    db.add(contract)
    await db.flush()

    # Create version
    version = ContractVersion(
        contract_id=contract.id,
        tenant_id=tenant_id,
        version_number=1,
        valid_from=body.version.valid_from,
        valid_to=body.version.valid_to,
    )
    db.add(version)
    await db.flush()

    # Create line items
    for li in body.version.line_items:
        line_item = ContractLineItem(
            contract_version_id=version.id,
            tenant_id=tenant_id,
            item_desc=li.item_desc.strip().lower(),
            raw_item_desc=li.item_desc,
            unit=li.unit,
            unit_price=li.unit_price,
            currency=li.currency,
        )
        db.add(line_item)

    await db.flush()

    logger.info(
        "contract_created",
        contract_id=str(contract.id),
        vendor_id=str(body.vendor_id),
        tenant_id=str(tenant_id),
        line_items=len(body.version.line_items),
    )

    return {
        "id": str(contract.id),
        "vendor_id": str(body.vendor_id),
        "contract_ref": body.contract_ref,
        "version": {
            "id": str(version.id),
            "version_number": 1,
            "valid_from": str(body.version.valid_from),
            "valid_to": str(body.version.valid_to),
            "line_item_count": len(body.version.line_items),
        },
        "created_at": str(contract.created_at) if contract.created_at else None,
    }
