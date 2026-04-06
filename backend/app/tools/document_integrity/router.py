"""FastAPI router for Tool B."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.derived import DocumentHash
from backend.app.models.raw import Document
from backend.app.tools.document_integrity.analyzers.risk_scorer import risk_level_from_score
from backend.app.tools.document_integrity.schemas import (
    BatchAnalyzeRequest,
    IntegrityListItem,
    IntegrityListResponse,
    IntegrityReport,
    NumericChange,
)
from backend.app.tools.document_integrity.tasks import run_integrity_analysis

router = APIRouter()


def _not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _risk_filter_bounds(risk_level: str) -> tuple[int, int]:
    normalized = risk_level.upper()
    if normalized == "LOW":
        return (0, 30)
    if normalized == "MEDIUM":
        return (31, 69)
    if normalized == "HIGH":
        return (70, 100)
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid risk_level")


def _build_report(document: Document, document_hash: DocumentHash, version_count: int) -> IntegrityReport:
    payload = document_hash.flagged_anomalies_jsonb or {}
    raw_numeric_changes = payload.get("numeric_changes") if isinstance(payload, dict) else []
    raw_flags = payload.get("flags") if isinstance(payload, dict) else []
    return IntegrityReport(
        document_id=str(document.id),
        filename=document.original_filename,
        doc_type=str(document.doc_type),
        risk_score=document_hash.risk_score,
        risk_level=risk_level_from_score(document_hash.risk_score),
        comparison_status=str(document_hash.comparison_status),
        version_count=version_count,
        flags=[str(flag) for flag in (raw_flags or [])],
        numeric_changes=[NumericChange.model_validate(change) for change in (raw_numeric_changes or [])],
        metadata=document_hash.metadata_jsonb or {},
        analyzed_at=document_hash.created_at if document_hash.risk_score is not None else None,
    )


@router.post("/analyze/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def analyze_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    if document is None:
        _not_found()

    run_integrity_analysis.delay(str(document_id), str(tenant_id))
    return {
        "task_queued": True,
        "document_id": str(document_id),
    }


@router.get("/documents", response_model=IntegrityListResponse)
async def list_integrity_documents(
    risk_level: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrityListResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    latest_hash_sq = (
        select(
            DocumentHash.document_id.label("document_id"),
            func.max(DocumentHash.upload_sequence).label("max_upload_sequence"),
        )
        .where(DocumentHash.tenant_id == tenant_id)
        .group_by(DocumentHash.document_id)
        .subquery()
    )

    filters = [Document.tenant_id == tenant_id]
    if risk_level is not None:
        low, high = _risk_filter_bounds(risk_level)
        filters.extend([
            DocumentHash.risk_score.is_not(None),
            DocumentHash.risk_score >= low,
            DocumentHash.risk_score <= high,
        ])

    count_stmt = (
        select(func.count())
        .select_from(Document)
        .join(latest_hash_sq, latest_hash_sq.c.document_id == Document.id)
        .join(
            DocumentHash,
            and_(
                DocumentHash.document_id == latest_hash_sq.c.document_id,
                DocumentHash.upload_sequence == latest_hash_sq.c.max_upload_sequence,
                DocumentHash.tenant_id == tenant_id,
            ),
        )
        .where(*filters)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    data_stmt = (
        select(Document, DocumentHash)
        .join(latest_hash_sq, latest_hash_sq.c.document_id == Document.id)
        .join(
            DocumentHash,
            and_(
                DocumentHash.document_id == latest_hash_sq.c.document_id,
                DocumentHash.upload_sequence == latest_hash_sq.c.max_upload_sequence,
                DocumentHash.tenant_id == tenant_id,
            ),
        )
        .where(*filters)
        .order_by(DocumentHash.risk_score.desc().nullslast(), DocumentHash.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(data_stmt)).all())

    items = [
        IntegrityListItem(
            document_id=str(document.id),
            filename=document.original_filename,
            doc_type=str(document.doc_type),
            risk_score=document_hash.risk_score,
            risk_level=risk_level_from_score(document_hash.risk_score),
            comparison_status=str(document_hash.comparison_status) if document_hash.comparison_status is not None else None,
            analyzed_at=document_hash.created_at,
        )
        for document, document_hash in rows
    ]

    return IntegrityListResponse(
        items=items,
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get("/documents/{document_id}", response_model=IntegrityReport)
async def get_integrity_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrityReport:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    if document is None:
        _not_found()

    hash_rows = list(
        (
            await db.execute(
                select(DocumentHash)
                .where(
                    DocumentHash.document_id == document_id,
                    DocumentHash.tenant_id == tenant_id,
                )
                .order_by(DocumentHash.upload_sequence.asc())
            )
        ).scalars()
    )
    if not hash_rows:
        _not_found()

    latest_hash = hash_rows[-1]
    version_count = len(hash_rows)
    if version_count == 1:
        version_count = (
            await db.execute(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.tenant_id == tenant_id,
                    Document.original_filename == document.original_filename,
                    Document.doc_type == document.doc_type,
                )
            )
        ).scalar_one()

    return _build_report(document, latest_hash, int(version_count))


@router.post("/analyze-batch")
async def analyze_batch(
    body: BatchAnalyzeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    unique_ids = list(dict.fromkeys(body.document_ids))
    document_uuids = [UUID(str(document_id)) for document_id in unique_ids]

    owned_count = (
        await db.execute(
            select(func.count()).select_from(Document).where(
                Document.id.in_(document_uuids),
                Document.tenant_id == tenant_id,
            )
        )
    ).scalar_one()
    if owned_count != len(document_uuids):
        _not_found()

    for document_id in document_uuids:
        run_integrity_analysis.delay(str(document_id), str(tenant_id))

    return {
        "queued": len(document_uuids),
        "document_ids": [str(document_id) for document_id in document_uuids],
    }
