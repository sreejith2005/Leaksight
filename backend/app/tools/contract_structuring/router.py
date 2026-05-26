"""FastAPI router for Tool A contract structuring."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.raw import Document
from backend.app.tools.contract_structuring.models import (
    ContractStructuringExport,
    ContractStructuringRun,
    ContractStructuringRunDocument,
    ExtractedClause,
    ExtractedLineItem,
    RawContractTable,
)
from backend.app.tools.contract_structuring.schemas import (
    ClauseResponse,
    CreateStructuringRunRequest,
    ExportTriggerResponse,
    LineItemResponse,
    PaginatedRunsResponse,
    RejectLineItemRequest,
    RunDocumentResponse,
    StructuringExportResponse,
    StructuringRunResponse,
    StructuringRunResultsResponse,
    StructuringRunStatusResponse,
    UpdateClauseRequest,
    UpdateLineItemRequest,
)
from backend.app.tools.contract_structuring.service import create_structuring_run
from backend.app.tools.contract_structuring.tasks import generate_structuring_export

router = APIRouter()


def _not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _run_response(run: ContractStructuringRun) -> StructuringRunResponse:
    return StructuringRunResponse.model_validate(run)


def _line_item_response(item: ExtractedLineItem, extraction_method: str | None = None) -> LineItemResponse:
    payload = {
        field_name: getattr(item, field_name)
        for field_name in LineItemResponse.model_fields
        if field_name != "extraction_method"
    }
    raw_contract_id = getattr(item, "contract_id", None)
    payload["contract_id"] = raw_contract_id if isinstance(raw_contract_id, str) else None
    payload["extraction_method"] = extraction_method if isinstance(extraction_method, str) else None
    return LineItemResponse.model_validate(payload)


async def _resolve_extraction_method(
    db: AsyncSession,
    tenant_id: UUID,
    raw_table_id: UUID,
) -> str | None:
    return await db.scalar(
        select(RawContractTable.extraction_method).where(
            RawContractTable.id == raw_table_id,
            RawContractTable.tenant_id == tenant_id,
        )
    )


def _clause_response(clause: ExtractedClause) -> ClauseResponse:
    return ClauseResponse.model_validate(clause)


@router.post("/runs", response_model=StructuringRunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateStructuringRunRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StructuringRunResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    if not body.document_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="document_ids must not be empty")

    unique_document_ids = list(dict.fromkeys(body.document_ids))

    owned_doc_count = (
        await db.execute(
            select(func.count()).select_from(Document).where(
                Document.tenant_id == tenant_id,
                Document.id.in_(unique_document_ids),
            )
        )
    ).scalar_one()

    if owned_doc_count != len(unique_document_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more document_ids do not belong to the current tenant",
        )

    run_id = await create_structuring_run(
        document_ids=unique_document_ids,
        run_label=body.run_label,
        tenant_id=tenant_id,
        user_id=current_user.user_id,
        db=db,
    )

    run = await db.scalar(
        select(ContractStructuringRun).where(
            ContractStructuringRun.id == run_id,
            ContractStructuringRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        _not_found()

    return _run_response(run)


@router.get("/runs", response_model=PaginatedRunsResponse)
async def list_runs(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedRunsResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    filters = [ContractStructuringRun.tenant_id == tenant_id]
    if status_filter:
        filters.append(ContractStructuringRun.status == status_filter)

    total = (
        await db.execute(select(func.count()).select_from(ContractStructuringRun).where(*filters))
    ).scalar_one()

    runs = list(
        (
            await db.execute(
                select(ContractStructuringRun)
                .where(*filters)
                .order_by(ContractStructuringRun.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )

    return PaginatedRunsResponse(
        items=[_run_response(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}/status", response_model=StructuringRunStatusResponse)
async def run_status(
    run_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StructuringRunStatusResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    run = await db.scalar(
        select(ContractStructuringRun).where(
            ContractStructuringRun.id == run_id,
            ContractStructuringRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        _not_found()

    total_documents = int(getattr(run, "total_documents"))
    processed_documents = int(getattr(run, "processed_documents"))
    total_line_items_found = int(getattr(run, "total_line_items_found"))
    total_clauses_found = int(getattr(run, "total_clauses_found"))

    if total_documents <= 0:
        progress = 0.0
    else:
        progress = round((processed_documents / total_documents) * 100.0, 2)

    progress = max(0.0, min(100.0, progress))

    return StructuringRunStatusResponse(
        run_id=getattr(run, "id"),
        status=str(getattr(run, "status")),
        processed_documents=processed_documents,
        total_documents=total_documents,
        progress_percentage=progress,
        total_line_items_found=total_line_items_found,
        total_clauses_found=total_clauses_found,
    )


@router.get("/runs/{run_id}/results", response_model=StructuringRunResultsResponse)
async def run_results(
    run_id: UUID,
    document_id: UUID | None = Query(None),
    needs_review: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StructuringRunResultsResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    run = await db.scalar(
        select(ContractStructuringRun).where(
            ContractStructuringRun.id == run_id,
            ContractStructuringRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        _not_found()

    run_doc_filters = [
        ContractStructuringRunDocument.run_id == run_id,
        ContractStructuringRunDocument.tenant_id == tenant_id,
    ]
    if document_id is not None:
        run_doc_filters.append(ContractStructuringRunDocument.document_id == document_id)

    run_docs = list(
        (
            await db.execute(
                select(ContractStructuringRunDocument)
                .where(*run_doc_filters)
                .order_by(ContractStructuringRunDocument.created_at.asc())
            )
        ).scalars()
    )

    documents: list[RunDocumentResponse] = []
    for run_doc in run_docs:
        line_item_filters = [
            ExtractedLineItem.run_id == run_id,
            ExtractedLineItem.tenant_id == tenant_id,
            ExtractedLineItem.document_id == run_doc.document_id,
        ]
        if needs_review is not None:
            line_item_filters.append(ExtractedLineItem.needs_review == needs_review)

        line_items = list(
            (
                await db.execute(
                    select(ExtractedLineItem)
                    .where(*line_item_filters)
                    .order_by(ExtractedLineItem.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).scalars()
        )

        raw_table_ids = [getattr(item, "raw_table_id") for item in line_items]
        extraction_method_map: dict[UUID, str] = {}
        if raw_table_ids:
            raw_rows = list(
                (
                    await db.execute(
                        select(RawContractTable.id, RawContractTable.extraction_method).where(
                            RawContractTable.tenant_id == tenant_id,
                            RawContractTable.id.in_(raw_table_ids),
                        )
                    )
                ).all()
            )
            extraction_method_map = {
                row[0]: str(row[1]) if row[1] is not None else None
                for row in raw_rows
            }

        clauses = list(
            (
                await db.execute(
                    select(ExtractedClause)
                    .where(
                        ExtractedClause.run_id == run_id,
                        ExtractedClause.tenant_id == tenant_id,
                        ExtractedClause.document_id == run_doc.document_id,
                    )
                    .order_by(ExtractedClause.created_at.asc())
                )
            ).scalars()
        )

        run_doc_response = RunDocumentResponse.model_validate(run_doc)
        documents.append(
            run_doc_response.model_copy(
                update={
                    "line_items": [
                        _line_item_response(
                            item,
                            extraction_method_map.get(getattr(item, "raw_table_id")),
                        )
                        for item in line_items
                    ],
                    "clauses": [_clause_response(clause) for clause in clauses],
                }
            )
        )

    return StructuringRunResultsResponse(run=_run_response(run), documents=documents)


@router.patch("/line-items/{item_id}", response_model=LineItemResponse)
async def patch_line_item(
    item_id: UUID,
    body: UpdateLineItemRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LineItemResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    item = await db.scalar(
        select(ExtractedLineItem).where(
            ExtractedLineItem.id == item_id,
            ExtractedLineItem.tenant_id == tenant_id,
        )
    )
    if item is None:
        _not_found()

    item_status = str(getattr(item, "review_status"))
    if item_status == "CONFIRMED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Confirmed line items are immutable")

    update_data = body.model_dump(exclude_unset=True)
    if "unit_price" in update_data and update_data["unit_price"] is not None:
        if Decimal(update_data["unit_price"]) <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="unit_price must be greater than zero",
            )

    for field_name, value in update_data.items():
        setattr(item, field_name, value)

    setattr(item, "reviewed_by_user_id", current_user.user_id)
    setattr(item, "reviewed_at", datetime.now(timezone.utc))
    await db.commit()

    extraction_method = await _resolve_extraction_method(db, tenant_id, getattr(item, "raw_table_id"))
    return _line_item_response(item, str(extraction_method) if extraction_method is not None else None)


@router.post("/line-items/{item_id}/confirm", response_model=LineItemResponse)
async def confirm_line_item(
    item_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LineItemResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    item = await db.scalar(
        select(ExtractedLineItem).where(
            ExtractedLineItem.id == item_id,
            ExtractedLineItem.tenant_id == tenant_id,
        )
    )
    if item is None:
        _not_found()

    item_status = str(getattr(item, "review_status"))
    if item_status in {"CONFIRMED", "REJECTED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Line item cannot be confirmed")

    setattr(item, "review_status", "CONFIRMED")
    setattr(item, "reviewed_by_user_id", current_user.user_id)
    setattr(item, "reviewed_at", datetime.now(timezone.utc))
    await db.commit()

    extraction_method = await _resolve_extraction_method(db, tenant_id, getattr(item, "raw_table_id"))
    return _line_item_response(item, str(extraction_method) if extraction_method is not None else None)


@router.post("/line-items/{item_id}/reject", response_model=LineItemResponse)
async def reject_line_item(
    item_id: UUID,
    body: RejectLineItemRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LineItemResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    item = await db.scalar(
        select(ExtractedLineItem).where(
            ExtractedLineItem.id == item_id,
            ExtractedLineItem.tenant_id == tenant_id,
        )
    )
    if item is None:
        _not_found()

    item_status = str(getattr(item, "review_status"))
    if item_status == "CONFIRMED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Confirmed line items are immutable")

    setattr(item, "review_status", "REJECTED")
    setattr(item, "reviewer_notes", body.reason)
    setattr(item, "reviewed_by_user_id", current_user.user_id)
    setattr(item, "reviewed_at", datetime.now(timezone.utc))
    await db.commit()

    extraction_method = await _resolve_extraction_method(db, tenant_id, getattr(item, "raw_table_id"))
    return _line_item_response(item, str(extraction_method) if extraction_method is not None else None)


@router.patch("/clauses/{clause_id}", response_model=ClauseResponse)
async def patch_clause(
    clause_id: UUID,
    body: UpdateClauseRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClauseResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    clause = await db.scalar(
        select(ExtractedClause).where(
            ExtractedClause.id == clause_id,
            ExtractedClause.tenant_id == tenant_id,
        )
    )
    if clause is None:
        _not_found()

    data = body.model_dump(exclude_unset=True)
    if "extracted_value" in data:
        setattr(clause, "extracted_value", data["extracted_value"])
    if "reviewer_notes" in data:
        setattr(clause, "reviewer_notes", data["reviewer_notes"])
    if "review_status" in data:
        setattr(clause, "review_status", data["review_status"])
    await db.commit()

    return _clause_response(clause)


async def _trigger_export(
    run_id: UUID,
    export_format: str,
    current_user: CurrentUser,
    db: AsyncSession,
) -> ExportTriggerResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    run = await db.scalar(
        select(ContractStructuringRun).where(
            ContractStructuringRun.id == run_id,
            ContractStructuringRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        _not_found()

    generate_structuring_export.delay(
        str(run_id),
        export_format,
        str(current_user.user_id),
        str(tenant_id),
    )

    return ExportTriggerResponse(
        message="Export generation triggered",
        export_format=export_format,
        run_id=run_id,
    )


@router.post(
    "/runs/{run_id}/export/excel",
    response_model=ExportTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_excel(
    run_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExportTriggerResponse:
    return await _trigger_export(run_id, "EXCEL", current_user, db)


@router.post(
    "/runs/{run_id}/export/erp-json",
    response_model=ExportTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_erp_json_route(
    run_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExportTriggerResponse:
    return await _trigger_export(run_id, "ERP_JSON", current_user, db)


@router.post(
    "/runs/{run_id}/export/leaksight-import",
    response_model=ExportTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_leaksight_import(
    run_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExportTriggerResponse:
    return await _trigger_export(run_id, "LEAKSIGHT_IMPORT", current_user, db)


@router.get("/runs/{run_id}/exports", response_model=list[StructuringExportResponse])
async def list_exports(
    run_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StructuringExportResponse]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    run = await db.scalar(
        select(ContractStructuringRun).where(
            ContractStructuringRun.id == run_id,
            ContractStructuringRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        _not_found()

    exports = list(
        (
            await db.execute(
                select(ContractStructuringExport)
                .where(
                    ContractStructuringExport.run_id == run_id,
                    ContractStructuringExport.tenant_id == tenant_id,
                )
                .order_by(ContractStructuringExport.created_at.desc())
            )
        ).scalars()
    )

    return [StructuringExportResponse.model_validate(export) for export in exports]
