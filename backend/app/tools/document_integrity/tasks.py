"""Celery tasks for Tool B."""

from __future__ import annotations

from uuid import UUID

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.tools.document_integrity.service import DocumentIntegrityService

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


@shared_task(
    name="document_integrity.run_analysis",
    queue="default",
    bind=True,
    max_retries=2,
)
def run_integrity_analysis(self, document_id: str, tenant_id: str):
    """Run Tool B analysis with a synchronous SQLAlchemy session."""
    document_uuid = UUID(str(document_id))
    tenant_uuid = UUID(str(tenant_id))
    service = DocumentIntegrityService()

    with _sync_session_factory() as db_session:
        try:
            _set_tenant_context(db_session, tenant_uuid)
            report = service.run_analysis(
                document_id=str(document_uuid),
                tenant_id=str(tenant_uuid),
                db_session=db_session,
            )
            db_session.commit()
            return report
        except Exception as exc:
            db_session.rollback()
            logger.error(
                "document_integrity_analysis_failed",
                document_id=str(document_uuid),
                tenant_id=str(tenant_uuid),
                error_type=type(exc).__name__,
            )
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            raise
