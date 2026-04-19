"""
LeakSight V1 - Security Utilities (JWT decoding and user resolution).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, ExpiredSignatureError, jwt
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=True,
)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


class CurrentUser(BaseModel):
    """Authenticated user context extracted from JWT."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    tenant_id: UUID
    email: str
    role: str = "REVIEWER"


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "code": "UNAUTHORIZED",
                "message": message,
            }
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(
    user_id: UUID,
    tenant_id: UUID,
    email: str,
    role: str = "REVIEWER",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "role": role,
        "jti": str(uuid.uuid4()),
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a JWT signature and expiry."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            options={"require_exp": True},
        )
    except ExpiredSignatureError as exc:
        raise _unauthorized("Token expired") from exc
    except JWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    if "exp" not in payload:
        raise _unauthorized("Invalid or expired token")

    return payload


async def get_token_payload(token: str, db: AsyncSession) -> dict[str, Any]:
    """Decode a JWT and ensure its JTI has not been revoked."""
    payload = decode_jwt(token)
    jti = payload.get("jti")

    if not isinstance(jti, str) or not jti:
        raise _unauthorized("Token missing required fields")

    revoked = await db.execute(
        text("SELECT 1 FROM revoked_tokens WHERE jti = :jti"),
        {"jti": jti},
    )
    if revoked.scalar_one_or_none() is not None:
        raise _unauthorized("Token has been revoked")

    return payload


def extract_tenant_id(payload: dict[str, Any]) -> UUID:
    """Extract tenant_id from a decoded JWT payload."""
    tenant_id: str | None = payload.get("tenant_id")
    if not tenant_id:
        raise _unauthorized("Token missing tenant context")
    try:
        return UUID(tenant_id)
    except ValueError as exc:
        raise _unauthorized("Token missing tenant context") from exc


async def resolve_current_user(token: str, db: AsyncSession) -> CurrentUser:
    """Validate the token and return a typed authenticated user."""
    payload = await get_token_payload(token, db)

    user_id_str = payload.get("sub")
    tenant_id_str = payload.get("tenant_id")
    email = payload.get("email")

    if not user_id_str or not tenant_id_str or not email:
        raise _unauthorized("Token missing required fields")

    try:
        user_id = UUID(user_id_str)
        tenant_id = UUID(tenant_id_str)
    except ValueError as exc:
        raise _unauthorized(
            "Token contains invalid user or tenant identifiers"
        ) from exc

    return CurrentUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        role=payload.get("role", "REVIEWER"),
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency for authenticated user resolution."""
    return await resolve_current_user(token, db)
