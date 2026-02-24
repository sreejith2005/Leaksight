"""
Tests for LeakSight V1 — Leakage Record Endpoints

Source: docs/API_CONTRACTS.md (Section 4)

Tests:
1. List records → 200 with pagination, excludes evidence_jsonb
2. Get single record → 200 with full evidence
3. Get record from other tenant → 404
4. Accept PENDING record → 200
5. Accept PENDING_FX_RATE record → 422
6. Accept already ACCEPTED record → 409
7. Reject without notes → 422
8. Reject with notes → 200
9. Reject already ACCEPTED record → 409
10. Summary endpoint → 200 with correct aggregation
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.leakage import router
from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
RECORD_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
RUN_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")


def _create_app(
    user: CurrentUser | None = None,
    db_mock: AsyncMock | None = None,
) -> FastAPI:
    app = FastAPI()
    leakage_router = APIRouter(prefix="/api/v1/leakage", tags=["leakage"])
    leakage_router.include_router(router)
    app.include_router(leakage_router)

    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user

    if db_mock is not None:
        async def _override_db():
            yield db_mock
        app.dependency_overrides[get_db] = _override_db

    return app


def _make_user(
    tenant_id: uuid.UUID = TENANT_ID,
    user_id: uuid.UUID = USER_ID,
) -> CurrentUser:
    return CurrentUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email="test@example.com",
        role="ADMIN",
    )


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_record(
    record_id: uuid.UUID = RECORD_ID,
    status: str = "PENDING",
    amount: Decimal = Decimal("3000.00"),
) -> MagicMock:
    rec = MagicMock()
    rec.id = record_id
    rec.tenant_id = TENANT_ID
    rec.run_id = RUN_ID
    rec.leakage_type = "PRICE_MISMATCH"
    rec.invoice_id = uuid.uuid4()
    rec.amount = amount
    rec.currency = "INR"
    rec.confidence = 0.92
    rec.rule_applied = "RULE_1_PRICE_MISMATCH"
    rec.explanation = "Invoice overcharge ₹3000"
    rec.evidence_jsonb = {"invoice_ref": "INV-001", "contract_ref": "CT-001"}
    rec.status = status
    rec.reviewed_by_user_id = None
    rec.reviewed_at = None
    rec.review_notes = None
    rec.created_at = datetime.now(timezone.utc)
    return rec


# ── Test 1: List records ──────────────────────────────────────────────


def test_list_records_success():
    """List records returns paginated data without evidence_jsonb."""
    db = _make_db()

    # Mock count query
    count_result = MagicMock()
    count_result.scalar.return_value = 1

    # Mock data query — Row-like object
    row = MagicMock()
    row.id = RECORD_ID
    row.leakage_type = "PRICE_MISMATCH"
    row.amount = Decimal("3000.00")
    row.currency = "INR"
    row.confidence = 0.92
    row.rule_applied = "RULE_1_PRICE_MISMATCH"
    row.explanation = "Invoice overcharge ₹3000"
    row.status = "PENDING"
    row.vendor_name = "Tata Steel"
    row.invoice_no = "INV-001"
    row.invoice_date = "2024-06-15"
    row.created_at = datetime.now(timezone.utc)

    data_result = MagicMock()
    data_result.all.return_value = [row]

    db.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/leakage/records")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "pagination" in data
    assert len(data["data"]) == 1
    assert data["data"][0]["id"] == str(RECORD_ID)
    # evidence_jsonb should NOT be in list response
    assert "evidence" not in data["data"][0]
    assert "evidence_jsonb" not in data["data"][0]


# ── Test 2: Get single record with evidence ───────────────────────────


def test_get_record_detail():
    """Get single record returns full evidence."""
    db = _make_db()
    record = _mock_record()

    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute.return_value = result

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/leakage/records/{RECORD_ID}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(RECORD_ID)
    assert "evidence" in data
    assert data["evidence"]["invoice_ref"] == "INV-001"


# ── Test 3: Get record from other tenant → 404 ───────────────────────


def test_get_record_other_tenant():
    """Cross-tenant record access returns 404, never 403."""
    db = _make_db()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/leakage/records/{uuid.uuid4()}")

    assert response.status_code == 404


# ── Test 4: Accept PENDING record → 200 ──────────────────────────────


def test_accept_pending_record():
    """Accept a PENDING record returns 200."""
    db = _make_db()
    record = _mock_record(status="PENDING")

    # Pre-check query
    pre_result = MagicMock()
    pre_result.scalar_one_or_none.return_value = record
    db.execute.return_value = pre_result

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        with patch(
            "backend.app.api.endpoints.leakage.accept_leakage_record",
            new_callable=AsyncMock,
        ) as mock_accept:
            accepted = _mock_record(status="ACCEPTED")
            accepted.reviewed_by_user_id = USER_ID
            accepted.reviewed_at = datetime.now(timezone.utc)
            accepted.review_notes = "Confirmed"
            mock_accept.return_value = accepted

            response = client.post(
                f"/api/v1/leakage/records/{RECORD_ID}/accept",
                json={"notes": "Confirmed"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ACCEPTED"


# ── Test 5: Accept PENDING_FX_RATE → 422 ─────────────────────────────


def test_accept_pending_fx_rate():
    """Accept a PENDING_FX_RATE record returns 422."""
    db = _make_db()
    record = _mock_record(status="PENDING_FX_RATE")

    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute.return_value = result

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            f"/api/v1/leakage/records/{RECORD_ID}/accept",
            json={},
        )

    assert response.status_code == 422
    data = response.json()
    assert "PENDING_FX_RATE" in data["detail"]["error"]["message"]


# ── Test 6: Accept already ACCEPTED → 409 ────────────────────────────


def test_accept_already_accepted():
    """Accept an already ACCEPTED record returns 409."""
    db = _make_db()
    record = _mock_record(status="ACCEPTED")

    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute.return_value = result

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        from backend.app.services.leakage_service import ImmutabilityError

        with patch(
            "backend.app.api.endpoints.leakage.accept_leakage_record",
            new_callable=AsyncMock,
            side_effect=ImmutabilityError("already ACCEPTED"),
        ):
            response = client.post(
                f"/api/v1/leakage/records/{RECORD_ID}/accept",
                json={},
            )

    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["error"]["code"] == "IMMUTABLE_RECORD"


# ── Test 7: Reject without notes → 422 ───────────────────────────────


def test_reject_without_notes():
    """Reject without notes returns 422."""
    db = _make_db()

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            f"/api/v1/leakage/records/{RECORD_ID}/reject",
            json={"notes": ""},
        )

    assert response.status_code == 422
    data = response.json()
    assert "required" in data["detail"]["error"]["message"].lower()


# ── Test 8: Reject with notes → 200 ──────────────────────────────────


def test_reject_with_notes():
    """Reject with notes returns 200."""
    db = _make_db()

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        with patch(
            "backend.app.api.endpoints.leakage.reject_leakage_record",
            new_callable=AsyncMock,
        ) as mock_reject:
            rejected = _mock_record(status="REJECTED")
            rejected.reviewed_by_user_id = USER_ID
            rejected.reviewed_at = datetime.now(timezone.utc)
            rejected.review_notes = "Vendor confirmed amendment"
            mock_reject.return_value = rejected

            response = client.post(
                f"/api/v1/leakage/records/{RECORD_ID}/reject",
                json={"notes": "Vendor confirmed amendment"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"
    assert data["review_notes"] == "Vendor confirmed amendment"


# ── Test 9: Reject already ACCEPTED → 409 ────────────────────────────


def test_reject_already_accepted():
    """Reject an already ACCEPTED record returns 409."""
    db = _make_db()

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        with patch(
            "backend.app.api.endpoints.leakage.reject_leakage_record",
            new_callable=AsyncMock,
        ) as mock_reject:
            from backend.app.services.leakage_service import ImmutabilityError

            mock_reject.side_effect = ImmutabilityError("already ACCEPTED")

            response = client.post(
                f"/api/v1/leakage/records/{RECORD_ID}/reject",
                json={"notes": "Should not work"},
            )

    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["error"]["code"] == "IMMUTABLE_RECORD"


# ── Test 10: Summary endpoint ─────────────────────────────────────────


def test_summary_endpoint():
    """Summary returns aggregated data."""
    db = _make_db()

    # total_leakage
    total_result = MagicMock()
    total_result.scalar.return_value = Decimal("150000.00")

    # by_type
    type_row = MagicMock()
    type_row.leakage_type = "PRICE_MISMATCH"
    type_row.count = 10
    type_row.total_amount = Decimal("150000.00")
    type_result = MagicMock()
    type_result.all.return_value = [type_row]

    # by_status
    status_row1 = MagicMock()
    status_row1.status = "PENDING"
    status_row1.count = 5
    status_row2 = MagicMock()
    status_row2.status = "ACCEPTED"
    status_row2.count = 10
    status_result = MagicMock()
    status_result.all.return_value = [status_row1, status_row2]

    # by_vendor
    vendor_row = MagicMock()
    vendor_row.vendor_id = uuid.uuid4()
    vendor_row.vendor_name = "Tata Steel"
    vendor_row.total_amount = Decimal("150000.00")
    vendor_row.record_count = 10
    vendor_result = MagicMock()
    vendor_result.all.return_value = [vendor_row]

    # avg confidence
    conf_result = MagicMock()
    conf_result.scalar.return_value = 0.89

    db.execute = AsyncMock(
        side_effect=[total_result, type_result, status_result, vendor_result, conf_result]
    )

    app = _create_app(user=_make_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.leakage.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/leakage/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leakage_amount"] == 150000.0
    assert "by_type" in data
    assert "by_status" in data
    assert "by_vendor" in data
    assert data["average_confidence"] == 0.89
