"""
Tests for LeakSight V1 — Contract Endpoints

Source: docs/API_CONTRACTS.md (Section 6)

Tests:
1. List contracts → 200
2. Get contract versions → 200
3. Get contract not found → 404
4. Create contract → 201
5. Create contract with invalid vendor → 404
6. Create contract with invalid date range → 400
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.contracts import router
from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
CONTRACT_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
VENDOR_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")
VERSION_ID = uuid.UUID("44444444-5555-6666-7777-888888888888")


def _create_app(user=None, db_mock=None):
    app = FastAPI()
    r = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])
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


# ── Test 1: List contracts ───────────────────────────────────────────


def test_list_contracts():
    db = _db()

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    row = MagicMock()
    row.id = CONTRACT_ID
    row.vendor_id = VENDOR_ID
    row.vendor_name = "tata steel"
    row.contract_ref = "TS-2024-001"
    row.created_at = datetime.now(timezone.utc)
    row.latest_version_number = 1

    data_result = MagicMock()
    data_result.all.return_value = [row]

    # For active version detail: version count, version, line items count
    ver_count_result = MagicMock()
    ver_count_result.scalar.return_value = 1

    version = MagicMock()
    version.version_number = 1
    version.valid_from = "2024-01-01"
    version.valid_to = "2024-12-31"
    version.id = VERSION_ID

    ver_result = MagicMock()
    ver_result.scalar_one_or_none.return_value = version

    li_count_result = MagicMock()
    li_count_result.scalar.return_value = 2

    db.execute = AsyncMock(
        side_effect=[count_result, data_result, ver_count_result, ver_result, li_count_result]
    )

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.contracts.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/contracts/")

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["contract_ref"] == "TS-2024-001"
    assert data["data"][0]["active_version"]["version_number"] == 1


# ── Test 2: Get contract versions ────────────────────────────────────


def test_get_contract_versions():
    db = _db()

    contract = MagicMock()
    contract.id = CONTRACT_ID
    contract.vendor_id = VENDOR_ID
    contract.contract_ref = "TS-2024-001"

    contract_result = MagicMock()
    contract_result.scalar_one_or_none.return_value = contract

    vendor_result = MagicMock()
    vendor_result.scalar.return_value = "tata steel"

    version = MagicMock()
    version.id = VERSION_ID
    version.version_number = 1
    version.valid_from = "2024-01-01"
    version.valid_to = "2024-12-31"

    versions_result = MagicMock()
    versions_result.scalars.return_value.all.return_value = [version]

    li = MagicMock()
    li.id = uuid.uuid4()
    li.item_desc = "cement opc 53 grade"
    li.unit = "MT"
    li.unit_price = Decimal("320.00")
    li.currency = "INR"

    li_result = MagicMock()
    li_result.scalars.return_value.all.return_value = [li]

    db.execute = AsyncMock(
        side_effect=[contract_result, vendor_result, versions_result, li_result]
    )

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.contracts.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/contracts/{CONTRACT_ID}/versions")

    assert response.status_code == 200
    data = response.json()
    assert data["contract_ref"] == "TS-2024-001"
    assert len(data["versions"]) == 1
    assert len(data["versions"][0]["line_items"]) == 1


# ── Test 3: Get contract not found ───────────────────────────────────


def test_get_contract_versions_not_found():
    db = _db()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.contracts.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/contracts/{uuid.uuid4()}/versions")

    assert response.status_code == 404


# ── Test 4: Create contract → 201 ───────────────────────────────────


def test_create_contract():
    db = _db()

    # Vendor exists
    vendor = MagicMock()
    vendor.id = VENDOR_ID
    vendor_result = MagicMock()
    vendor_result.scalar_one_or_none.return_value = vendor
    db.execute.return_value = vendor_result

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.contracts.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/contracts/",
            json={
                "vendor_id": str(VENDOR_ID),
                "contract_ref": "TS-2024-001",
                "version": {
                    "valid_from": "2024-01-01",
                    "valid_to": "2024-12-31",
                    "line_items": [
                        {
                            "item_desc": "Cement OPC 53 Grade",
                            "unit": "MT",
                            "unit_price": 320.00,
                            "currency": "INR",
                        }
                    ],
                },
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["contract_ref"] == "TS-2024-001"
    assert data["version"]["version_number"] == 1
    assert data["version"]["line_item_count"] == 1


# ── Test 5: Create contract invalid vendor → 404 ─────────────────────


def test_create_contract_invalid_vendor():
    db = _db()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.contracts.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/contracts/",
            json={
                "vendor_id": str(uuid.uuid4()),
                "version": {
                    "valid_from": "2024-01-01",
                    "valid_to": "2024-12-31",
                    "line_items": [
                        {"item_desc": "X", "unit": "MT", "unit_price": 100.0}
                    ],
                },
            },
        )

    assert response.status_code == 404


# ── Test 6: Create contract invalid date range → 400 ─────────────────


def test_create_contract_invalid_dates():
    db = _db()

    vendor = MagicMock()
    vendor.id = VENDOR_ID
    result = MagicMock()
    result.scalar_one_or_none.return_value = vendor
    db.execute.return_value = result

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.api.endpoints.contracts.set_tenant_context", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/contracts/",
            json={
                "vendor_id": str(VENDOR_ID),
                "version": {
                    "valid_from": "2024-12-31",
                    "valid_to": "2024-01-01",  # before valid_from
                    "line_items": [
                        {"item_desc": "X", "unit": "MT", "unit_price": 100.0}
                    ],
                },
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "VALIDATION_ERROR"
