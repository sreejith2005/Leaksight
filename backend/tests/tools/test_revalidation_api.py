"""API tests for Tool C document revalidation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.tools.document_revalidation.router import router
from backend.app.tools.document_revalidation.schemas import (
    RevalidationDocResponse,
    SubjectResponse,
)

TENANT_A = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TENANT_B = uuid.UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
SUBJECT_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
REVAL_DOC_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")
DOCUMENT_ID = uuid.UUID("44444444-5555-6666-7777-888888888888")


def _create_app(user: CurrentUser | None = None, db_mock: AsyncMock | None = None) -> FastAPI:
    app = FastAPI()
    api_router = APIRouter(prefix="/api/v1/revalidation", tags=["Document Revalidation"])
    api_router.include_router(router)
    app.include_router(api_router)

    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if db_mock is not None:

        async def _db():
            yield db_mock

        app.dependency_overrides[get_db] = _db

    return app


def _user(tenant_id: uuid.UUID = TENANT_A, role: str = "ADMIN") -> CurrentUser:
    return CurrentUser(
        user_id=USER_ID,
        tenant_id=tenant_id,
        email="admin@example.com",
        role=role,
    )


def _db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock()
    db.commit = AsyncMock()
    return db


def _count_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _subject_response(tenant_id: uuid.UUID = TENANT_A, subject_type: str = "EMPLOYEE") -> SubjectResponse:
    return SubjectResponse(
        id=SUBJECT_ID,
        tenant_id=tenant_id,
        subject_type=subject_type,
        name="Jane Doe",
        identifier="EMP-001",
        department="Finance",
        email="jane@example.com",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        compliance_summary={
            "total_required": 2,
            "uploaded": 0,
            "expired": 0,
            "expiring_soon": 0,
            "missing": 2,
        },
    )


def _revalidation_doc_response(status_value: str) -> RevalidationDocResponse:
    return RevalidationDocResponse(
        id=REVAL_DOC_ID,
        tenant_id=TENANT_A,
        subject_id=SUBJECT_ID,
        document_id=DOCUMENT_ID if status_value != "PENDING_UPLOAD" else None,
        category="ID_PROOF",
        display_name="Identity Proof",
        issue_date=None,
        expiry_date=None,
        has_expiry=status_value != "NO_EXPIRY",
        manually_reviewed=status_value in {"VALID", "NO_EXPIRY", "EXPIRED"},
        status=status_value,
        extraction_confidence=None,
        alert_days_before=30,
        last_checked_at=None,
        notes=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        days_until_expiry=None,
    )


class TestSubjectEndpoints:
    def test_create_employee_subject(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.create_subject",
                new_callable=AsyncMock,
                return_value=_subject_response(subject_type="EMPLOYEE"),
            ):
                response = client.post(
                    "/api/v1/revalidation/subjects",
                    json={
                        "subject_type": "EMPLOYEE",
                        "name": "Jane Doe",
                        "identifier": "EMP-001",
                        "department": "Finance",
                        "email": "jane@example.com",
                    },
                )

        assert response.status_code == 201
        assert response.json()["subject_type"] == "EMPLOYEE"

    def test_create_vendor_subject(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.create_subject",
                new_callable=AsyncMock,
                return_value=_subject_response(subject_type="VENDOR"),
            ):
                response = client.post(
                    "/api/v1/revalidation/subjects",
                    json={
                        "subject_type": "VENDOR",
                        "name": "Acme Supplies",
                        "identifier": "GST-001",
                    },
                )

        assert response.status_code == 201
        assert response.json()["subject_type"] == "VENDOR"

    def test_duplicate_identifier_returns_409(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.create_subject",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=409, detail="Duplicate subject identifier"),
            ):
                response = client.post(
                    "/api/v1/revalidation/subjects",
                    json={
                        "subject_type": "EMPLOYEE",
                        "name": "Jane Doe",
                        "identifier": "EMP-001",
                    },
                )

        assert response.status_code == 409

    def test_list_subjects_filtered_by_type(self):
        db = _db()
        db.execute = AsyncMock(return_value=_count_result(1))
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.list_subjects",
                new_callable=AsyncMock,
                return_value=[_subject_response(subject_type="EMPLOYEE")],
            ):
                response = client.get("/api/v1/revalidation/subjects?subject_type=EMPLOYEE")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["subject_type"] == "EMPLOYEE"

    def test_get_nonexistent_subject_returns_404(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.get_subject",
                new_callable=AsyncMock,
                return_value=None,
            ):
                response = client.get(f"/api/v1/revalidation/subjects/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_cross_tenant_subject_returns_404(self):
        db = _db()
        app = _create_app(user=_user(tenant_id=TENANT_B), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.get_subject",
                new_callable=AsyncMock,
                return_value=None,
            ):
                response = client.get(f"/api/v1/revalidation/subjects/{SUBJECT_ID}")

        assert response.status_code == 404


class TestRevalidationDocEndpoints:
    def test_create_doc_slot_returns_pending_upload(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.create_revalidation_doc",
                new_callable=AsyncMock,
                return_value=_revalidation_doc_response("PENDING_UPLOAD"),
            ):
                response = client.post(
                    f"/api/v1/revalidation/subjects/{SUBJECT_ID}/documents",
                    json={
                        "subject_id": str(SUBJECT_ID),
                        "category": "ID_PROOF",
                        "display_name": "Identity Proof",
                        "has_expiry": True,
                        "alert_days_before": 30,
                    },
                )

        assert response.status_code == 201
        assert response.json()["status"] == "PENDING_UPLOAD"

    def test_attach_document_returns_revalidation_pending(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.attach_document",
                new_callable=AsyncMock,
                return_value=_revalidation_doc_response("REVALIDATION_PENDING"),
            ):
                response = client.post(
                    f"/api/v1/revalidation/documents/{REVAL_DOC_ID}/attach",
                    json={"document_id": str(DOCUMENT_ID)},
                )

        assert response.status_code == 200
        assert response.json()["status"] == "REVALIDATION_PENDING"

    def test_manual_date_valid_document(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.update_dates_manually",
                new_callable=AsyncMock,
                return_value=_revalidation_doc_response("VALID"),
            ):
                response = client.put(
                    f"/api/v1/revalidation/documents/{REVAL_DOC_ID}/dates",
                    json={"expiry_date": "2026-10-01", "has_expiry": True},
                )

        assert response.status_code == 200
        assert response.json()["status"] == "VALID"

    def test_manual_date_no_expiry(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.update_dates_manually",
                new_callable=AsyncMock,
                return_value=_revalidation_doc_response("NO_EXPIRY"),
            ):
                response = client.put(
                    f"/api/v1/revalidation/documents/{REVAL_DOC_ID}/dates",
                    json={"has_expiry": False},
                )

        assert response.status_code == 200
        assert response.json()["status"] == "NO_EXPIRY"

    def test_manual_date_expired(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.update_dates_manually",
                new_callable=AsyncMock,
                return_value=_revalidation_doc_response("EXPIRED"),
            ):
                response = client.put(
                    f"/api/v1/revalidation/documents/{REVAL_DOC_ID}/dates",
                    json={"expiry_date": "2020-01-01", "has_expiry": True},
                )

        assert response.status_code == 200
        assert response.json()["status"] == "EXPIRED"


class TestDashboard:
    def test_dashboard_returns_expected_keys(self):
        db = _db()
        app = _create_app(user=_user(), db_mock=db)
        client = TestClient(app)

        with patch("backend.app.tools.document_revalidation.router.set_tenant_context", new_callable=AsyncMock):
            with patch(
                "backend.app.tools.document_revalidation.router.get_compliance_dashboard",
                new_callable=AsyncMock,
                return_value={
                    "employees_total": 0,
                    "vendors_total": 0,
                    "docs_valid": 0,
                    "docs_expiring_soon": 0,
                    "docs_expired": 0,
                    "docs_missing": 0,
                    "docs_pending_upload": 0,
                    "recent_alerts": [],
                },
            ):
                response = client.get("/api/v1/revalidation/dashboard")

        assert response.status_code == 200
        payload = response.json()
        assert set(payload.keys()) == {
            "employees_total",
            "vendors_total",
            "docs_valid",
            "docs_expiring_soon",
            "docs_expired",
            "docs_missing",
            "docs_pending_upload",
            "recent_alerts",
        }
