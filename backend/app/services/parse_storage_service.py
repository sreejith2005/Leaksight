"""
LeakSight V1 — Parse Storage Service

Source: docs/PARSING_SPEC.md (Sections 7 & 8)
       docs/DATABASE_SCHEMA.md (Sections 2.1, 2.2)
       docs/ARCHITECTURE.md (immutability rules)

Responsibilities:
  1. Store parse results as raw_parses rows (append-only)
  2. Manage raw_version numbering (never overwrite)
  3. Confidence threshold enforcement (flag low-confidence documents)
  4. Mark document parse_status based on result
  5. Impact analysis_run status for low-confidence results
"""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.derived import AnalysisRun
from backend.app.models.raw import Document, RawParse
from backend.app.models.tenant import TenantSettings
from backend.app.parsers.base_parser import ParseResult

logger = get_logger(__name__)

# Default threshold if tenant_settings not found
_DEFAULT_MANUAL_REVIEW_THRESHOLD = 0.70


async def get_tenant_threshold(
    db: AsyncSession,
    tenant_id: UUID,
) -> float:
    """Get the manual review threshold for a tenant.

    Returns the tenant's configured threshold, or the default (0.70).
    """
    result = await db.execute(
        select(TenantSettings.manual_review_threshold).where(
            TenantSettings.tenant_id == tenant_id,
        )
    )
    threshold = result.scalar_one_or_none()
    return threshold if threshold is not None else _DEFAULT_MANUAL_REVIEW_THRESHOLD


async def get_next_raw_version(
    db: AsyncSession,
    document_id: UUID,
) -> int:
    """Get the next raw_version number for a document.

    Returns 1 for first parse, or previous max + 1 for re-parse.
    Per PARSING_SPEC.md §7.
    """
    result = await db.execute(
        select(func.max(RawParse.raw_version)).where(
            RawParse.document_id == document_id,
        )
    )
    max_version = result.scalar_one_or_none()
    return 1 if max_version is None else max_version + 1


async def store_parse_result(
    db: AsyncSession,
    parse_result: ParseResult,
    tenant_id: UUID,
    run_id: UUID | None = None,
) -> RawParse:
    """Store a parse result and enforce confidence thresholds.

    Per PARSING_SPEC.md §7 and §8:
    1. Always create a new raw_parses row (never update existing)
    2. Check confidence against tenant threshold
    3. Flag document if below threshold
    4. Update document parse_status
    5. Impact run status if applicable

    Args:
        db: Async database session (with tenant context set).
        parse_result: ParseResult from a parser.
        tenant_id: UUID of the tenant.
        run_id: UUID of the analysis run (if applicable).

    Returns:
        The created RawParse row.
    """
    # ── Get next version number ───────────────────────────────
    raw_version = await get_next_raw_version(db, parse_result.document_id)

    # ── Serialize parse result to JSONB ───────────────────────
    structured_output = parse_result.to_jsonb()
    failure_flags_jsonb = [
        {
            "severity": f.severity,
            "code": f.code,
            "message": f.message,
            "page_number": f.page_number,
            "field_name": f.field_name,
        }
        for f in parse_result.failure_flags
    ]

    # ── Create raw_parses row (append-only) ───────────────────
    raw_parse = RawParse(
        document_id=parse_result.document_id,
        tenant_id=tenant_id,
        raw_version=raw_version,
        parser_used=parse_result.parser_used,
        parser_version=parse_result.parser_version,
        structured_output_jsonb=structured_output,
        parse_confidence=parse_result.parse_confidence,
        failure_flags=failure_flags_jsonb,
    )
    db.add(raw_parse)

    # ── Update document parse_status ──────────────────────────
    if parse_result.parse_confidence == 0.0:
        # Total failure
        new_status = "FAILED"
    else:
        new_status = "PARSED"

    await db.execute(
        update(Document)
        .where(Document.id == parse_result.document_id)
        .values(parse_status=new_status)
    )

    # ── Confidence threshold enforcement ──────────────────────
    # Per PARSING_SPEC.md §8.2
    threshold = await get_tenant_threshold(db, tenant_id)

    if parse_result.parse_confidence < threshold:
        # Flag the document
        await flag_document_low_confidence(db, parse_result.document_id)

        # Mark run for PARTIAL_SUCCESS if applicable
        if run_id is not None:
            await mark_run_partial_success(db, run_id)

        logger.info(
            "low_confidence_parse",
            document_id=str(parse_result.document_id),
            confidence=parse_result.parse_confidence,
            threshold=threshold,
        )

    await db.flush()

    logger.info(
        "parse_result_stored",
        document_id=str(parse_result.document_id),
        raw_version=raw_version,
        parse_confidence=parse_result.parse_confidence,
        parser_used=parse_result.parser_used,
    )

    return raw_parse


async def flag_document_low_confidence(
    db: AsyncSession,
    document_id: UUID,
) -> None:
    """Flag a document as having low parse confidence.

    Sets documents.low_confidence_flag = TRUE.
    Per PARSING_SPEC.md §8.2.
    """
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(low_confidence_flag=True)
    )


async def mark_run_partial_success(
    db: AsyncSession,
    run_id: UUID,
) -> None:
    """Mark an analysis run for PARTIAL_SUCCESS due to low-confidence documents.

    Per PARSING_SPEC.md §8.4:
    If any document has confidence below threshold, run transitions to
    PARTIAL_SUCCESS instead of COMPLETE.

    Only transitions from PROCESSING status to avoid invalid transitions.
    """
    result = await db.execute(
        select(AnalysisRun.status).where(AnalysisRun.id == run_id)
    )
    current_status = result.scalar_one_or_none()

    if current_status == "PROCESSING":
        await db.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(status="PARTIAL_SUCCESS")
        )
