"""
Tests for Admin API endpoints
POST /admin/fx-rates/upload
GET  /admin/fx-rates
PUT  /admin/tenant-settings
GET  /admin/tenant-settings
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.api.endpoints.admin import router
from backend.app.core.security import CurrentUser, get_current_user

TENANT = uuid.uuid4()
USER = uuid.uuid4()


# ── helpers ────────────────────────────────────────────────────────────


def _admin_user() -> CurrentUser:
    return CurrentUser(
        user_id=USER, tenant_id=TENANT, email="admin@co.com", role="ADMIN"
    )


def _reviewer_user() -> CurrentUser:
    return CurrentUser(
        user_id=USER, tenant_id=TENANT, email="reviewer@co.com", role="REVIEWER"
    )


async def _db():
    return AsyncMock()


def _create_app(user: CurrentUser, db_mock=None):
    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[get_current_user] = lambda: user
    if db_mock:
        from backend.app.core.database import get_db

        app.dependency_overrides[get_db] = lambda: db_mock
    return app


# ── FX Rates Upload ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_fx_rates_success():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/admin/fx-rates/upload",
                json={
                    "rates": [
                        {
                            "from_currency": "usd",
                            "to_currency": "inr",
                            "rate": 83.5,
                            "rate_date": "2024-06-01",
                        },
                        {
                            "from_currency": "eur",
                            "to_currency": "inr",
                            "rate": 90.2,
                            "rate_date": "2024-06-01",
                            "source": "ADMIN_IMPORT",
                        },
                    ]
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["uploaded_count"] == 2
    assert len(data["rates"]) == 2
    assert data["rates"][0]["from_currency"] == "USD"
    assert data["rates"][1]["from_currency"] == "EUR"


@pytest.mark.asyncio
async def test_upload_fx_rates_empty_list():
    mock_db = AsyncMock()
    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post("/admin/fx-rates/upload", json={"rates": []})

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_fx_rates_reviewer_forbidden():
    mock_db = AsyncMock()
    app = _create_app(_reviewer_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/admin/fx-rates/upload",
                json={
                    "rates": [
                        {
                            "from_currency": "usd",
                            "to_currency": "inr",
                            "rate": 83.5,
                            "rate_date": "2024-06-01",
                        }
                    ]
                },
            )

    assert resp.status_code == 403


# ── FX Rates List ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_fx_rates():
    mock_rate = MagicMock()
    mock_rate.id = uuid.uuid4()
    mock_rate.from_currency = "USD"
    mock_rate.to_currency = "INR"
    mock_rate.rate = Decimal("83.5")
    mock_rate.rate_date = date(2024, 6, 1)
    mock_rate.source = "MANUAL_UPLOAD"
    mock_rate.uploaded_by_user_id = USER
    mock_rate.created_at = datetime(2024, 6, 1, 12, 0, 0)

    mock_db = AsyncMock()

    # First execute → count
    count_result = MagicMock()
    count_result.scalar.return_value = 1

    # Second execute → data
    data_scalars = MagicMock()
    data_scalars.all.return_value = [mock_rate]
    data_result = MagicMock()
    data_result.scalars.return_value = data_scalars

    mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/admin/fx-rates?from_currency=USD")

    assert resp.status_code == 200
    data = resp.json()
    assert data["pagination"]["total_records"] == 1
    assert len(data["data"]) == 1
    assert data["data"][0]["from_currency"] == "USD"


# ── Tenant Settings GET ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tenant_settings():
    mock_settings = MagicMock()
    mock_settings.fuzzy_threshold = 0.85
    mock_settings.duplicate_window_days = 7
    mock_settings.manual_review_threshold = 0.7
    mock_settings.base_currency = "INR"
    mock_settings.abbreviation_dictionary = {"kg": "kilogram"}
    mock_settings.updated_at = None

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mock_settings
    mock_db.execute = AsyncMock(return_value=result_mock)

    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/admin/tenant-settings")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == str(TENANT)
    assert data["fuzzy_threshold"] == 0.85
    assert data["base_currency"] == "INR"


@pytest.mark.asyncio
async def test_get_tenant_settings_not_found():
    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result_mock)

    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/admin/tenant-settings")

    assert resp.status_code == 404


# ── Tenant Settings PUT ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_tenant_settings_scalars():
    mock_settings = MagicMock()
    mock_settings.fuzzy_threshold = 0.85
    mock_settings.duplicate_window_days = 7
    mock_settings.manual_review_threshold = 0.7
    mock_settings.base_currency = "INR"
    mock_settings.abbreviation_dictionary = {"kg": "kilogram"}

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mock_settings
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.flush = AsyncMock()

    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                "/admin/tenant-settings",
                json={"fuzzy_threshold": 0.9, "base_currency": "USD"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert mock_settings.fuzzy_threshold == 0.9
    assert mock_settings.base_currency == "USD"


@pytest.mark.asyncio
async def test_update_tenant_settings_merge_abbreviations():
    from backend.app.models.tenant import DEFAULT_ABBREVIATION_DICTIONARY

    mock_settings = MagicMock()
    mock_settings.fuzzy_threshold = 0.85
    mock_settings.duplicate_window_days = 7
    mock_settings.manual_review_threshold = 0.7
    mock_settings.base_currency = "INR"
    mock_settings.abbreviation_dictionary = dict(DEFAULT_ABBREVIATION_DICTIONARY)

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mock_settings
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.flush = AsyncMock()

    app = _create_app(_admin_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                "/admin/tenant-settings",
                json={
                    "abbreviation_dictionary_additions": {
                        "doz": "dozen",
                        "pkt": "packet",
                    }
                },
            )

    assert resp.status_code == 200
    updated_dict = mock_settings.abbreviation_dictionary
    # New entries merged
    assert updated_dict["doz"] == "dozen"
    assert updated_dict["pkt"] == "packet"
    # System defaults preserved
    for key, value in DEFAULT_ABBREVIATION_DICTIONARY.items():
        assert key in updated_dict


@pytest.mark.asyncio
async def test_update_tenant_settings_reviewer_forbidden():
    mock_db = AsyncMock()
    app = _create_app(_reviewer_user(), mock_db)

    with patch("backend.app.api.endpoints.admin.set_tenant_context", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                "/admin/tenant-settings",
                json={"base_currency": "USD"},
            )

    assert resp.status_code == 403
