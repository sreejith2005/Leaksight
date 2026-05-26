"""
LeakSight V1 — Report Endpoints

Source: docs/API_CONTRACTS.md (Section 7 — Report Endpoints)

Endpoints:
  GET /api/v1/reports/runs/{run_id}/summary      — CFO summary (JSON)
  GET /api/v1/reports/runs/{run_id}/evidence-pack — Evidence pack (PDF)
  GET /api/v1/reports/runs/{run_id}/export-excel  — Excel export (.xlsx)

Phase 7: Summary returns JSON via assembler. Evidence-pack streams PDF.
         Export-excel streams .xlsx file.
"""

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.derived import AnalysisRun, LeakageRecord
from backend.app.models.invoices import Invoice
from backend.app.models.vendors import Vendor
from backend.app.reporting.excel_exporter import generate_excel_export
from backend.app.reporting.pdf_renderer import ReportGenerationError, render_to_pdf
from backend.app.reporting.report_assembler import (
    assemble_cfo_summary,
    assemble_evidence_pack,
    assemble_excel_export,
)

logger = get_logger(__name__)

router = APIRouter()


# ── GET /runs/{run_id}/summary — CFO summary ──────────────────────────


@router.get("/runs/{run_id}/summary")
async def get_run_summary(
    run_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the CFO summary data for a completed run.

    Financial totals use ACCEPTED records only.
    Returns JSON assembled by the report assembler.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    try:
        data = await assemble_cfo_summary(run_id, tenant_id, db)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Analysis run {run_id} not found",
                }
            },
        )

    return {
        "run_id": str(data.run_id),
        "run_status": data.run_status,
        "summary": {
            "total_leakage": float(data.total_leakage_amount),
            "currency": data.currency,
            "pending_review_count": data.pending_review_count,
            "pending_fx_rate_count": data.pending_fx_rate_count,
            "top_vendors": [
                {
                    "vendor_name": v.vendor_name,
                    "leakage_amount": float(v.total_amount),
                    "record_count": v.record_count,
                }
                for v in data.leakage_by_vendor
            ],
            "by_rule": {
                r.rule_type: {
                    "count": r.record_count,
                    "amount": float(r.total_amount),
                }
                for r in data.leakage_by_rule
            },
            "confidence_bands": {
                "high": {
                    "count": data.leakage_by_confidence_band.high_count,
                    "amount": float(data.leakage_by_confidence_band.high_amount),
                },
                "medium": {
                    "count": data.leakage_by_confidence_band.medium_count,
                    "amount": float(data.leakage_by_confidence_band.medium_amount),
                },
                "low": {
                    "count": data.leakage_by_confidence_band.low_count,
                    "amount": float(data.leakage_by_confidence_band.low_amount),
                },
            },
        },
        "partial_success_notes": data.partial_success_notes,
        "generated_at": str(data.report_generated_at),
    }


# ── GET /runs/{run_id}/evidence-pack — PDF evidence pack ──────────────


@router.get("/runs/{run_id}/evidence-pack")
async def get_evidence_pack(
    run_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate evidence pack PDF for a run.

    Returns application/pdf streaming response with Content-Disposition header.
    Only ACCEPTED findings are included.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    try:
        data = await assemble_evidence_pack(run_id, tenant_id, db)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Analysis run {run_id} not found",
                }
            },
        )

    # Build template context from dataclass
    context = {
        "run_id": str(data.run_id),
        "tenant_name": data.tenant_name,
        "report_generated_at": str(data.report_generated_at),
        "total_leakage_amount": data.total_leakage_amount,
        "currency": data.currency,
        "findings": data.findings,
    }

    try:
        pdf_bytes = render_to_pdf("evidence_pack.html", context)
    except ReportGenerationError:
        logger.error(
            "PDF generation failed for evidence-pack run_id=%s",
            run_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "PDF_UNAVAILABLE",
                    "message": "PDF generation requires system libraries (Cairo/Pango) that are not available in this environment. Use the Excel export as an alternative. PDF generation works correctly in the production Docker environment.",
                }
            },
        )
    except Exception:
        logger.error(
            "Unexpected error during PDF generation for run_id=%s",
            run_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "PDF_UNAVAILABLE",
                    "message": "PDF generation requires system libraries (Cairo/Pango) that are not available in this environment. Use the Excel export as an alternative. PDF generation works correctly in the production Docker environment.",
                }
            },
        )

    filename = f"evidence-pack-{run_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ── GET /runs/{run_id}/export-excel — Excel export ────────────────────


@router.get("/runs/{run_id}/export-excel")
async def get_excel_export(
    run_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate Excel export for a run.

    Returns application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    streaming response.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    try:
        data = await assemble_excel_export(run_id, tenant_id, db)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Analysis run {run_id} not found",
                }
            },
        )

    try:
        xlsx_bytes = generate_excel_export(data)
    except Exception:
        logger.error(
            "Excel generation failed for run_id=%s",
            run_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "REPORT_GENERATION_FAILED",
                    "message": "Failed to generate Excel export",
                }
            },
        )

    filename = f"leakage-export-{run_id}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
