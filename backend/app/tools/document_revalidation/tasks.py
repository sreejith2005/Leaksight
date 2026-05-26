"""Celery tasks for Tool C document revalidation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import joinedload, Session, sessionmaker

from backend.app.core.celery_app import celery_app
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.models.raw import RawParse
from backend.app.models.tenant import Tenant
from backend.app.tools.document_revalidation.date_extractor import extract_dates_from_parse
from backend.app.tools.document_revalidation.models import (
    RevalidationAlert,
    RevalidationDocument,
)
from backend.app.tools.document_revalidation.service import _compute_status

logger = get_logger(__name__)

_sync_engine = create_engine(
    get_settings().database_url_sync,
    future=True,
    pool_pre_ping=True,
)
_sync_session_factory = sessionmaker(
    bind=_sync_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def _set_tenant_context(db_session: Session, tenant_id: UUID) -> None:
    safe_tenant_id = str(UUID(str(tenant_id)))
    db_session.execute(text(f"SET LOCAL app.current_tenant_id = '{safe_tenant_id}'"))


def _run_daily_expiry_check_sync(db_session: Session, tenant_id: UUID) -> dict:
    _set_tenant_context(db_session, tenant_id)
    now = datetime.now(timezone.utc)

    documents = list(
        db_session.execute(
            select(RevalidationDocument)
            .options(joinedload(RevalidationDocument.subject))
            .where(
                RevalidationDocument.tenant_id == tenant_id,
                RevalidationDocument.has_expiry.is_(True),
                RevalidationDocument.status.not_in(("PENDING_UPLOAD", "NO_EXPIRY")),
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

        existing_unsent = db_session.execute(
            select(RevalidationAlert.id).where(
                RevalidationAlert.tenant_id == tenant_id,
                RevalidationAlert.revalidation_doc_id == revalidation_doc.id,
                RevalidationAlert.alert_type == new_status,
                RevalidationAlert.sent_at.is_(None),
            )
        ).scalar_one_or_none()
        if existing_unsent is not None:
            continue

        subject_name = revalidation_doc.subject.name if revalidation_doc.subject is not None else "subject"
        if new_status == "EXPIRING_SOON":
            message = f"{revalidation_doc.display_name} for {subject_name} is expiring soon"
        else:
            message = f"{revalidation_doc.display_name} for {subject_name} has expired"

        db_session.add(
            RevalidationAlert(
                tenant_id=tenant_id,
                revalidation_doc_id=revalidation_doc.id,
                alert_type=new_status,
                message=message,
            )
        )
        alerts_created += 1

    db_session.commit()
    return {"updated": updated, "alerts_created": alerts_created}


@celery_app.task(name="revalidation.extract_dates", queue="revalidation")
def extract_dates_task(reval_doc_id: str, document_id: str, tenant_id: str) -> dict:
    revalidation_doc_uuid = UUID(str(reval_doc_id))
    document_uuid = UUID(str(document_id))
    tenant_uuid = UUID(str(tenant_id))

    with _sync_session_factory() as db_session:
        try:
            _set_tenant_context(db_session, tenant_uuid)

            revalidation_doc = db_session.execute(
                select(RevalidationDocument).where(
                    RevalidationDocument.id == revalidation_doc_uuid,
                    RevalidationDocument.tenant_id == tenant_uuid,
                )
            ).scalar_one_or_none()
            if revalidation_doc is None:
                logger.error(
                    "revalidation_extract_dates_missing_doc",
                    reval_doc_id=str(revalidation_doc_uuid),
                    document_id=str(document_uuid),
                    tenant_id=str(tenant_uuid),
                )
                return {"status": "missing_revalidation_doc"}

            raw_parse = db_session.execute(
                select(RawParse)
                .where(
                    RawParse.document_id == document_uuid,
                    RawParse.tenant_id == tenant_uuid,
                )
                .order_by(RawParse.raw_version.desc(), RawParse.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            extracted = (
                extract_dates_from_parse(raw_parse.structured_output_jsonb)
                if raw_parse is not None
                else {"issue_date": None, "expiry_date": None, "confidence": 0.0}
            )
            revalidation_doc.issue_date = extracted["issue_date"]
            revalidation_doc.expiry_date = extracted["expiry_date"]
            revalidation_doc.extraction_confidence = extracted["confidence"]
            revalidation_doc.last_checked_at = datetime.now(timezone.utc)
            revalidation_doc.status = _compute_status(revalidation_doc)
            revalidation_doc.updated_at = datetime.now(timezone.utc)
            db_session.commit()

            logger.info(
                "revalidation_extract_dates_completed",
                reval_doc_id=str(revalidation_doc_uuid),
                document_id=str(document_uuid),
                tenant_id=str(tenant_uuid),
                status=revalidation_doc.status,
                confidence=extracted["confidence"],
            )
            return {
                "status": revalidation_doc.status,
                "confidence": extracted["confidence"],
            }
        except Exception as exc:
            db_session.rollback()
            try:
                _set_tenant_context(db_session, tenant_uuid)
                revalidation_doc = db_session.execute(
                    select(RevalidationDocument).where(
                        RevalidationDocument.id == revalidation_doc_uuid,
                        RevalidationDocument.tenant_id == tenant_uuid,
                    )
                ).scalar_one_or_none()
                if revalidation_doc is not None:
                    revalidation_doc.status = "REVALIDATION_PENDING"
                    revalidation_doc.updated_at = datetime.now(timezone.utc)
                    db_session.commit()
            except Exception:
                db_session.rollback()

            logger.error(
                "revalidation_extract_dates_failed",
                reval_doc_id=str(revalidation_doc_uuid),
                document_id=str(document_uuid),
                tenant_id=str(tenant_uuid),
                error_type=type(exc).__name__,
            )
            return {"status": "REVALIDATION_PENDING"}


@celery_app.task(name="revalidation.daily_expiry_check", queue="revalidation")
def daily_expiry_check_task(tenant_id: str) -> dict:
    tenant_uuid = UUID(str(tenant_id))
    with _sync_session_factory() as db_session:
        try:
            result = _run_daily_expiry_check_sync(db_session, tenant_uuid)
            logger.info(
                "revalidation_daily_expiry_check_completed",
                tenant_id=str(tenant_uuid),
                updated=result["updated"],
                alerts_created=result["alerts_created"],
            )
            return result
        except Exception as exc:
            db_session.rollback()
            logger.error(
                "revalidation_daily_expiry_check_failed",
                tenant_id=str(tenant_uuid),
                error_type=type(exc).__name__,
            )
            return {"updated": 0, "alerts_created": 0}


@celery_app.task(name="revalidation.bulk_check_all", queue="revalidation")
def bulk_expiry_check_all_tenants_task() -> dict:
    queued = 0
    with _sync_session_factory() as db_session:
        tenant_ids = list(
            db_session.execute(
                select(Tenant.id).where(Tenant.is_active.is_(True))
            ).scalars()
        )

    for tenant_id in tenant_ids:
        daily_expiry_check_task.delay(str(tenant_id))
        queued += 1

    logger.info(
        "revalidation_bulk_expiry_check_queued",
        tenants=queued,
    )
    return {"tenants_queued": queued}
