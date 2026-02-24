"""
Tests for LeakSight V1 — Vendor Endpoints

Source: docs/API_CONTRACTS.md (Section 5)

Tests:
1. List vendors → 200 with pagination
2. List vendors with search filter
3. Get single vendor with aliases → 200
4. Get vendor not found → 404
5. Add alias → 201
6. Add duplicate alias → 409
7. Deactivate alias → 200
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.vendors import router
from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
VENDOR_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
ALIAS_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")


def _create_app(user=None, db_mock=None):
    app = FastAPI()
    r = APIRouter(prefix="/api/v1/vendors", tags=["vendors"])
    r.include_router(router)
    app.include_router(r)
    if user:
        app.dependency_overrides[get_current_user] = lambda: user
    if db_mock:
        async def _db():
            yield db_mock
        app.dependency_overrides[get_db] = _db
    return app


def _user():
    return CurrentUser(user_id=USER_ID, tenant_id=TENANT_ID, email="t@t.com", role="ADMIN")


def _db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


# ── Test 1: List vendors ─────────────────────────────────────────────


def test_list_vendors():
    db = _db()

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    row = MagicMock()
    row.id = VENDOR_ID
    row.normalized_name = "tata steel"
    row.raw_names_jsonb = ["Tata Steel Pvt Ltd"]
    row.gst_id = "27AAACT2727Q1ZX"
    row.alias_count = 2
    row.created_at = datetime.now(timezone.utc)

    data_result = MagicMock()
    data_result.all.return_value = [row]

    db.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/vendors")

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["normalized_name"] == "tata steel"
    assert "pagination" in data


# ── Test 2: List with search ─────────────────────────────────────────


def test_list_vendors_with_search():
    db = _db()

    count_result = MagicMock()
    count_result.scalar.return_value = 0

    data_result = MagicMock()
    data_result.all.return_value = []

    db.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/vendors?search=nonexistent")

    assert response.status_code == 200
    assert response.json()["data"] == []


# ── Test 3: Get vendor with aliases ──────────────────────────────────


def test_get_vendor_detail():
    db = _db()

    vendor = MagicMock()
    vendor.id = VENDOR_ID
    vendor.normalized_name = "tata steel"
    vendor.raw_names_jsonb = ["Tata Steel Pvt Ltd"]
    vendor.gst_id = "27AAACT2727Q1ZX"
    vendor.created_at = datetime.now(timezone.utc)

    vendor_result = MagicMock()
    vendor_result.scalar_one_or_none.return_value = vendor

    alias_obj = MagicMock()
    alias_obj.id = ALIAS_ID
    alias_obj.alias_name = "tata steel pvt ltd"
    alias_obj.override_source = "MANUAL_REVIEW"
    alias_obj.applied_by_user_id = USER_ID
    alias_obj.is_active = True
    alias_obj.created_at = datetime.now(timezone.utc)

    alias_result = MagicMock()
    alias_result.scalars.return_value.all.return_value = [alias_obj]

    db.execute = AsyncMock(side_effect=[vendor_result, alias_result])

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/vendors/{VENDOR_ID}")

    assert response.status_code == 200
    data = response.json()
    assert data["normalized_name"] == "tata steel"
    assert len(data["aliases"]) == 1
    assert data["aliases"][0]["alias_name"] == "tata steel pvt ltd"


# ── Test 4: Get vendor not found ─────────────────────────────────────


def test_get_vendor_not_found():
    db = _db()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/vendors/{uuid.uuid4()}")

    assert response.status_code == 404


# ── Test 5: Add alias ────────────────────────────────────────────────


def test_add_alias():
    db = _db()

    # vendor exists
    vendor = MagicMock()
    vendor.id = VENDOR_ID
    vendor_result = MagicMock()
    vendor_result.scalar_one_or_none.return_value = vendor

    # no duplicate
    dup_result = MagicMock()
    dup_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(side_effect=[vendor_result, dup_result])

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            f"/api/v1/vendors/{VENDOR_ID}/aliases",
            json={"alias_name": "T.S. Limited"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["alias_name"] == "t.s. limited"
    assert data["vendor_id"] == str(VENDOR_ID)
    assert data["override_source"] == "MANUAL_REVIEW"


# ── Test 6: Add duplicate alias → 409 ────────────────────────────────


def test_add_duplicate_alias():
    db = _db()

    vendor = MagicMock()
    vendor.id = VENDOR_ID
    vendor_result = MagicMock()
    vendor_result.scalar_one_or_none.return_value = vendor

    existing_alias = MagicMock()
    dup_result = MagicMock()
    dup_result.scalar_one_or_none.return_value = existing_alias

    db.execute = AsyncMock(side_effect=[vendor_result, dup_result])

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            f"/api/v1/vendors/{VENDOR_ID}/aliases",
            json={"alias_name": "existing alias"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == "DUPLICATE_RESOURCE"


# ── Test 7: Deactivate alias ─────────────────────────────────────────


def test_deactivate_alias():
    db = _db()

    alias = MagicMock()
    alias.id = ALIAS_ID
    alias.alias_name = "old alias"
    alias.is_active = True

    result = MagicMock()
    result.scalar_one_or_none.return_value = alias
    db.execute.return_value = result

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.vendors.set_tenant_context", new_callable=AsyncMock):
        response = client.put(
            f"/api/v1/vendors/{VENDOR_ID}/aliases/{ALIAS_ID}/deactivate"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False
