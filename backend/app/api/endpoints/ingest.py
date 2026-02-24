"""
LeakSight V1 — File Ingestion Endpoints

Source: docs/API_CONTRACTS.md (Section 3 — File Ingestion Endpoints),
       docs/PARSING_SPEC.md (Section 3 — Supported Formats),
       docs/DATABASE_SCHEMA.md (Sections 2.1, 4.3 — documents, document_hashes)

Endpoints:
  POST /api/v1/ingest/upload       — Upload a single document
  POST /api/v1/ingest/trigger-run  — Trigger an analysis run
  GET  /api/v1/ingest/runs/{run_id}/status — Get run status
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.derived import AnalysisRun, DocumentHash
from backend.app.models.raw import Document
from backend.app.services import analysis_run_service
from backend.app.tasks.parse_task import parse_document
from backend.app.tasks.analysis_run_task import run_analysis

logger = get_logger(__name__)

router = APIRouter()

# Supported file extensions per PARSING_SPEC.md Section 3
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".xlsx", ".xls", ".csv", ".docx",
})

# MIME type mapping for supported formats
EXTENSION_MIME_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Valid doc_type values per DATABASE_SCHEMA.md
VALID_DOC_TYPES: frozenset[str] = frozenset({"INVOICE", "CONTRACT", "PO", "GRN"})


class TriggerRunRequest(BaseModel):
    """Request schema for POST /api/v1/ingest/trigger-run."""

    document_ids: list[uuid.UUID]
    run_label: str | None = None


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload a document for processing.

    Validates file size and format, computes SHA-256 hash, stores file
    to disk, creates documents row and document_hashes BASELINE record.

    Args:
        file: Uploaded file (multipart/form-data).
        doc_type: Document type — INVOICE, CONTRACT, PO, or GRN.
        current_user: Decoded JWT payload from auth dependency.
        db: Async database session.

    Returns:
        Document metadata including document_id.
    """
    settings = get_settings()
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # ── Validate doc_type ───────────────────────────────────────────
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid doc_type '{doc_type}'. "
                    f"Must be one of: {', '.join(sorted(VALID_DOC_TYPES))}",
                }
            },
        )

    # ── Validate file format ────────────────────────────────────────
    original_filename = file.filename or "unknown"
    file_ext = Path(original_filename).suffix.lower()
    if file_ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "UNSUPPORTED_FORMAT",
                    "message": (
                        f"File format '{file_ext}' is not supported. "
                        f"Accepted formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                    ),
                }
            },
        )

    # ── Read file and validate size ─────────────────────────────────
    file_bytes = await file.read()
    file_size = len(file_bytes)
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    if file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "FILE_TOO_LARGE",
                    "message": (
                        f"File size ({file_size} bytes) exceeds "
                        f"{settings.max_upload_size_mb}MB limit"
                    ),
                    "details": [
                        {
                            "field": "file_size",
                            "message": (
                                f"File size exceeds {settings.max_upload_size_mb}MB limit"
                            ),
                        }
                    ],
                }
            },
        )

    # ── Compute SHA-256 hash ────────────────────────────────────────
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # ── Check for re-upload (same hash for same tenant) ─────────────
    existing_doc_stmt = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.sha256_hash == sha256_hash,
    )
    result = await db.execute(existing_doc_stmt)
    existing_doc = result.scalar_one_or_none()

    if existing_doc is not None:
        # Re-upload of same file (unchanged) — return existing document
        # Create REUPLOAD hash record per PARSING_SPEC.md Section 7.3
        # Find the current max upload_sequence for this document
        max_seq_stmt = select(func.max(DocumentHash.upload_sequence)).where(
            DocumentHash.document_id == existing_doc.id,
        )
        max_seq_result = await db.execute(max_seq_stmt)
        max_seq = max_seq_result.scalar() or 0

        reupload_hash = DocumentHash(
            document_id=existing_doc.id,
            tenant_id=tenant_id,
            hash_sha256=sha256_hash,
            hash_type="REUPLOAD",
            upload_sequence=max_seq + 1,
            comparison_status="UNCHANGED",
        )
        db.add(reupload_hash)
        await db.flush()

        logger.info(
            "document_reupload_unchanged",
            document_id=str(existing_doc.id),
            tenant_id=str(tenant_id),
            doc_type=doc_type,
        )

        return {
            "document_id": str(existing_doc.id),
            "filename": existing_doc.original_filename,
            "doc_type": existing_doc.doc_type,
            "sha256_hash": existing_doc.sha256_hash,
            "file_size": existing_doc.file_size,
            "parse_status": existing_doc.parse_status,
            "created_at": str(existing_doc.created_at),
            "note": "Document already uploaded (identical hash). Returning existing record.",
        }

    # ── Generate document_id and write file to storage ──────────────
    document_id = uuid.uuid4()
    storage_path = Path(settings.document_storage_path)
    file_dir = storage_path / str(tenant_id) / str(document_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_full_path = file_dir / original_filename

    file_full_path.write_bytes(file_bytes)

    # ── Determine MIME type ─────────────────────────────────────────
    mime_type = EXTENSION_MIME_MAP.get(file_ext, "application/octet-stream")

    # ── Relative file path for database storage ─────────────────────
    relative_path = f"{tenant_id}/{document_id}/{original_filename}"

    # ── Create documents row ────────────────────────────────────────
    doc = Document(
        id=document_id,
        tenant_id=tenant_id,
        file_path=relative_path,
        original_filename=original_filename,
        sha256_hash=sha256_hash,
        doc_type=doc_type,
        file_size=file_size,
        mime_type=mime_type,
    )
    db.add(doc)
    await db.flush()

    # ── Create document_hashes BASELINE record ──────────────────────
    baseline_hash = DocumentHash(
        document_id=document_id,
        tenant_id=tenant_id,
        hash_sha256=sha256_hash,
        hash_type="BASELINE",
        upload_sequence=1,
        comparison_status="NEW",
    )
    db.add(baseline_hash)
    await db.flush()

    # ── Log upload (only permitted fields) ──────────────────────────
    logger.info(
        "document_uploaded",
        document_id=str(document_id),
        tenant_id=str(tenant_id),
        doc_type=doc_type,
        count=file_size,
    )

    # ── Queue parse task (Phase 5) ──────────────────────────────────
    parse_document.delay(str(document_id), str(tenant_id))
    logger.info(
        "parse_task_queued",
        document_id=str(document_id),
        tenant_id=str(tenant_id),
    )

    return {
        "document_id": str(document_id),
        "filename": original_filename,
        "doc_type": doc_type,
        "sha256_hash": sha256_hash,
        "file_size": file_size,
        "parse_status": "PENDING",
        "created_at": str(doc.created_at) if doc.created_at else None,
    }


@router.post("/trigger-run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(
    request: TriggerRunRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger an analysis run on specified documents.

    Validates all document_ids belong to requesting tenant, creates
    an analysis_run record in QUEUED status.

    Args:
        request: Request body with document_ids and optional run_label.
        current_user: Decoded JWT payload.
        db: Async database session.

    Returns:
        Run metadata including run_id and status.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    if not request.document_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "document_ids must not be empty",
                }
            },
        )

    # ── Confirm all document_ids belong to the requesting tenant ────
    doc_count_stmt = (
        select(func.count())
        .select_from(Document)
        .where(
            Document.id.in_(request.document_ids),
            Document.tenant_id == tenant_id,
        )
    )
    result = await db.execute(doc_count_stmt)
    owned_count = result.scalar() or 0

    if owned_count != len(request.document_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": (
                        "One or more document_ids do not belong to the "
                        "requesting tenant or do not exist"
                    ),
                }
            },
        )

    # ── Create analysis run ─────────────────────────────────────────
    run = await analysis_run_service.create_run(
        tenant_id=tenant_id,
        total_documents=len(request.document_ids),
        db=db,
    )
    await db.flush()

    # ── Update documents with run_id ────────────────────────────────
    for doc_id in request.document_ids:
        doc_stmt = select(Document).where(Document.id == doc_id)
        doc_result = await db.execute(doc_stmt)
        doc = doc_result.scalar_one_or_none()
        if doc:
            doc.run_id = run.id

    await db.flush()

    # ── Queue analysis run task (Phase 5) ──────────────────────────
    run_analysis.delay(str(run.id), str(tenant_id))
    logger.info(
        "analysis_run_queued",
        run_id=str(run.id),
        tenant_id=str(tenant_id),
        total=len(request.document_ids),
    )

    return {
        "run_id": str(run.id),
        "status": "QUEUED",
        "total_documents": len(request.document_ids),
        "created_at": str(run.created_at) if run.created_at else None,
    }


@router.get("/runs/{run_id}/status")
async def get_run_status(
    run_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current status and progress of an analysis run.

    Confirms run belongs to requesting tenant. Returns count of
    leakage records by status for frontend progress display.

    Args:
        run_id: UUID of the analysis run.
        current_user: Decoded JWT payload.
        db: Async database session.

    Returns:
        Run status with progress information.
    """
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    # ── Load run ────────────────────────────────────────────────────
    stmt = select(AnalysisRun).where(
        AnalysisRun.id == run_id,
        AnalysisRun.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Analysis run {run_id} not found",
                }
            },
        )

    # ── Calculate progress ──────────────────────────────────────────
    total = run.total_documents or 0
    processed = run.processed_documents or 0
    progress = round((processed / total * 100), 1) if total > 0 else 0.0

    return {
        "run_id": str(run.id),
        "status": run.status,
        "total_documents": total,
        "processed_documents": processed,
        "progress_percentage": progress,
        "total_leakage_found": float(run.total_leakage_found or 0),
        "leakage_record_count": run.leakage_record_count or 0,
        "error_summary": run.error_summary,
        "started_at": str(run.started_at) if run.started_at else None,
        "completed_at": str(run.completed_at) if run.completed_at else None,
        "created_at": str(run.created_at) if run.created_at else None,
    }
