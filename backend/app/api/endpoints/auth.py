"""
LeakSight V1 — Authentication Endpoints

Source: docs/API_CONTRACTS.md (Section 2 — Authentication Endpoints)

Endpoints:
  POST /api/v1/auth/token  — Authenticate and return JWT access token
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from passlib.hash import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import create_access_token
from backend.app.models.tenant import Tenant, TenantSettings, User, DEFAULT_ABBREVIATION_DICTIONARY

logger = get_logger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Request schema for POST /api/v1/auth/token."""

    email: str
    password: str
    tenant_name: str | None = None


class TokenResponse(BaseModel):
    """Response schema for POST /api/v1/auth/token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
    user: dict[str, Any]


@router.post("/token")
async def login_for_token(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate user and return JWT access token.

    For V1: if the user does not exist, creates the user and tenant
    automatically. This simplifies pilot onboarding. In production,
    this would be replaced with a proper registration flow.

    Args:
        request: Email, password, and optional tenant_name.
        db: Async database session.

    Returns:
        JWT access token with user details.

    Raises:
        HTTPException: 401 if credentials are invalid.
    """
    # Look up existing user by email
    stmt = select(User).where(User.email == request.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is not None:
        # Verify password
        if not bcrypt.verify(request.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Invalid credentials",
                    }
                },
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Account is deactivated",
                    }
                },
            )

        # Load tenant name for response
        tenant_stmt = select(Tenant).where(Tenant.id == user.tenant_id)
        tenant_result = await db.execute(tenant_stmt)
        tenant = tenant_result.scalar_one_or_none()
        tenant_name = tenant.name if tenant else "Unknown"

        # Create access token
        token = create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role if isinstance(user.role, str) else user.role,
        )

        logger.info(
            "user_login_success",
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
        )

        return TokenResponse(
            access_token=token,
            user={
                "id": str(user.id),
                "email": user.email,
                "role": user.role if isinstance(user.role, str) else user.role,
                "tenant_id": str(user.tenant_id),
                "tenant_name": tenant_name,
            },
        )

    # --- V1 auto-registration: create tenant + user if not found ---
    tenant_name_val = request.tenant_name or "Default Tenant"

    # Create tenant
    tenant = Tenant(name=tenant_name_val)
    db.add(tenant)
    await db.flush()

    # Create tenant_settings with defaults
    tenant_settings = TenantSettings(
        tenant_id=tenant.id,
        abbreviation_dictionary=DEFAULT_ABBREVIATION_DICTIONARY,
        fuzzy_threshold=0.85,
        duplicate_window_days=30,
        manual_review_threshold=0.70,
        base_currency="INR",
    )
    db.add(tenant_settings)

    # Create user with hashed password
    password_hash = bcrypt.hash(request.password)
    user = User(
        tenant_id=tenant.id,
        email=request.email,
        password_hash=password_hash,
        role="ADMIN",
    )
    db.add(user)
    await db.flush()

    # Create access token
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        email=user.email,
        role="ADMIN",
    )

    logger.info(
        "user_auto_registered",
        user_id=str(user.id),
        tenant_id=str(tenant.id),
    )

    return TokenResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "role": "ADMIN",
            "tenant_id": str(tenant.id),
            "tenant_name": tenant_name_val,
        },
    )
