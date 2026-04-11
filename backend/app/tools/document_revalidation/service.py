"""Async service layer for Tool C document revalidation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.raw import Document
from backend.app.tools.document_revalidation.models import (
    RevalidationAlert,
    RevalidationDocCatalog,
    RevalidationDocument,
    RevalidationSubject,
)
from backend.app.tools.document_revalidation.schemas import (
    AlertResponse,
    ManualDateUpdate,
    RevalidationDocCreate,
    RevalidationDocResponse,
    SubjectCreate,
    SubjectResponse,
)


def _not_found() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _duplicate_subject() -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate subject identifier")


def _subject_response(subject: RevalidationSubject, compliance_summary: dict | None = None) -> SubjectResponse:
    payload = {
        field_name: getattr(subject, field_name)
        for field_name in SubjectResponse.model_fields
        if field_name != "compliance_summary"
    }
    payload["compliance_summary"] = compliance_summary
    return SubjectResponse.model_validate(payload)


def _days_until_expiry(revalidation_doc: RevalidationDocument) -> int | None:
    if not revalidation_doc.has_expiry:
        return None
    if revalidation_doc.expiry_date is None:
        return None
    if str(revalidation_doc.status) == "NO_EXPIRY":
        return None
    return (revalidation_doc.expiry_date - date.today()).days


def _revalidation_doc_response(
    revalidation_doc: RevalidationDocument,
    *,
    include_days_until_expiry: bool = False,
) -> RevalidationDocResponse:
    payload = {
        field_name: getattr(revalidation_doc, field_name)
        for field_name in RevalidationDocResponse.model_fields
        if field_name != "days_until_expiry"
    }
    payload["days_until_expiry"] = (
        _days_until_expiry(revalidation_doc) if include_days_until_expiry else None
    )
    return RevalidationDocResponse.model_validate(payload)


async def _build_compliance_summary(
    db: AsyncSession,
    tenant_id: UUID,
    subject: RevalidationSubject,
) -> dict:
    total_required = (
        await db.execute(
            select(func.count()).select_from(RevalidationDocCatalog).where(
                RevalidationDocCatalog.subject_type == subject.subject_type,
                RevalidationDocCatalog.is_required.is_(True),
                or_(
                    RevalidationDocCatalog.tenant_id.is_(None),
                    RevalidationDocCatalog.tenant_id == tenant_id,
                ),
            )
        )
    ).scalar_one()

    status_rows = list(
        (
            await db.execute(
                select(RevalidationDocument.status, func.count())
                .where(
                    RevalidationDocument.tenant_id == tenant_id,
                    RevalidationDocument.subject_id == subject.id,
                )
                .group_by(RevalidationDocument.status)
            )
        ).all()
    )
    counts_by_status = {
        str(status_value): int(count)
        for status_value, count in status_rows
    }
    uploaded = sum(counts_by_status.values())

    return {
        "total_required": int(total_required),
        "uploaded": uploaded,
        "expired": counts_by_status.get("EXPIRED", 0),
        "expiring_soon": counts_by_status.get("EXPIRING_SOON", 0),
        "missing": max(0, int(total_required) - uploaded),
    }


async def _get_subject(db: AsyncSession, tenant_id: UUID, subject_id: UUID) -> RevalidationSubject | None:
    return await db.scalar(
        select(RevalidationSubject).where(
            RevalidationSubject.id == subject_id,
            RevalidationSubject.tenant_id == tenant_id,
        )
    )


async def _get_revalidation_doc(
    db: AsyncSession,
    tenant_id: UUID,
    reval_doc_id: UUID,
) -> RevalidationDocument | None:
    return await db.scalar(
        select(RevalidationDocument)
        .options(selectinload(RevalidationDocument.subject))
        .where(
            RevalidationDocument.id == reval_doc_id,
            RevalidationDocument.tenant_id == tenant_id,
        )
    )


def _compute_status(reval_doc: RevalidationDocument) -> str:
    """Compute the current status for a revalidation document."""
    if not reval_doc.has_expiry:
        return "NO_EXPIRY"
    if reval_doc.expiry_date is None:
        return "REVALIDATION_PENDING"
    if reval_doc.expiry_date < date.today():
        return "EXPIRED"
    if reval_doc.expiry_date <= date.today() + timedelta(days=reval_doc.alert_days_before):
        return "EXPIRING_SOON"
    return "VALID"


async def create_subject(db: AsyncSession, tenant_id: UUID, data: SubjectCreate) -> SubjectResponse:
    await set_tenant_context(db, tenant_id)

    duplicate = await db.scalar(
        select(RevalidationSubject.id).where(
            RevalidationSubject.tenant_id == tenant_id,
            RevalidationSubject.subject_type == data.subject_type,
            RevalidationSubject.identifier == data.identifier,
        )
    )
    if duplicate is not None:
        _duplicate_subject()

    subject = RevalidationSubject(
        tenant_id=tenant_id,
        subject_type=data.subject_type,
        name=data.name,
        identifier=data.identifier,
        department=data.department,
        email=data.email,
        is_active=True,
    )
    db.add(subject)
    await db.flush()

    compliance_summary = await _build_compliance_summary(db, tenant_id, subject)
    await db.commit()
    return _subject_response(subject, compliance_summary)


async def list_subjects(
    db: AsyncSession,
    tenant_id: UUID,
    subject_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[SubjectResponse]:
    await set_tenant_context(db, tenant_id)

    filters = [RevalidationSubject.tenant_id == tenant_id]
    if subject_type is not None:
        filters.append(RevalidationSubject.subject_type == subject_type)

    subjects = list(
        (
            await db.execute(
                select(RevalidationSubject)
                .where(*filters)
                .order_by(RevalidationSubject.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )

    responses: list[SubjectResponse] = []
    for subject in subjects:
        responses.append(
            _subject_response(subject, await _build_compliance_summary(db, tenant_id, subject))
        )
    return responses


async def get_subject(db: AsyncSession, tenant_id: UUID, subject_id: UUID) -> SubjectResponse | None:
    await set_tenant_context(db, tenant_id)

    subject = await _get_subject(db, tenant_id, subject_id)
    if subject is None:
        return None

    return _subject_response(subject, await _build_compliance_summary(db, tenant_id, subject))


async def create_revalidation_doc(
    db: AsyncSession,
    tenant_id: UUID,
    data: RevalidationDocCreate,
    document_id: UUID | None = None,
) -> RevalidationDocResponse:
    await set_tenant_context(db, tenant_id)

    subject = await _get_subject(db, tenant_id, data.subject_id)
    if subject is None:
        _not_found()

    if document_id is not None:
        document = await db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if document is None:
            _not_found()

    revalidation_doc = RevalidationDocument(
        tenant_id=tenant_id,
        subject_id=data.subject_id,
        document_id=document_id,
        category=data.category,
        display_name=data.display_name,
        has_expiry=data.has_expiry,
        manually_reviewed=False,
        status="PENDING_UPLOAD" if document_id is None else "REVALIDATION_PENDING",
        alert_days_before=data.alert_days_before,
        notes=data.notes,
    )
    db.add(revalidation_doc)
    await db.flush()
    await db.commit()
    return _revalidation_doc_response(revalidation_doc)


async def attach_document(
    db: AsyncSession,
    tenant_id: UUID,
    reval_doc_id: UUID,
    document_id: UUID,
) -> RevalidationDocResponse:
    await set_tenant_context(db, tenant_id)

    revalidation_doc = await _get_revalidation_doc(db, tenant_id, reval_doc_id)
    if revalidation_doc is None:
        _not_found()

    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    if document is None:
        _not_found()

    revalidation_doc.document_id = document_id
    revalidation_doc.status = "REVALIDATION_PENDING"
    revalidation_doc.updated_at = datetime.now(timezone.utc)
    await db.commit()

    from backend.app.tools.document_revalidation.tasks import extract_dates_task

    extract_dates_task.delay(str(reval_doc_id), str(document_id), str(tenant_id))
    return _revalidation_doc_response(revalidation_doc)


async def update_dates_manually(
    db: AsyncSession,
    tenant_id: UUID,
    reval_doc_id: UUID,
    data: ManualDateUpdate,
) -> RevalidationDocResponse:
    await set_tenant_context(db, tenant_id)

    revalidation_doc = await _get_revalidation_doc(db, tenant_id, reval_doc_id)
    if revalidation_doc is None:
        _not_found()

    revalidation_doc.issue_date = data.issue_date
    revalidation_doc.expiry_date = data.expiry_date
    revalidation_doc.has_expiry = data.has_expiry
    revalidation_doc.notes = data.notes
    revalidation_doc.manually_reviewed = True
    revalidation_doc.status = _compute_status(revalidation_doc)
    revalidation_doc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _revalidation_doc_response(revalidation_doc)


async def run_daily_expiry_check(db: AsyncSession, tenant_id: UUID) -> dict:
    await set_tenant_context(db, tenant_id)

    now = datetime.now(timezone.utc)
    documents = list(
        (
            await db.execute(
                select(RevalidationDocument)
                .options(selectinload(RevalidationDocument.subject))
                .where(
                    RevalidationDocument.tenant_id == tenant_id,
                    RevalidationDocument.has_expiry.is_(True),
                    RevalidationDocument.status.not_in(("PENDING_UPLOAD", "NO_EXPIRY")),
                )
            )
        ).scalars()
    )

    updated = 0
    alerts_created = 0
    for revalidation_doc in documents:
        new_status = _compute_status(revalidation_doc)
        if new_status == revalidation_doc.status:
            continue

        revalidation_doc.status = new_status
        revalidation_doc.updated_at = now
        updated += 1

        if new_status not in {"EXPIRING_SOON", "EXPIRED"}:
            continue

        existing_unsent = await db.scalar(
            select(RevalidationAlert.id).where(
                RevalidationAlert.tenant_id == tenant_id,
                RevalidationAlert.revalidation_doc_id == revalidation_doc.id,
                RevalidationAlert.alert_type == new_status,
                RevalidationAlert.sent_at.is_(None),
            )
        )
        if existing_unsent is not None:
            continue

        subject_name = revalidation_doc.subject.name if revalidation_doc.subject is not None else "subject"
        if new_status == "EXPIRING_SOON":
            message = f"{revalidation_doc.display_name} for {subject_name} is expiring soon"
        else:
            message = f"{revalidation_doc.display_name} for {subject_name} has expired"

        db.add(
            RevalidationAlert(
                tenant_id=tenant_id,
                revalidation_doc_id=revalidation_doc.id,
                alert_type=new_status,
                message=message,
            )
        )
        alerts_created += 1

    await db.commit()
    return {"updated": updated, "alerts_created": alerts_created}


async def get_compliance_dashboard(db: AsyncSession, tenant_id: UUID) -> dict:
    await set_tenant_context(db, tenant_id)

    employees_total = (
        await db.execute(
            select(func.count()).select_from(RevalidationSubject).where(
                RevalidationSubject.tenant_id == tenant_id,
                RevalidationSubject.subject_type == "EMPLOYEE",
            )
        )
    ).scalar_one()
    vendors_total = (
        await db.execute(
            select(func.count()).select_from(RevalidationSubject).where(
                RevalidationSubject.tenant_id == tenant_id,
                RevalidationSubject.subject_type == "VENDOR",
            )
        )
    ).scalar_one()

    doc_status_rows = list(
        (
            await db.execute(
                select(RevalidationDocument.status, func.count())
                .where(RevalidationDocument.tenant_id == tenant_id)
                .group_by(RevalidationDocument.status)
            )
        ).all()
    )
    doc_status_counts = {
        str(status_value): int(count)
        for status_value, count in doc_status_rows
    }

    required_by_type = {
        str(subject_type): int(count)
        for subject_type, count in (
            await db.execute(
                select(RevalidationDocCatalog.subject_type, func.count())
                .where(
                    RevalidationDocCatalog.is_required.is_(True),
                    or_(
                        RevalidationDocCatalog.tenant_id.is_(None),
                        RevalidationDocCatalog.tenant_id == tenant_id,
                    ),
                )
                .group_by(RevalidationDocCatalog.subject_type)
            )
        ).all()
    }

    subjects = list(
        (
            await db.execute(
                select(RevalidationSubject.id, RevalidationSubject.subject_type).where(
                    RevalidationSubject.tenant_id == tenant_id,
                )
            )
        ).all()
    )
    uploaded_by_subject = {
        subject_id: int(count)
        for subject_id, count in (
            await db.execute(
                select(RevalidationDocument.subject_id, func.count())
                .where(RevalidationDocument.tenant_id == tenant_id)
                .group_by(RevalidationDocument.subject_id)
            )
        ).all()
    }
    docs_missing = sum(
        max(0, required_by_type.get(str(subject_type), 0) - uploaded_by_subject.get(subject_id, 0))
        for subject_id, subject_type in subjects
    )

    recent_alerts = list(
        (
            await db.execute(
                select(RevalidationAlert)
                .where(RevalidationAlert.tenant_id == tenant_id)
                .order_by(RevalidationAlert.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )

    return {
        "employees_total": int(employees_total),
        "vendors_total": int(vendors_total),
        "docs_valid": doc_status_counts.get("VALID", 0),
        "docs_expiring_soon": doc_status_counts.get("EXPIRING_SOON", 0),
        "docs_expired": doc_status_counts.get("EXPIRED", 0),
        "docs_missing": docs_missing,
        "docs_pending_upload": doc_status_counts.get("PENDING_UPLOAD", 0),
        "recent_alerts": [
            AlertResponse.model_validate(alert).model_dump(mode="json")
            for alert in recent_alerts
        ],
    }


async def list_alerts(
    db: AsyncSession,
    tenant_id: UUID,
    page: int,
    page_size: int,
) -> list[AlertResponse]:
    await set_tenant_context(db, tenant_id)

    alerts = list(
        (
            await db.execute(
                select(RevalidationAlert)
                .where(RevalidationAlert.tenant_id == tenant_id)
                .order_by(RevalidationAlert.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return [AlertResponse.model_validate(alert) for alert in alerts]
