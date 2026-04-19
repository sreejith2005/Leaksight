"""
LeakSight V1 - Authentication Endpoints

Endpoints:
  POST /api/v1/auth/token   - Authenticate and return JWT access token
  POST /api/v1/auth/logout  - Revoke the current JWT access token
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from passlib.hash import bcrypt
from pydantic import BaseModel
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_token_payload,
    oauth2_scheme,
)
from backend.app.models.tenant import Tenant, User

logger = get_logger(__name__)

router = APIRouter()

RATE_LIMIT_WINDOW = timedelta(minutes=15)
RATE_LIMIT_DELAY_THRESHOLD = 5
RATE_LIMIT_LOCKOUT_THRESHOLD = 10
RATE_LIMIT_DELAY_SECONDS = 3
AUTH_SENTINEL_UUID = uuid.UUID(int=0)

FAILED_LOGIN_ATTEMPTS: dict[str, list[datetime]] = {}
_FAILED_LOGIN_ATTEMPTS_LOCK = Lock()

_sync_engine = create_engine(
    get_settings().database_url_sync,
    future=True,
    pool_pre_ping=True,
)
_sync_session_factory = sessionmaker(
    bind=_sync_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class LoginRequest(BaseModel):
    """Request schema for POST /api/v1/auth/token."""

    email: str
    password: str
    tenant_name: str | None = None


class TokenResponse(BaseModel):
    """Response schema for POST /api/v1/auth/token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    user: dict[str, Any]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        forwarded_ip = forwarded_for.split(",")[0].strip()
        if forwarded_ip:
            return forwarded_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _invalid_credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid email or password",
            }
        },
    )


def _prune_failed_attempts(client_ip: str, now: datetime) -> list[datetime]:
    cutoff = now - RATE_LIMIT_WINDOW
    attempts = [
        attempt
        for attempt in FAILED_LOGIN_ATTEMPTS.get(client_ip, [])
        if attempt >= cutoff
    ]
    if attempts:
        FAILED_LOGIN_ATTEMPTS[client_ip] = attempts
    else:
        FAILED_LOGIN_ATTEMPTS.pop(client_ip, None)
    return attempts


def _record_failed_attempt(client_ip: str, now: datetime) -> None:
    with _FAILED_LOGIN_ATTEMPTS_LOCK:
        attempts = _prune_failed_attempts(client_ip, now)
        attempts.append(now)
        FAILED_LOGIN_ATTEMPTS[client_ip] = attempts


def _clear_failed_attempts(client_ip: str, now: datetime) -> None:
    with _FAILED_LOGIN_ATTEMPTS_LOCK:
        _prune_failed_attempts(client_ip, now)
        FAILED_LOGIN_ATTEMPTS.pop(client_ip, None)


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _write_audit_log(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    details_jsonb: dict[str, Any],
) -> None:
    with _sync_session_factory() as sync_db:
        sync_db: Session
        try:
            sync_db.execute(text("SET LOCAL ROLE app_admin"))
            sync_db.execute(
                text(
                    """
                    INSERT INTO audit_logs (
                        tenant_id,
                        user_id,
                        action,
                        resource_type,
                        resource_id,
                        details_jsonb
                    ) VALUES (
                        :tenant_id,
                        :user_id,
                        :action,
                        :resource_type,
                        :resource_id,
                        CAST(:details_jsonb AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "user_id": str(user_id),
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id),
                    "details_jsonb": json.dumps(details_jsonb),
                },
            )
            sync_db.commit()
        except Exception:
            sync_db.rollback()
            logger.exception("auth_audit_log_write_failed", action=action)


def _check_rate_limit(client_ip: str) -> None:
    now = _utcnow()
    with _FAILED_LOGIN_ATTEMPTS_LOCK:
        attempts = _prune_failed_attempts(client_ip, now)
        count = len(attempts)

    if count >= RATE_LIMIT_LOCKOUT_THRESHOLD:
        _write_audit_log(
            tenant_id=AUTH_SENTINEL_UUID,
            user_id=AUTH_SENTINEL_UUID,
            action="LOGIN_BLOCKED_RATE_LIMIT",
            resource_type="auth",
            resource_id=AUTH_SENTINEL_UUID,
            details_jsonb={"ip": client_ip, "attempt_count": count},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many failed login attempts. Try again in 15 minutes.",
                }
            },
        )

    if count >= RATE_LIMIT_DELAY_THRESHOLD:
        time.sleep(RATE_LIMIT_DELAY_SECONDS)


@router.post("/token")
async def login_for_token(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate user and return JWT access token."""
    client_ip = _get_client_ip(http_request)
    _check_rate_limit(client_ip)

    stmt = select(User).where(User.email == request.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        _record_failed_attempt(client_ip, _utcnow())
        _write_audit_log(
            tenant_id=AUTH_SENTINEL_UUID,
            user_id=AUTH_SENTINEL_UUID,
            action="LOGIN_FAILED",
            resource_type="auth",
            resource_id=AUTH_SENTINEL_UUID,
            details_jsonb={
                "ip": client_ip,
                "email_attempted": _hash_email(request.email),
                "reason": "UNKNOWN_EMAIL",
            },
        )
        raise _invalid_credentials_exception()

    if not bcrypt.verify(request.password, user.password_hash):
        _record_failed_attempt(client_ip, _utcnow())
        _write_audit_log(
            tenant_id=AUTH_SENTINEL_UUID,
            user_id=AUTH_SENTINEL_UUID,
            action="LOGIN_FAILED",
            resource_type="auth",
            resource_id=AUTH_SENTINEL_UUID,
            details_jsonb={
                "ip": client_ip,
                "email_attempted": _hash_email(request.email),
                "reason": "WRONG_PASSWORD",
            },
        )
        raise _invalid_credentials_exception()

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

    tenant_stmt = select(Tenant).where(Tenant.id == user.tenant_id)
    tenant_result = await db.execute(tenant_stmt)
    tenant = tenant_result.scalar_one_or_none()
    tenant_name = tenant.name if tenant else "Unknown"

    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role if isinstance(user.role, str) else user.role,
    )

    _clear_failed_attempts(client_ip, _utcnow())
    _write_audit_log(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="LOGIN_SUCCESS",
        resource_type="auth",
        resource_id=AUTH_SENTINEL_UUID,
        details_jsonb={"ip": client_ip},
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


@router.post("/logout")
async def logout(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Revoke the current JWT access token."""
    payload = await get_token_payload(token, db)
    jti = payload.get("jti")
    exp_value = payload.get("exp")

    if not isinstance(jti, str) or not jti:
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

    if isinstance(exp_value, (int, float)):
        expires_at = datetime.fromtimestamp(exp_value, tz=timezone.utc)
    else:
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

    existing = await db.execute(
        text("SELECT 1 FROM revoked_tokens WHERE jti = :jti"),
        {"jti": jti},
    )
    if existing.scalar_one_or_none() is None:
        await db.execute(
            text(
                """
                INSERT INTO revoked_tokens (jti, expires_at)
                VALUES (:jti, :expires_at)
                """
            ),
            {"jti": jti, "expires_at": expires_at},
        )

    return {"message": "Logged out successfully"}
