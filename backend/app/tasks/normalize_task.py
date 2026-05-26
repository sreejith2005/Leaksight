"""
LeakSight V1 — Normalize Document Celery Task

Source: docs/ARCHITECTURE.md (normalization task section)
       docs/PARSING_SPEC.md (normalization pipeline)
       docs/DECISIONS.md (no silent failures)

This task:
  1. Converts string IDs back to UUID
  2. Creates its own async DB session
  3. Sets tenant context for RLS before any DB operation
  4. Loads raw_parses record
  5. Calls normalization_service.normalize_parse_result()
  6. On failure: writes error flag to raw_parses, returns failure — never re-raises

This task does NOT chain to another task. The analysis_run_task is triggered
explicitly from the ingest endpoint trigger-run call. Users decide when to
trigger analysis after all documents are uploaded and normalized.
"""

import asyncio
import traceback
from uuid import UUID

from sqlalchemy import select, update

from backend.app.core.celery_app import celery_app
from backend.app.core.celery_async import run_async as _run_async
from backend.app.core.database import async_session_factory
from backend.app.core.logging import get_logger
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.raw import RawParse
from backend.app.parsers.base_parser import ParseResult, DocType, DocumentHeader
from backend.app.services.normalization_service import (
    normalize_parse_result as normalize_service_fn,
)

logger = get_logger(__name__)


def _reconstruct_parse_result(raw_parse: RawParse) -> ParseResult:
    """Reconstruct a ParseResult from a stored raw_parses row.

    The raw_parses table stores structured_output_jsonb which contains
    the serialized ParseResult data. This function reconstructs it
    for use by the normalization service.

    Args:
        raw_parse: The RawParse ORM model instance.

    Returns:
        A ParseResult object ready for normalization.
    """
    data = raw_parse.structured_output_jsonb

    header_data = data.get("header", {})
    header = DocumentHeader(
        vendor_name=header_data.get("vendor_name"),
        vendor_gst_id=header_data.get("vendor_gst_id"),
        document_number=header_data.get("document_number"),
        document_date=header_data.get("document_date"),
        total_amount=header_data.get("total_amount"),
        currency=header_data.get("currency", "INR"),
        valid_from=header_data.get("valid_from"),
        valid_to=header_data.get("valid_to"),
        version_number=header_data.get("version_number"),
    )

    # Reconstruct line items from JSONB
    from backend.app.parsers.base_parser import LineItem
    line_items = []
    for li_data in data.get("line_items", []):
        line_items.append(LineItem(
            line_number=li_data.get("line_number", 0),
            item_desc=li_data.get("item_desc", ""),
            quantity=li_data.get("quantity"),
            unit=li_data.get("unit"),
            unit_price=li_data.get("unit_price"),
            line_total=li_data.get("line_total"),
            ordered_qty=li_data.get("ordered_qty"),
            received_qty=li_data.get("received_qty"),
            field_confidences=li_data.get("field_confidences", {}),
            extraction_notes=li_data.get("extraction_notes"),
        ))

    # Reconstruct failure flags
    from backend.app.parsers.base_parser import FailureFlag
    failure_flags = []
    for ff_data in raw_parse.failure_flags or []:
        failure_flags.append(FailureFlag(
            severity=ff_data.get("severity", "WARNING"),
            code=ff_data.get("code", "UNKNOWN"),
            message=ff_data.get("message", ""),
            page_number=ff_data.get("page_number"),
            field_name=ff_data.get("field_name"),
        ))

    doc_type_str = data.get("doc_type", "INVOICE")
    try:
        doc_type = DocType(doc_type_str)
    except ValueError:
        doc_type = DocType.INVOICE

    return ParseResult(
        document_id=raw_parse.document_id,
        doc_type=doc_type,
        parser_used=raw_parse.parser_used,
        parser_version=raw_parse.parser_version,
        parse_confidence=raw_parse.parse_confidence,
        header=header,
        line_items=line_items,
        failure_flags=failure_flags,
        raw_extracted_data=data.get("raw_extracted_data") or {},
    )


async def _normalize_document_async(raw_parse_id: UUID, tenant_id: UUID) -> dict:
    """Async implementation of the normalization task.

    Args:
        raw_parse_id: UUID of the raw_parses record.
        tenant_id: UUID of the tenant.

    Returns:
        Status dict with success/failure information.
    """
    async with async_session_factory() as db:
        try:
            # Step 3: Set tenant context BEFORE any DB operation
            await set_tenant_context(db, tenant_id)

            # Step 4: Load raw_parses record
            stmt = select(RawParse).where(RawParse.id == raw_parse_id)
            result = await db.execute(stmt)
            raw_parse = result.scalar_one_or_none()

            if raw_parse is None:
                logger.error(
                    "normalize_task_raw_parse_not_found",
                    raw_parse_id=str(raw_parse_id),
                    tenant_id=str(tenant_id),
                )
                return {
                    "status": "failed",
                    "raw_parse_id": str(raw_parse_id),
                    "error": "RawParseNotFound",
                }

            # Reconstruct ParseResult from stored JSONB
            parse_result = _reconstruct_parse_result(raw_parse)

            # Step 5: Call normalization service
            norm_result = await normalize_service_fn(
                db=db,
                parse_result=parse_result,
                tenant_id=tenant_id,
            )

            await db.commit()

            # Build summary dict
            summary = {
                "vendor_id": str(norm_result.vendor_id) if norm_result.vendor_id else None,
                "vendor_match_method": norm_result.vendor_match_method,
                "invoice_id": str(norm_result.invoice_id) if norm_result.invoice_id else None,
                "line_items_created": norm_result.line_items_created,
                "skipped": norm_result.skipped,
                "skip_reason": norm_result.skip_reason,
            }

            logger.info(
                "normalize_task_success",
                raw_parse_id=str(raw_parse_id),
                tenant_id=str(tenant_id),
                status="success",
            )

            return {
                "status": "success",
                "raw_parse_id": str(raw_parse_id),
                "canonical_records_created": summary,
            }

        except Exception as exc:
            # Step 7: On any exception — write error flag, return failure
            await db.rollback()

            try:
                await set_tenant_context(db, tenant_id)
                # Write error flag to raw_parses failure_flags
                current_flags = []
                try:
                    refetch = await db.execute(
                        select(RawParse.failure_flags).where(
                            RawParse.id == raw_parse_id
                        )
                    )
                    current_flags = refetch.scalar_one_or_none() or []
                except Exception:
                    pass

                error_flag = {
                    "severity": "ERROR",
                    "code": "NORMALIZATION_FAILED",
                    "message": f"Normalization failed: {type(exc).__name__}",
                    "page_number": None,
                    "field_name": None,
                }
                updated_flags = current_flags + [error_flag]

                await db.execute(
                    update(RawParse)
                    .where(RawParse.id == raw_parse_id)
                    .values(failure_flags=updated_flags)
                )
                await db.commit()
            except Exception:
                logger.error(
                    "normalize_task_error_flag_write_failed",
                    raw_parse_id=str(raw_parse_id),
                    tenant_id=str(tenant_id),
                    error_type=type(exc).__name__,
                )

            logger.error(
                "normalize_task_failed",
                raw_parse_id=str(raw_parse_id),
                tenant_id=str(tenant_id),
                error_type=type(exc).__name__,
                traceback=traceback.format_exc(),
            )

            return {
                "status": "failed",
                "raw_parse_id": str(raw_parse_id),
                "error": type(exc).__name__,
            }


@celery_app.task(name="backend.app.tasks.normalize_task.normalize_document")
def normalize_document(raw_parse_id: str, tenant_id: str) -> dict:
    """Celery task: Normalize a parsed document.

    Receives string IDs (JSON serialization), converts to UUID,
    runs async normalization pipeline.

    This task does NOT chain to another task. Analysis is triggered
    explicitly by the user via the trigger-run endpoint.

    Args:
        raw_parse_id: String UUID of the raw_parses record.
        tenant_id: String UUID of the tenant.

    Returns:
        Status dict with success/failure information.
    """
    # Step 1: Convert strings to UUIDs
    rp_uuid = UUID(raw_parse_id)
    tenant_uuid = UUID(tenant_id)

    # Steps 2-7: Run the async normalization pipeline
    return _run_async(_normalize_document_async(rp_uuid, tenant_uuid))

