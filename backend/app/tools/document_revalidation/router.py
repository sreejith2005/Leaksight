"""FastAPI router for Tool C document revalidation."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.core.tenant_context import set_tenant_context
from backend.app.tools.document_revalidation.models import (
    RevalidationAlert,
    RevalidationDocCatalog,
    RevalidationDocument,
    RevalidationSubject,
)
from backend.app.tools.document_revalidation.schemas import (
    AlertResponse,
    AttachDocumentRequest,
    DocCatalogResponse,
    ManualDateUpdate,
    RevalidationDocCreate,
    RevalidationDocResponse,
    SubjectCreate,
    SubjectResponse,
)
from backend.app.tools.document_revalidation.service import (
    _revalidation_doc_response,
    attach_document,
    create_revalidation_doc,
    create_subject,
    get_compliance_dashboard,
    get_subject,
    list_alerts,
    list_subjects,
    update_dates_manually,
)
from backend.app.tools.document_revalidation.tasks import daily_expiry_check_task

router = APIRouter()


def _not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject_endpoint(
    body: SubjectCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubjectResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)
    return await create_subject(db, tenant_id, body)


@router.get("/subjects")
async def list_subjects_endpoint(
    subject_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    filters = [RevalidationSubject.tenant_id == tenant_id]
    if subject_type is not None:
        filters.append(RevalidationSubject.subject_type == subject_type)

    total = (
        await db.execute(
            select(func.count()).select_from(RevalidationSubject).where(*filters)
        )
    ).scalar_one()

    items = await list_subjects(
        db=db,
        tenant_id=tenant_id,
        subject_type=subject_type,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


@router.get("/subjects/{subject_id}", response_model=SubjectResponse)
async def get_subject_endpoint(
    subject_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubjectResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    subject = await get_subject(db, tenant_id, subject_id)
    if subject is None:
        _not_found()
    return subject


@router.get("/catalog", response_model=list[DocCatalogResponse])
async def list_catalog_endpoint(
    subject_type: str | None = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocCatalogResponse]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    filters = [
        or_(
            RevalidationDocCatalog.tenant_id.is_(None),
            RevalidationDocCatalog.tenant_id == tenant_id,
        )
    ]
    if subject_type is not None:
        filters.append(RevalidationDocCatalog.subject_type == subject_type)

    catalog_items = list(
        (
            await db.execute(
                select(RevalidationDocCatalog)
                .where(*filters)
                .order_by(
                    RevalidationDocCatalog.subject_type.asc(),
                    RevalidationDocCatalog.display_name.asc(),
                )
            )
        ).scalars()
    )
    return [DocCatalogResponse.model_validate(item) for item in catalog_items]


@router.post(
    "/subjects/{subject_id}/documents",
    response_model=RevalidationDocResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_revalidation_doc_endpoint(
    subject_id: UUID,
    body: RevalidationDocCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevalidationDocResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    payload = body.model_copy(update={"subject_id": subject_id})
    return await create_revalidation_doc(db, tenant_id, payload)


@router.get("/subjects/{subject_id}/documents", response_model=list[RevalidationDocResponse])
async def list_subject_documents_endpoint(
    subject_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RevalidationDocResponse]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    subject = await db.scalar(
        select(RevalidationSubject).where(
            RevalidationSubject.id == subject_id,
            RevalidationSubject.tenant_id == tenant_id,
        )
    )
    if subject is None:
        _not_found()

    docs = list(
        (
            await db.execute(
                select(RevalidationDocument)
                .where(
                    RevalidationDocument.subject_id == subject_id,
                    RevalidationDocument.tenant_id == tenant_id,
                )
                .order_by(RevalidationDocument.created_at.desc())
            )
        ).scalars()
    )
    return [
        _revalidation_doc_response(doc, include_days_until_expiry=True)
        for doc in docs
    ]


@router.get("/documents/{reval_doc_id}", response_model=RevalidationDocResponse)
async def get_revalidation_doc_endpoint(
    reval_doc_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevalidationDocResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    revalidation_doc = await db.scalar(
        select(RevalidationDocument).where(
            RevalidationDocument.id == reval_doc_id,
            RevalidationDocument.tenant_id == tenant_id,
        )
    )
    if revalidation_doc is None:
        _not_found()
    return _revalidation_doc_response(revalidation_doc, include_days_until_expiry=True)


@router.post("/documents/{reval_doc_id}/attach", response_model=RevalidationDocResponse)
async def attach_document_endpoint(
    reval_doc_id: UUID,
    body: AttachDocumentRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevalidationDocResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)
    return await attach_document(db, tenant_id, reval_doc_id, body.document_id)


@router.put("/documents/{reval_doc_id}/dates", response_model=RevalidationDocResponse)
async def update_dates_manually_endpoint(
    reval_doc_id: UUID,
    body: ManualDateUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevalidationDocResponse:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)
    return await update_dates_manually(db, tenant_id, reval_doc_id, body)


@router.get("/dashboard")
async def get_dashboard_endpoint(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)
    return await get_compliance_dashboard(db, tenant_id)


@router.get("/alerts")
async def list_alerts_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    total = (
        await db.execute(
            select(func.count()).select_from(RevalidationAlert).where(
                RevalidationAlert.tenant_id == tenant_id,
            )
        )
    ).scalar_one()
    items = await list_alerts(db, tenant_id, page, page_size)
    return {
        "items": [AlertResponse.model_validate(item).model_dump(mode="json") for item in items],
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


@router.post("/admin/check-expiry", status_code=status.HTTP_202_ACCEPTED)
async def queue_expiry_check_endpoint(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    tenant_id = current_user.tenant_id
    await set_tenant_context(db, tenant_id)

    if current_user.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    daily_expiry_check_task.delay(str(tenant_id))
    return {
        "message": "Expiry check queued",
        "tenant_id": str(tenant_id),
    }
