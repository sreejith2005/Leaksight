"""
Tests for LeakSight V1 — Report Endpoints (Phase 7)

Source: docs/API_CONTRACTS.md (Section 7)

Tests:
1. Run summary → 200 with assembler data as JSON
2. Run summary not found → 404
3. Evidence pack → 200 with application/pdf
4. Evidence pack not found → 404
5. Evidence pack render failure → 500
6. Excel export → 200 with xlsx MIME type
7. Excel export not found → 404
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.reports import router
from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.reporting.report_assembler import (
    CFOSummaryData,
    ConfidenceBandSummary,
    EvidencePackData,
    ExcelExportData,
    RuleLeakageSummary,
    SummarySheetData,
    VendorLeakageSummary,
)
from backend.app.reporting.pdf_renderer import ReportGenerationError

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
RUN_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")


def _create_app(user=None, db_mock=None):
    app = FastAPI()
    r = APIRouter(prefix="/api/v1/reports", tags=["reports"])
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


def _sample_cfo_data() -> CFOSummaryData:
    return CFOSummaryData(
        run_id=RUN_ID,
        run_status="COMPLETE",
        started_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2025, 6, 1, 11, 0, tzinfo=timezone.utc),
        total_leakage_amount=Decimal("150000.00"),
        currency="INR",
        leakage_by_vendor=[
            VendorLeakageSummary(vendor_name="Tata Steel", total_amount=Decimal("50000.00"), record_count=5),
        ],
        leakage_by_rule=[
            RuleLeakageSummary(rule_type="RULE_1_PRICE_MISMATCH", total_amount=Decimal("150000.00"), record_count=20),
        ],
        leakage_by_confidence_band=ConfidenceBandSummary(
            high_count=15, high_amount=Decimal("120000.00"),
            medium_count=3, medium_amount=Decimal("20000.00"),
            low_count=2, low_amount=Decimal("10000.00"),
        ),
        pending_review_count=5,
        pending_fx_rate_count=0,
        partial_success_notes=None,
        report_generated_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


def _sample_evidence_data() -> EvidencePackData:
    return EvidencePackData(
        run_id=RUN_ID,
        tenant_name="Acme Corp",
        report_generated_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        total_leakage_amount=Decimal("5000.00"),
        currency="INR",
        findings=[],
    )


def _sample_excel_data() -> ExcelExportData:
    return ExcelExportData(
        run_id=RUN_ID,
        generated_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        summary_sheet=SummarySheetData(
            run_id=RUN_ID,
            generated_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
            total_leakage_amount=Decimal("15000.00"),
            currency="INR",
            vendor_breakdown=[],
            rule_breakdown=[],
        ),
        price_mismatch_sheet=[],
        duplicate_invoice_sheet=[],
        quantity_mismatch_sheet=[],
        vendor_breakdown_sheet=[],
    )


FAKE_PDF = b"%PDF-1.4 fake-content"
FAKE_XLSX = b"PK\x03\x04fake-xlsx"

_PATCH_PREFIX = "backend.app.api.endpoints.reports"


# ── Test 1: Run summary → 200 ────────────────────────────────────────


@patch(f"{_PATCH_PREFIX}.assemble_cfo_summary", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_run_summary(mock_ctx, mock_assemble):
    mock_assemble.return_value = _sample_cfo_data()

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{RUN_ID}/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(RUN_ID)
    assert data["summary"]["total_leakage"] == 150000.0
    assert data["summary"]["currency"] == "INR"
    assert data["summary"]["top_vendors"][0]["vendor_name"] == "Tata Steel"
    assert data["summary"]["confidence_bands"]["high"]["count"] == 15


# ── Test 2: Run summary not found → 404 ──────────────────────────────


@patch(f"{_PATCH_PREFIX}.assemble_cfo_summary", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_run_summary_not_found(mock_ctx, mock_assemble):
    mock_assemble.side_effect = ValueError("Run not found")

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{uuid.uuid4()}/summary")

    assert response.status_code == 404


# ── Test 3: Evidence pack → 200 PDF ──────────────────────────────────


@patch(f"{_PATCH_PREFIX}.render_to_pdf")
@patch(f"{_PATCH_PREFIX}.assemble_evidence_pack", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_evidence_pack_pdf(mock_ctx, mock_assemble, mock_render):
    mock_assemble.return_value = _sample_evidence_data()
    mock_render.return_value = FAKE_PDF

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{RUN_ID}/evidence-pack")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")


# ── Test 4: Evidence pack not found → 404 ────────────────────────────


@patch(f"{_PATCH_PREFIX}.assemble_evidence_pack", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_evidence_pack_not_found(mock_ctx, mock_assemble):
    mock_assemble.side_effect = ValueError("Run not found")

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{uuid.uuid4()}/evidence-pack")

    assert response.status_code == 404


# ── Test 5: Evidence pack render failure → 500 ───────────────────────


@patch(f"{_PATCH_PREFIX}.render_to_pdf")
@patch(f"{_PATCH_PREFIX}.assemble_evidence_pack", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_evidence_pack_render_failure(mock_ctx, mock_assemble, mock_render):
    mock_assemble.return_value = _sample_evidence_data()
    mock_render.side_effect = ReportGenerationError("font issue")

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{RUN_ID}/evidence-pack")

    assert response.status_code == 500
    assert "REPORT_GENERATION_FAILED" in response.json()["detail"]["error"]["code"]


# ── Test 6: Excel export → 200 xlsx ──────────────────────────────────


@patch(f"{_PATCH_PREFIX}.generate_excel_export")
@patch(f"{_PATCH_PREFIX}.assemble_excel_export", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_excel_export_xlsx(mock_ctx, mock_assemble, mock_gen):
    mock_assemble.return_value = _sample_excel_data()
    mock_gen.return_value = FAKE_XLSX

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{RUN_ID}/export-excel")

    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"PK")


# ── Test 7: Excel export not found → 404 ─────────────────────────────


@patch(f"{_PATCH_PREFIX}.assemble_excel_export", new_callable=AsyncMock)
@patch(f"{_PATCH_PREFIX}.set_tenant_context", new_callable=AsyncMock)
def test_excel_export_not_found(mock_ctx, mock_assemble):
    mock_assemble.side_effect = ValueError("Run not found")

    app = _create_app(user=_user(), db_mock=_db())
    client = TestClient(app)
    response = client.get(f"/api/v1/reports/runs/{uuid.uuid4()}/export-excel")

    assert response.status_code == 404
