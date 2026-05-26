import io
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from passlib.hash import bcrypt

from backend.app.api.endpoints.ingest import router as ingest_router
from backend.app.core.config import get_settings
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.database import get_db
from backend.app.main import create_app

TENANT_ID = uuid.UUID("6c662d73-81a4-4eb8-b7d7-d3465d10d111")
USER_ID = uuid.UUID("8da16d66-0dda-4440-90d2-943d9f560222")
AUTH_SENTINEL_UUID = uuid.UUID(int=0)
USER_EMAIL = "security-user@test.com"
USER_PASSWORD = "CorrectHorseBatteryStaple123"


def _sync_engine() -> sa.Engine:
    return sa.create_engine(get_settings().database_url_sync, future=True, pool_pre_ping=True)


@contextmanager
def _client():
    with TestClient(create_app()) as client:
        yield client


def _clear_security_rows() -> None:
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM revoked_tokens"))
        conn.execute(
            sa.text(
                """
                DELETE FROM audit_logs
                WHERE action IN ('LOGIN_FAILED', 'LOGIN_SUCCESS', 'LOGIN_BLOCKED_RATE_LIMIT')
                   OR tenant_id IN (:tenant_id, :sentinel_id)
                   OR user_id IN (:user_id, :sentinel_id)
                """
            ),
            {
                "tenant_id": str(TENANT_ID),
                "user_id": str(USER_ID),
                "sentinel_id": str(AUTH_SENTINEL_UUID),
            },
        )
        conn.execute(sa.text("DELETE FROM users WHERE id = :user_id"), {"user_id": str(USER_ID)})
        conn.execute(sa.text("DELETE FROM tenants WHERE id = :tenant_id"), {"tenant_id": str(TENANT_ID)})


def _create_login_user() -> None:
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO tenants (id, name, is_active)
                VALUES (:id, :name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": str(TENANT_ID), "name": "Security Test Tenant"},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO users (id, tenant_id, email, password_hash, role, is_active)
                VALUES (:id, :tenant_id, :email, :password_hash, 'ADMIN', true)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": str(USER_ID),
                "tenant_id": str(TENANT_ID),
                "email": USER_EMAIL,
                "password_hash": bcrypt.hash(USER_PASSWORD),
            },
        )


def _login(client: TestClient, email: str = USER_EMAIL, password: str = USER_PASSWORD) -> dict:
    response = client.post(
        "/api/v1/auth/token",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _make_ingest_app(db_mock: AsyncMock | None = None) -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/api/v1/ingest")
    router.include_router(ingest_router)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        email=USER_EMAIL,
        role="ADMIN",
    )

    if db_mock is None:
        db_mock = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db_mock.execute = AsyncMock(return_value=result)
        db_mock.flush = AsyncMock()
        db_mock.add = MagicMock()

    async def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture(autouse=True)
def _security_test_isolation():
    from backend.app.api.endpoints.auth import FAILED_LOGIN_ATTEMPTS

    FAILED_LOGIN_ATTEMPTS.clear()
    _clear_security_rows()
    yield
    FAILED_LOGIN_ATTEMPTS.clear()
    _clear_security_rows()


def test_login_lockout_after_10_failures():
    with _client() as client, patch(
        "backend.app.api.endpoints.auth.time.sleep", return_value=None
    ):
        last_response = None
        for _ in range(11):
            last_response = client.post(
                "/api/v1/auth/token",
                json={"email": "wrong@test.com", "password": "wrongpass"},
            )

    assert last_response is not None
    assert last_response.status_code == 429
    assert (
        last_response.json()["detail"]["error"]["message"]
        == "Too many failed login attempts. Try again in 15 minutes."
    )


def test_logout_invalidates_token():
    _create_login_user()
    with _client() as client:
        token = _login(client)["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/v1/health", headers=headers).status_code == 200

        logout_response = client.post("/api/v1/auth/logout", headers=headers)
        assert logout_response.status_code == 200
        assert logout_response.json() == {"message": "Logged out successfully"}

        revoked_response = client.get("/api/v1/health", headers=headers)
        assert revoked_response.status_code == 401
        assert revoked_response.json()["detail"]["error"]["message"] == "Token has been revoked"


def test_magic_byte_mismatch_rejected():
    app = _make_ingest_app()
    client = TestClient(app)

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/ingest/upload",
            files={"file": ("test.pdf", io.BytesIO(b"name,amount\nx,1\n"), "application/pdf")},
            data={"doc_type": "INVOICE"},
        )

    assert response.status_code == 400
    assert "Upload rejected for security" in response.json()["detail"]["error"]["message"]


def test_filename_sanitisation():
    db_mock = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    db_mock.execute = AsyncMock(return_value=existing_result)
    db_mock.flush = AsyncMock()
    db_mock.add = MagicMock()

    app = _make_ingest_app(db_mock=db_mock)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock), patch(
        "pathlib.Path.mkdir"
    ), patch("pathlib.Path.write_bytes"), patch(
        "backend.app.api.endpoints.ingest.parse_document"
    ) as mock_parse_task:
        mock_parse_task.delay = MagicMock()
        response = client.post(
            "/api/v1/ingest/upload",
            files={
                "file": (
                    "../../etc/passwd.pdf",
                    io.BytesIO(b"%PDF-1.7 security test"),
                    "application/pdf",
                )
            },
            data={"doc_type": "INVOICE"},
        )

    assert response.status_code == 201
    assert "/" not in response.json()["filename"]
    assert "\\" not in response.json()["filename"]

    stored_document = db_mock.add.call_args_list[0][0][0]
    assert "/" not in stored_document.original_filename
    assert "\\" not in stored_document.original_filename


def test_security_headers_present():
    with _client() as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_failed_login_creates_audit_entry():
    _create_login_user()
    forwarded_ip = "203.0.113.10"
    with _client() as client:
        response = client.post(
            "/api/v1/auth/token",
            json={"email": USER_EMAIL, "password": "wrong-password"},
            headers={"X-Forwarded-For": forwarded_ip},
        )

    assert response.status_code == 401

    engine = _sync_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                """
                SELECT action, details_jsonb
                FROM audit_logs
                WHERE action = 'LOGIN_FAILED'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        ).mappings().first()

    assert row is not None
    assert row["action"] == "LOGIN_FAILED"
    assert row["details_jsonb"]["ip"] == forwarded_ip


def test_login_response_does_not_reveal_reason():
    _create_login_user()
    with _client() as client:
        unknown_email_response = client.post(
            "/api/v1/auth/token",
            json={"email": "does-not-exist@test.com", "password": "wrong-password"},
        )
        wrong_password_response = client.post(
            "/api/v1/auth/token",
            json={"email": USER_EMAIL, "password": "wrong-password"},
        )

    assert unknown_email_response.status_code == wrong_password_response.status_code
    assert unknown_email_response.json() == wrong_password_response.json()
