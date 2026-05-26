"""
LeakSight V1 — Notification Endpoints

Source: docs/API_CONTRACTS.md (Section 10 — Notification Endpoints)

Endpoints:
  GET  /api/v1/notifications              — List notifications for current user
  PUT  /api/v1/notifications/{id}/read    — Mark single notification as read
  POST /api/v1/notifications/read-all     — Mark all unread notifications as read

Phase 8: In-app notification retrieval and read-status management.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.notifications import Notification
from backend.app.services.notification_service import mark_notification_read

logger = get_logger(__name__)

router = APIRouter()


# ── GET / — List notifications ────────────────────────────────────────


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False, description="Return only unread notifications"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List notifications for the current user.

    Supports filtering by unread_only and standard offset/limit pagination.
    Only returns IN_APP notifications (EMAIL notifications are delivery records).

    Returns:
        JSON with data array, pagination metadata, and unread_count.
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.user_id

    await set_tenant_context(db, tenant_id)

    # Build query for IN_APP notifications only
    query = select(Notification).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
        Notification.channel == "IN_APP",
    )

    if unread_only:
        query = query.where(Notification.is_read == False)  # noqa: E712

    # Count total matching
    count_query = select(func.count()).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
        Notification.channel == "IN_APP",
    )
    if unread_only:
        count_query = count_query.where(Notification.is_read == False)  # noqa: E712

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Count unread (always provided regardless of filter)
    unread_query = select(func.count()).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
        Notification.channel == "IN_APP",
        Notification.is_read == False,  # noqa: E712
    )
    unread_result = await db.execute(unread_query)
    unread_count = unread_result.scalar() or 0

    # Fetch paginated results
    query = query.order_by(Notification.created_at.desc())
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    notifications = list(result.scalars().all())

    data = [
        {
            "id": str(n.id),
            "message": n.message,
            "notification_type": n.notification_type,
            "run_id": str(n.run_id) if n.run_id else None,
            "is_read": n.is_read,
            "read_at": n.read_at.isoformat() if n.read_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifications
    ]

    logger.info(
        "notifications_listed",
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        count=len(data),
        component="notification_endpoints",
    )

    return {
        "data": data,
        "pagination": {
            "total": total,
            "skip": skip,
            "limit": limit,
        },
        "unread_count": unread_count,
    }


# ── PUT /{id}/read — Mark single notification as read ───────────────


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark a single notification as read.

    Sets is_read to True and records read_at timestamp.

    Returns:
        JSON with notification id and read_at timestamp.

    Raises:
        404 if notification not found or doesn't belong to this user.
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.user_id

    await set_tenant_context(db, tenant_id)

    try:
        notification = await mark_notification_read(
            notification_id=notification_id,
            user_id=user_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    await db.commit()

    logger.info(
        "notification_marked_read",
        notification_id=str(notification_id),
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        component="notification_endpoints",
    )

    return {
        "id": str(notification.id),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }


# ── POST /read-all — Mark all notifications as read ─────────────────


@router.post("/read-all")
async def mark_all_read(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark all unread IN_APP notifications as read for the current user.

    Bulk update — sets is_read to True and read_at to now() for all
    unread notifications belonging to this user.

    Returns:
        JSON with count of notifications marked as read.
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.user_id

    await set_tenant_context(db, tenant_id)

    now = datetime.now(timezone.utc)

    stmt = (
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.channel == "IN_APP",
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True, read_at=now)
    )

    result = await db.execute(stmt)
    updated_count = result.rowcount

    await db.commit()

    logger.info(
        "notifications_marked_all_read",
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        count=updated_count,
        component="notification_endpoints",
    )

    return {
        "marked_read_count": updated_count,
    }
