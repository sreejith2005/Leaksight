"""
Tests for LeakSight V1 — Authentication & Security

Source: docs/API_CONTRACTS.md (Section 1 — Authentication),
       docs/CLAUDE.md (error format, auth rules)

Tests:
1. create_access_token → valid JWT with correct claims
2. decode_jwt → valid token returns correct payload
3. decode_jwt → expired token raises 401
4. decode_jwt → tampered signature raises 401
5. get_current_user → valid JWT returns CurrentUser
6. get_current_user → missing tenant_id → 401
7. get_current_user → missing Authorization header → 401
8. POST /token → new user auto-registers (V1)
9. POST /token → existing user valid password → 200
10. POST /token → existing user wrong password → 401
11. POST /token → deactivated user → 401
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from backend.app.core.security import (
    ALGORITHM,
    CurrentUser,
    create_access_token,
    decode_jwt,
    extract_tenant_id,
    get_current_user,
)
from backend.app.core.config import get_settings

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
EMAIL = "admin@test.com"


def _secret_key() -> str:
    """Return the actual secret key used by the application."""
    return get_settings().secret_key


# ── Helpers ────────────────────────────────────────────────────────────


def _make_token(
    user_id: uuid.UUID = USER_ID,
    tenant_id: uuid.UUID = TENANT_ID,
    email: str = EMAIL,
    role: str = "ADMIN",
    expires_delta: timedelta | None = None,
    secret: str | None = None,
) -> str:
    """Create a JWT for testing purposes."""
    if secret is None:
        secret = _secret_key()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=24)
    )
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jose_jwt.encode(payload, secret, algorithm=ALGORITHM)


# ── Test 1: create_access_token produces valid JWT ────────────────────


def test_create_access_token_valid():
    """create_access_token produces a JWT with correct claims."""
    token = create_access_token(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        email=EMAIL,
        role="ADMIN",
    )

    payload = jose_jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    assert payload["sub"] == str(USER_ID)
    assert payload["tenant_id"] == str(TENANT_ID)
    assert payload["email"] == EMAIL
    assert payload["role"] == "ADMIN"
    assert "exp" in payload


# ── Test 2: decode_jwt with valid token ───────────────────────────────


def test_decode_jwt_valid():
    """decode_jwt returns correct payload for a valid token."""
    token = _make_token()
    payload = decode_jwt(token)

    assert payload["sub"] == str(USER_ID)
    assert payload["tenant_id"] == str(TENANT_ID)
    assert payload["email"] == EMAIL
    assert payload["role"] == "ADMIN"


# ── Test 3: decode_jwt with expired token → 401 ──────────────────────


def test_decode_jwt_expired():
    """decode_jwt raises 401 for an expired token."""
    token = _make_token(expires_delta=timedelta(seconds=-10))

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(token)

    assert exc_info.value.status_code == 401
    assert "Invalid or expired token" in str(exc_info.value.detail)


# ── Test 4: decode_jwt with tampered signature → 401 ─────────────────


def test_decode_jwt_tampered_signature():
    """decode_jwt raises 401 for a token signed with wrong secret."""
    token = _make_token(secret="wrong-secret-key-not-the-real-one")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        decode_jwt(token)

    assert exc_info.value.status_code == 401
    assert "Invalid or expired token" in str(exc_info.value.detail)


# ── Test 5: get_current_user with valid JWT → CurrentUser ─────────────


@pytest.mark.asyncio
async def test_get_current_user_valid():
    """get_current_user returns CurrentUser for a valid JWT."""
    token = _make_token()
    db = AsyncMock()

    user = await get_current_user(token=token, db=db)

    assert isinstance(user, CurrentUser)
    assert user.user_id == USER_ID
    assert user.tenant_id == TENANT_ID
    assert user.email == EMAIL
    assert user.role == "ADMIN"


# ── Test 6: get_current_user with missing tenant_id → 401 ────────────


@pytest.mark.asyncio
async def test_get_current_user_missing_tenant():
    """get_current_user raises 401 when tenant_id is missing from token."""
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {
        "sub": str(USER_ID),
        # no tenant_id
        "email": EMAIL,
        "role": "ADMIN",
        "exp": expire,
    }
    token = jose_jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)
    db = AsyncMock()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db)

    assert exc_info.value.status_code == 401
    assert "Token missing required fields" in str(exc_info.value.detail)


# ── Test 7: Missing Authorization header → 401 ───────────────────────


def test_missing_authorization_header():
    """Request without Authorization header returns 401."""
    from backend.app.core.database import get_db

    app = FastAPI()
    db_mock = AsyncMock()

    @app.get("/protected")
    async def protected_route(
        current_user: CurrentUser = pytest.importorskip("fastapi").Depends(
            get_current_user
        ),
    ):
        return {"user": str(current_user.user_id)}

    async def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    response = client.get("/protected")

    assert response.status_code == 401


# ── Test 8: extract_tenant_id valid ───────────────────────────────────


def test_extract_tenant_id_valid():
    """extract_tenant_id returns UUID for a valid payload."""
    payload = {"tenant_id": str(TENANT_ID)}
    result = extract_tenant_id(payload)
    assert result == TENANT_ID


# ── Test 9: extract_tenant_id missing → 401 ──────────────────────────


def test_extract_tenant_id_missing():
    """extract_tenant_id raises 401 when tenant_id is missing."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        extract_tenant_id({})

    assert exc_info.value.status_code == 401
    assert "Token missing tenant context" in str(exc_info.value.detail)


# ── Test 10: POST /token auto-registers new user (V1) ────────────────


def test_login_auto_register():
    """POST /token with unknown email auto-registers user and tenant."""
    from backend.app.api.endpoints.auth import router as auth_router
    from backend.app.core.database import get_db

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth")

    db = AsyncMock()

    # User lookup: not found
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = None
    db.execute.return_value = user_result

    # flush will assign IDs via side_effect
    flush_call_count = 0

    async def _flush_side_effect():
        nonlocal flush_call_count
        flush_call_count += 1
        # After first flush (tenant), set tenant.id
        # After second flush (user), set user.id
        for call in db.add.call_args_list:
            obj = call[0][0]
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()
            if hasattr(obj, "tenant_id") and obj.tenant_id is None:
                # TenantSettings gets tenant_id from tenant
                pass

    db.flush = AsyncMock(side_effect=_flush_side_effect)
    db.add = MagicMock()

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/token",
        json={
            "email": "new@test.com",
            "password": "secret123",
            "tenant_name": "Test Corp",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "new@test.com"
    assert data["user"]["role"] == "ADMIN"
    assert data["user"]["tenant_name"] == "Test Corp"


# ── Test 11: POST /token existing user valid password → 200 ──────────


def test_login_existing_user_valid_password():
    """POST /token with correct password returns JWT."""
    from backend.app.api.endpoints.auth import router as auth_router
    from backend.app.core.database import get_db
    from passlib.hash import bcrypt as bcrypt_hash
    from backend.app.models.tenant import Tenant

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth")

    db = AsyncMock()

    # Mock existing user
    mock_user = MagicMock()
    mock_user.id = USER_ID
    mock_user.tenant_id = TENANT_ID
    mock_user.email = EMAIL
    mock_user.password_hash = bcrypt_hash.hash("correct-password")
    mock_user.role = "ADMIN"
    mock_user.is_active = True

    # Mock tenant
    mock_tenant = MagicMock()
    mock_tenant.name = "Test Corp"

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = mock_user

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = mock_tenant

    db.execute = AsyncMock(side_effect=[user_result, tenant_result])

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/token",
        json={"email": EMAIL, "password": "correct-password"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == EMAIL


# ── Test 12: POST /token wrong password → 401 ────────────────────────


def test_login_wrong_password():
    """POST /token with incorrect password returns 401."""
    from backend.app.api.endpoints.auth import router as auth_router
    from backend.app.core.database import get_db
    from passlib.hash import bcrypt as bcrypt_hash

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth")

    db = AsyncMock()

    mock_user = MagicMock()
    mock_user.id = USER_ID
    mock_user.tenant_id = TENANT_ID
    mock_user.email = EMAIL
    mock_user.password_hash = bcrypt_hash.hash("correct-password")
    mock_user.role = "ADMIN"
    mock_user.is_active = True

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = mock_user
    db.execute.return_value = user_result

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/token",
        json={"email": EMAIL, "password": "wrong-password"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["error"]["code"] == "UNAUTHORIZED"


# ── Test 13: POST /token deactivated user → 401 ──────────────────────


def test_login_deactivated_user():
    """POST /token for a deactivated user returns 401."""
    from backend.app.api.endpoints.auth import router as auth_router
    from backend.app.core.database import get_db
    from passlib.hash import bcrypt as bcrypt_hash

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth")

    db = AsyncMock()

    mock_user = MagicMock()
    mock_user.id = USER_ID
    mock_user.tenant_id = TENANT_ID
    mock_user.email = EMAIL
    mock_user.password_hash = bcrypt_hash.hash("correct-password")
    mock_user.role = "ADMIN"
    mock_user.is_active = False  # deactivated

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = mock_user
    db.execute.return_value = user_result

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/token",
        json={"email": EMAIL, "password": "correct-password"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["error"]["code"] == "UNAUTHORIZED"
    assert "deactivated" in data["detail"]["error"]["message"].lower()


# ── Test 14: CurrentUser model validation ─────────────────────────────


def test_current_user_model():
    """CurrentUser model accepts valid fields, defaults role to REVIEWER."""
    user = CurrentUser(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        email=EMAIL,
    )
    assert user.role == "REVIEWER"
    assert user.user_id == USER_ID
    assert user.tenant_id == TENANT_ID
    assert user.email == EMAIL
