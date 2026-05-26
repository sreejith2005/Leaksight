"""Tests for Tool A structuring API endpoints."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.tools.contract_structuring.router import router

TENANT_A = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TENANT_B = uuid.UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
RUN_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
ITEM_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")
DOC_ID = uuid.UUID("44444444-5555-6666-7777-888888888888")


def _create_app(user: CurrentUser | None = None, db_mock: AsyncMock | None = None) -> FastAPI:
    app = FastAPI()
    r = APIRouter(prefix="/api/v1/structuring", tags=["Contract Structuring"])
    r.include_router(router)
    app.include_router(r)

    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if db_mock is not None:

        async def _db():
            yield db_mock

        app.dependency_overrides[get_db] = _db

    return app


def _user(tenant_id: uuid.UUID = TENANT_A) -> CurrentUser:
    return CurrentUser(
        user_id=USER_ID,
        tenant_id=tenant_id,
        email="admin@example.com",
        role="ADMIN",
    )


def _db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_run(status: str = "PENDING") -> MagicMock:
    run = MagicMock()
    run.id = RUN_ID
    run.tenant_id = TENANT_A
    run.run_label = "phase-4"
    run.status = status
    run.total_documents = 1
    run.processed_documents = 1 if status == "COMPLETE" else 0
    run.total_line_items_found = 1000
    run.total_clauses_found = 0
    run.started_at = datetime.now(timezone.utc)
    run.completed_at = datetime.now(timezone.utc) if status == "COMPLETE" else None
    run.created_by_user_id = USER_ID
    run.created_at = datetime.now(timezone.utc)
    return run


def _mock_line_item(status: str = "PENDING_REVIEW") -> MagicMock:
    item = MagicMock()
    item.id = ITEM_ID
    item.tenant_id = TENANT_A
    item.run_id = RUN_ID
    item.document_id = DOC_ID
    item.raw_table_id = uuid.uuid4()
    item.item_description = "Copper Wire"
    item.normalized_item_id = None
    item.unit_raw = "KG"
    item.normalized_unit_id = None
    item.unit_price = Decimal("100.00")
    item.currency = "INR"
    item.slab_info = None
    item.effective_date = None
    item.expiry_date = None
    item.version_number = 1
    item.source_page = 2
    item.item_confidence = 0.95
    item.price_confidence = 0.96
    item.unit_confidence = 0.97
    item.review_status = status
    item.needs_review = True
    item.reviewed_by_user_id = None
    item.reviewed_at = None
    item.reviewer_notes = None
    item.created_at = datetime.now(timezone.utc)
    return item


def _mock_count_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _mock_scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value = rows
    return result


def test_post_runs_returns_201_with_valid_document_ids():
    db = _db()
    run = _mock_run(status="PENDING")
    db.execute = AsyncMock(return_value=_mock_count_result(1))
    db.scalar = AsyncMock(return_value=run)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        with patch(
            "backend.app.tools.contract_structuring.router.create_structuring_run",
            new_callable=AsyncMock,
            return_value=RUN_ID,
        ):
            response = client.post(
                "/api/v1/structuring/runs",
                json={"document_ids": [str(DOC_ID)], "run_label": "phase-4"},
            )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == str(RUN_ID)
    assert data["tenant_id"] == str(TENANT_A)


def test_post_runs_returns_422_for_wrong_tenant_document_ids():
    db = _db()
    db.execute = AsyncMock(return_value=_mock_count_result(0))

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/structuring/runs",
            json={"document_ids": [str(DOC_ID)], "run_label": "phase-4"},
        )

    assert response.status_code == 422


def test_get_runs_returns_paginated_list():
    db = _db()
    run = _mock_run()
    db.execute = AsyncMock(side_effect=[_mock_count_result(1), _mock_scalars_result([run])])

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/structuring/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert len(payload["items"]) == 1


def test_get_run_status_returns_expected_fields():
    db = _db()
    run = _mock_run(status="COMPLETE")
    db.scalar = AsyncMock(return_value=run)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/structuring/runs/{RUN_ID}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETE"
    assert payload["processed_documents"] == 1
    assert payload["total_documents"] == 1
    assert payload["total_line_items_found"] == 1000


def test_get_run_status_returns_404_for_unknown_run():
    db = _db()
    db.scalar = AsyncMock(return_value=None)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/structuring/runs/{uuid.uuid4()}/status")

    assert response.status_code == 404


def test_patch_line_item_updates_allowed_fields():
    db = _db()
    item = _mock_line_item(status="PENDING_REVIEW")
    db.scalar = AsyncMock(return_value=item)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.patch(
            f"/api/v1/structuring/line-items/{ITEM_ID}",
            json={"unit_price": 155.5, "reviewer_notes": "checked"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert Decimal(payload["unit_price"]) == Decimal("155.5")
    assert payload["reviewer_notes"] == "checked"


def test_patch_line_item_rejects_unit_price_zero_422():
    db = _db()
    item = _mock_line_item(status="PENDING_REVIEW")
    db.scalar = AsyncMock(return_value=item)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.patch(
            f"/api/v1/structuring/line-items/{ITEM_ID}",
            json={"unit_price": 0},
        )

    assert response.status_code == 422


def test_patch_line_item_returns_409_when_confirmed():
    db = _db()
    db.scalar = AsyncMock(return_value=_mock_line_item(status="CONFIRMED"))

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.patch(
            f"/api/v1/structuring/line-items/{ITEM_ID}",
            json={"unit_price": 200},
        )

    assert response.status_code == 409


def test_confirm_line_item_sets_confirmed_status():
    db = _db()
    item = _mock_line_item(status="PENDING_REVIEW")
    db.scalar = AsyncMock(return_value=item)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.post(f"/api/v1/structuring/line-items/{ITEM_ID}/confirm")

    assert response.status_code == 200
    assert response.json()["review_status"] == "CONFIRMED"


def test_reject_line_item_sets_rejected_status():
    db = _db()
    item = _mock_line_item(status="PENDING_REVIEW")
    db.scalar = AsyncMock(return_value=item)

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.contract_structuring.router.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            f"/api/v1/structuring/line-items/{ITEM_ID}/reject",
            json={"reason": "bad parse"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == "REJECTED"
    assert payload["reviewer_notes"] == "bad parse"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/v1/structuring/runs", None),
        ("post", "/api/v1/structuring/runs", {"document_ids": [str(DOC_ID)], "run_label": "x"}),
        ("get", f"/api/v1/structuring/runs/{RUN_ID}/status", None),
        ("patch", f"/api/v1/structuring/line-items/{ITEM_ID}", {"unit_price": 10}),
        ("post", f"/api/v1/structuring/line-items/{ITEM_ID}/confirm", None),
        ("post", f"/api/v1/structuring/line-items/{ITEM_ID}/reject", {"reason": "x"}),
    ],
)
def test_endpoints_require_auth(method: str, path: str, body: dict | None):
    app = _create_app(user=None, db_mock=None)
    client = TestClient(app)

    request_fn = getattr(client, method)
    if body is None:
        response = request_fn(path)
    else:
        response = request_fn(path, json=body)

    assert response.status_code == 401
