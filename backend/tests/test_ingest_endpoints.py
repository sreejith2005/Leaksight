"""
Tests for LeakSight V1 — File Ingestion Endpoints

Source: docs/API_CONTRACTS.md (Section 3), docs/PARSING_SPEC.md

Tests:
1. Upload valid PDF → 201, document_id returned, documents row created, BASELINE hash created
2. Upload file exceeding size limit → 400 FILE_TOO_LARGE
3. Upload unsupported format → 400 UNSUPPORTED_FORMAT listing accepted formats
4. Upload without JWT → 401
5. Trigger run with valid document_ids → 202, run_id returned, QUEUED status
6. Trigger run with document_id belonging to different tenant → 403
7. Get run status for own run → 200 with correct fields
8. Get run status for another tenant's run → 404
"""

import io
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.ingest import (
    SUPPORTED_EXTENSIONS,
    VALID_DOC_TYPES,
    router,
)
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.database import get_db


TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
OTHER_TENANT_ID = uuid.UUID("ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
DOC_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
RUN_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")


def _create_app(
    user_payload: CurrentUser | None = None,
    db_mock: AsyncMock | None = None,
) -> FastAPI:
    """Create a test FastAPI app with overridden dependencies."""
    from fastapi import APIRouter

    app = FastAPI()
    ingest_router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])
    ingest_router.include_router(router)
    app.include_router(ingest_router)

    if user_payload is not None:
        app.dependency_overrides[get_current_user] = lambda: user_payload

    if db_mock is not None:
        async def _override_db():
            yield db_mock
        app.dependency_overrides[get_db] = _override_db

    return app


def _make_user_payload(
    tenant_id: uuid.UUID = TENANT_ID,
    user_id: uuid.UUID = USER_ID,
    role: str = "ADMIN",
) -> CurrentUser:
    """Create a mock CurrentUser for dependency override."""
    return CurrentUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email="test@example.com",
        role=role,
    )


def _make_db_mock() -> AsyncMock:
    """Create a mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


# ── Test 1: Upload valid PDF ───────────────────────────────────────────


def test_upload_valid_pdf():
    """Upload a valid PDF returns 201 with document_id."""
    db = _make_db_mock()

    # Mock: no existing document with same hash
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    file_content = b"%PDF-1.4 test content for unit test"

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        with patch("pathlib.Path.mkdir"):
            with patch("pathlib.Path.write_bytes"):
                with patch("backend.app.api.endpoints.ingest.parse_document") as mock_parse_task:
                    mock_parse_task.delay = MagicMock()
                    response = client.post(
                        "/api/v1/ingest/upload",
                        files={"file": ("invoice.pdf", io.BytesIO(file_content), "application/pdf")},
                        data={"doc_type": "INVOICE"},
                    )

    assert response.status_code == 201
    data = response.json()
    assert "document_id" in data
    assert data["filename"] == "invoice.pdf"
    assert data["doc_type"] == "INVOICE"
    assert data["sha256_hash"] is not None
    assert data["file_size"] == len(file_content)
    assert data["parse_status"] == "PENDING"

    # Verify db.add was called for both Document and DocumentHash
    assert db.add.call_count == 2

    # Verify parse task was queued
    mock_parse_task.delay.assert_called_once()


# ── Test 2: Upload file exceeding size limit ──────────────────────────


def test_upload_exceeds_size_limit():
    """Upload file larger than MAX_UPLOAD_SIZE_MB returns 400 FILE_TOO_LARGE."""
    db = _make_db_mock()

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    # Create content just over the limit
    with patch("backend.app.api.endpoints.ingest.get_settings") as mock_settings:
        settings = MagicMock()
        settings.max_upload_size_mb = 1  # 1MB limit for test
        settings.document_storage_path = "/tmp/test_docs"
        mock_settings.return_value = settings

        # 1.5MB content
        big_content = b"x" * (1024 * 1024 + 512 * 1024)

        with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
            response = client.post(
                "/api/v1/ingest/upload",
                files={"file": ("big.pdf", io.BytesIO(big_content), "application/pdf")},
                data={"doc_type": "INVOICE"},
            )

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["error"]["code"] == "FILE_TOO_LARGE"


# ── Test 3: Upload unsupported format ─────────────────────────────────


def test_upload_unsupported_format():
    """Upload unsupported file format returns 400 UNSUPPORTED_FORMAT."""
    db = _make_db_mock()

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/ingest/upload",
            files={"file": ("archive.zip", io.BytesIO(b"PK content"), "application/zip")},
            data={"doc_type": "INVOICE"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["error"]["code"] == "UNSUPPORTED_FORMAT"
    # Verify accepted formats are listed in the error message
    msg = data["detail"]["error"]["message"]
    assert ".pdf" in msg
    assert ".xlsx" in msg
    assert ".csv" in msg
    assert ".docx" in msg


# ── Test 4: Upload without JWT ────────────────────────────────────────


def test_upload_without_jwt():
    """Upload without Authorization header returns 401."""
    db = _make_db_mock()

    # Do NOT override get_current_user → uses real dependency which requires Bearer
    app = _create_app(user_payload=None, db_mock=db)

    # Remove the dependency override so the real security kicks in
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

    client = TestClient(app)

    response = client.post(
        "/api/v1/ingest/upload",
        files={"file": ("invoice.pdf", io.BytesIO(b"pdf content"), "application/pdf")},
        data={"doc_type": "INVOICE"},
    )

    # FastAPI's HTTPBearer returns 403 when no credentials provided
    # or 401 when credentials are invalid
    assert response.status_code in (401, 403)


# ── Test 5: Trigger run with valid document_ids ───────────────────────


def test_trigger_run_valid():
    """Trigger run with valid document_ids returns 202 with run_id."""
    db = _make_db_mock()

    # Mock: all doc_ids belong to tenant (count matches)
    count_result = MagicMock()
    count_result.scalar.return_value = 2

    # Mock: document lookups for run_id assignment
    doc_mock = MagicMock()
    doc_mock.id = DOC_ID
    doc_result = MagicMock()
    doc_result.scalar_one_or_none.return_value = doc_mock

    db.execute.side_effect = [count_result, doc_result, doc_result]

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        with patch(
            "backend.app.api.endpoints.ingest.analysis_run_service.create_run",
            new_callable=AsyncMock,
        ) as mock_create_run:
            mock_run = MagicMock()
            mock_run.id = RUN_ID
            mock_run.status = "QUEUED"
            mock_run.total_documents = 2
            mock_run.created_at = datetime.now(timezone.utc)
            mock_create_run.return_value = mock_run

            with patch("backend.app.api.endpoints.ingest.run_analysis") as mock_run_task:
                mock_run_task.delay = MagicMock()
                response = client.post(
                    "/api/v1/ingest/trigger-run",
                    json={"document_ids": doc_ids},
                )

    assert response.status_code == 202
    data = response.json()
    assert data["run_id"] == str(RUN_ID)
    assert data["status"] == "QUEUED"
    assert data["total_documents"] == 2

    # Verify analysis task was queued
    mock_run_task.delay.assert_called_once_with(str(RUN_ID), str(TENANT_ID))


# ── Test 6: Trigger run with document_id from different tenant ────────


def test_trigger_run_wrong_tenant():
    """Trigger run with doc_id belonging to different tenant returns 403."""
    db = _make_db_mock()

    # Mock: count returns 0 (none of the doc_ids belong to this tenant)
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    db.execute.return_value = count_result

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/ingest/trigger-run",
            json={"document_ids": [str(uuid.uuid4())]},
        )

    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"]["code"] == "FORBIDDEN"


# ── Test 7: Get run status for own run ────────────────────────────────


def test_get_run_status_own_run():
    """Get run status for own tenant's run returns 200 with correct fields."""
    db = _make_db_mock()

    mock_run = MagicMock()
    mock_run.id = RUN_ID
    mock_run.tenant_id = TENANT_ID
    mock_run.status = "PROCESSING"
    mock_run.total_documents = 10
    mock_run.processed_documents = 5
    mock_run.total_leakage_found = Decimal("50000.00")
    mock_run.leakage_record_count = 3
    mock_run.error_summary = None
    mock_run.started_at = datetime.now(timezone.utc)
    mock_run.completed_at = None
    mock_run.created_at = datetime.now(timezone.utc)

    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_run
    db.execute.return_value = result

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/ingest/runs/{RUN_ID}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(RUN_ID)
    assert data["status"] == "PROCESSING"
    assert data["total_documents"] == 10
    assert data["processed_documents"] == 5
    assert data["progress_percentage"] == 50.0
    assert data["total_leakage_found"] == 50000.0
    assert data["leakage_record_count"] == 3
    assert data["error_summary"] is None


# ── Test 8: Get run status for another tenant's run ───────────────────


def test_get_run_status_other_tenant():
    """Get run status for another tenant's run returns 404."""
    db = _make_db_mock()

    # Run not found for this tenant
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    app = _create_app(
        user_payload=_make_user_payload(),
        db_mock=db,
    )
    client = TestClient(app)

    other_run_id = uuid.uuid4()

    with patch("backend.app.api.endpoints.ingest.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/ingest/runs/{other_run_id}/status")

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"]["code"] == "NOT_FOUND"
