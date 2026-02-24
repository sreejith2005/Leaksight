"""
LeakSight V1 — Security Utilities (JWT Decoding & Tenant Extraction)

Source: docs/API_CONTRACTS.md (Section 1 — Authentication), docs/CLAUDE.md
       docs/ARCHITECTURE.md (auth dependency injection pattern)

Phase 6: Real JWT implementation using python-jose. Replaces Phase 1 stubs.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.database import get_db

# OAuth2 scheme — token URL matches the auth endpoint path
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=True,
)

# JWT algorithm — HS256 is sufficient for single-server V1
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours


class CurrentUser(BaseModel):
    """Authenticated user context extracted from JWT.

    Every protected route receives this as a dependency.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    tenant_id: UUID
    email: str
    role: str = "REVIEWER"


def create_access_token(
    user_id: UUID,
    tenant_id: UUID,
    email: str,
    role: str = "REVIEWER",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: UUID of the authenticated user.
        tenant_id: UUID of the user's tenant.
        email: User email address.
        role: User role (ADMIN or REVIEWER).
        expires_delta: Optional custom expiration. Defaults to 24 hours.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Args:
        token: The raw JWT string from the Authorization header.

    Returns:
        Decoded JWT payload containing sub, tenant_id, email, role, exp.

    Raises:
        HTTPException: 401 if token is invalid, expired, or malformed.

    Note:
        Never logs the token value itself per logging rules.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Invalid or expired token",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_tenant_id(payload: dict[str, Any]) -> UUID:
    """Extract tenant_id from a decoded JWT payload.

    Args:
        payload: Decoded JWT payload dictionary.

    Returns:
        The tenant_id as UUID type.

    Raises:
        HTTPException: 401 if tenant_id is missing from the payload.
    """
    tenant_id: str | None = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Token missing tenant context",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return UUID(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Token missing tenant context",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency that extracts and validates the current user.

    Decodes the JWT, extracts user_id, tenant_id, and email,
    and returns a CurrentUser instance. Used in every protected route.

    Args:
        token: Bearer token string from the Authorization header.
        db: Async database session (available for future user validation).

    Returns:
        CurrentUser instance with user_id, tenant_id, email, role.

    Raises:
        HTTPException: 401 if token is invalid, expired, missing fields.
    """
    payload = decode_jwt(token)

    user_id_str = payload.get("sub")
    tenant_id_str = payload.get("tenant_id")
    email = payload.get("email")

    if not user_id_str or not tenant_id_str or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Token missing required fields",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(user_id_str)
        tenant_id = UUID(tenant_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Token contains invalid user or tenant identifiers",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        role=payload.get("role", "REVIEWER"),
    )
