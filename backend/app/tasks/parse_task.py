"""
LeakSight V1 — Parse Document Celery Task

Source: docs/ARCHITECTURE.md (parse task section)
       docs/PARSING_SPEC.md (failure flagging)
       docs/DECISIONS.md (no silent failures, ADR-006 no outbound internet)

Task chain: parse_document → normalize_document (on success, via immutable signature)

This task:
  1. Converts string IDs back to UUID (Celery JSON serialization)
  2. Creates its own async DB session (not FastAPI get_db)
  3. Sets tenant context for RLS before any DB operation
  4. Parses the document via parser_router
  5. Stores parse result via parse_storage_service
  6. On success: chains normalize_document task
  7. On failure: flags document with error, returns failure status — never re-raises
"""

import asyncio
from pathlib import Path
from uuid import UUID

from celery import shared_task
from sqlalchemy import select, update

from backend.app.core.celery_app import celery_app
from backend.app.core.database import async_session_factory
from backend.app.core.logging import get_logger
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.raw import Document
from backend.app.parsers.parser_router import parse_document as route_to_parser
from backend.app.services.parse_storage_service import store_parse_result

logger = get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _parse_document_async(document_id: UUID, tenant_id: UUID) -> dict:
    """Async implementation of the parse document task.

    Args:
        document_id: UUID of the document to parse.
        tenant_id: UUID of the tenant.

    Returns:
        Status dict with success/failure information.
    """
    async with async_session_factory() as db:
        try:
            # Step 3: Set tenant context BEFORE any DB operation
            await set_tenant_context(db, tenant_id)

            # Step 4: Load document record
            stmt = select(Document).where(Document.id == document_id)
            result = await db.execute(stmt)
            doc = result.scalar_one_or_none()

            if doc is None:
                logger.error(
                    "parse_task_document_not_found",
                    document_id=str(document_id),
                    tenant_id=str(tenant_id),
                )
                return {
                    "status": "failed",
                    "document_id": str(document_id),
                    "error": "DocumentNotFound",
                }

            # Update document status to PARSING
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(parse_status="PARSING")
            )
            await db.flush()

            # Step 5: Parse the document via parser_router
            file_path = Path(doc.file_path)
            parsed_document = route_to_parser(
                file_path=file_path,
                document_id=document_id,
                doc_type=doc.doc_type,
            )

            # Step 6: Store parse result
            raw_parse = await store_parse_result(
                db=db,
                parse_result=parsed_document,
                tenant_id=tenant_id,
            )

            await db.commit()

            logger.info(
                "parse_task_success",
                document_id=str(document_id),
                tenant_id=str(tenant_id),
                status="success",
            )

            return {
                "status": "success",
                "document_id": str(document_id),
                "raw_parse_id": str(raw_parse.id),
            }

        except Exception as exc:
            # Step 8: On any exception — flag the document, return failure
            await db.rollback()

            try:
                # Create a fresh transaction to write the failure flag
                await set_tenant_context(db, tenant_id)
                await db.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(
                        parse_status="FAILED",
                        low_confidence_flag=True,
                    )
                )
                await db.commit()
            except Exception:
                # If we can't even write the failure flag, log it
                logger.error(
                    "parse_task_failure_flag_write_error",
                    document_id=str(document_id),
                    tenant_id=str(tenant_id),
                    error_type=type(exc).__name__,
                )

            logger.error(
                "parse_task_failed",
                document_id=str(document_id),
                tenant_id=str(tenant_id),
                error_type=type(exc).__name__,
            )

            return {
                "status": "failed",
                "document_id": str(document_id),
                "error": type(exc).__name__,
            }


@celery_app.task(name="backend.app.tasks.parse_task.parse_document", bind=True)
def parse_document(self, document_id: str, tenant_id: str) -> dict:
    """Celery task: Parse a document.

    Receives string IDs (JSON serialization), converts to UUID,
    runs async parse pipeline, and chains normalize_document on success.

    Args:
        document_id: String UUID of the document.
        tenant_id: String UUID of the tenant.

    Returns:
        Status dict with success/failure information.
    """
    # Step 1: Convert strings to UUIDs
    doc_uuid = UUID(document_id)
    tenant_uuid = UUID(tenant_id)

    # Step 2-8: Run the async parse pipeline
    result = _run_async(_parse_document_async(doc_uuid, tenant_uuid))

    # Chain: on success, trigger normalize_document
    if result["status"] == "success":
        from backend.app.tasks.normalize_task import normalize_document

        normalize_document.si(
            result["raw_parse_id"],
            tenant_id,
        ).apply_async()

    return result

