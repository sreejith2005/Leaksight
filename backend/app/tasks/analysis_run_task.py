"""
LeakSight V1 — Analysis Run Celery Task

Source: docs/RULES_ENGINE.md (analysis run orchestration, PARTIAL_SUCCESS conditions)
       docs/ARCHITECTURE.md (analysis run task section)
       docs/DATABASE_SCHEMA.md (leakage_records, analysis_runs)
       docs/DECISIONS.md (no silent failures)

This is the most complex task in the system. It:
  1. Loads all canonical invoice records for the run
  2. For each invoice line item: vendor matching → contract resolution →
     FX lookup → unit conversion → rule engine → leakage records
  3. Explicitly determines final status: COMPLETE / PARTIAL_SUCCESS / FAILED
  4. NEVER leaves run status as PROCESSING regardless of outcome

PARTIAL_SUCCESS conditions (explicit, not implied):
  - failed_items: per-item exceptions (does not fail the entire run)
  - has_partial_success: vendor NO_MATCH or needs_manual_review
  - has_pending_fx: PENDING_FX_RATE leakage records created
"""

import asyncio
from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.celery_app import celery_app
from backend.app.core.database import async_session_factory
from backend.app.core.logging import get_logger
from backend.app.core.tenant_context import set_tenant_context
from backend.app.matching.vendor_matcher import MatchMethod, match_vendor
from backend.app.models.derived import AnalysisRun, LeakageRecord
from backend.app.models.invoices import Invoice, InvoiceLineItem
from backend.app.models.raw import Document
from backend.app.models.tenant import TenantSettings
from backend.app.models.vendors import Vendor
from backend.app.rules.rule_engine import evaluate_line_item
from backend.app.services import analysis_run_service, leakage_service
from backend.app.services.notification_service import send_run_notifications

logger = get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _build_partial_summary(
    failed_items: List[str],
    has_pending_fx: bool,
) -> str:
    """Build an error_summary string for PARTIAL_SUCCESS runs.

    Args:
        failed_items: List of item_id strings that encountered errors.
        has_pending_fx: Whether any PENDING_FX_RATE records were created.

    Returns:
        Human-readable summary string.
    """
    parts = []
    if failed_items:
        parts.append(f"{len(failed_items)} line item(s) failed processing")
    if has_pending_fx:
        parts.append("Some leakage records are PENDING_FX_RATE")
    return "; ".join(parts) if parts else "Partial issues detected"


async def _run_analysis_async(run_id: UUID, tenant_id: UUID) -> dict:
    """Async implementation of the analysis run task.

    Args:
        run_id: UUID of the analysis run.
        tenant_id: UUID of the tenant.

    Returns:
        Status dict with final run status and summary.
    """
    async with async_session_factory() as db:
        try:
            # Step 3: Set tenant context BEFORE any DB operation
            await set_tenant_context(db, tenant_id)

            # Step 4: Load the analysis_run record
            stmt = select(AnalysisRun).where(AnalysisRun.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()

            if run is None:
                logger.error(
                    "analysis_run_not_found",
                    run_id=str(run_id),
                    tenant_id=str(tenant_id),
                )
                return {
                    "status": "failed",
                    "run_id": str(run_id),
                    "error": "AnalysisRunNotFound",
                }

            # If already COMPLETE or FAILED, return immediately
            if run.status in ("COMPLETE", "PARTIAL_SUCCESS", "FAILED"):
                logger.info(
                    "analysis_run_already_terminal",
                    run_id=str(run_id),
                    status=run.status,
                )
                return {
                    "status": run.status.lower() if isinstance(run.status, str) else run.status,
                    "run_id": str(run_id),
                    "error": "AlreadyTerminal",
                }

            # Step 5: Transition to PROCESSING
            await analysis_run_service.transition_to_processing(run)
            await db.flush()

            # Step 6: Load tenant_settings
            ts_stmt = select(TenantSettings).where(
                TenantSettings.tenant_id == tenant_id
            )
            ts_result = await db.execute(ts_stmt)
            tenant_settings = ts_result.scalar_one_or_none()

            # Defaults if no tenant_settings record exists
            fuzzy_threshold = 0.85
            if tenant_settings:
                fuzzy_threshold = tenant_settings.fuzzy_threshold

            # Step 8: Load all canonical invoices associated with this run
            # Invoices are linked to documents which are linked to this run
            doc_stmt = select(Document.id).where(
                Document.run_id == run_id,
                Document.tenant_id == tenant_id,
            )
            doc_result = await db.execute(doc_stmt)
            document_ids = [row[0] for row in doc_result.fetchall()]

            inv_stmt = select(Invoice).where(
                Invoice.source_document_id.in_(document_ids),
                Invoice.tenant_id == tenant_id,
            )
            inv_result = await db.execute(inv_stmt)
            invoices = list(inv_result.scalars().all())

            # Step 9: Initialize tracking variables
            has_partial_success = False
            has_pending_fx = False
            failed_items: List[str] = []
            checked_invoice_ids: Set[UUID] = set()

            # Process each invoice and its line items
            for invoice in invoices:
                # Load vendor for name
                vendor_stmt = select(Vendor).where(Vendor.id == invoice.vendor_id)
                vendor_result = await db.execute(vendor_stmt)
                vendor = vendor_result.scalar_one_or_none()
                vendor_name = vendor.normalized_name if vendor else "Unknown"

                # Run vendor matching for this invoice's vendor
                vendor_match_result = await match_vendor(
                    raw_name=vendor_name,
                    gst_id=vendor.gst_id if vendor else None,
                    tenant_id=tenant_id,
                    db=db,
                )

                # Check vendor match quality
                if (
                    vendor_match_result.match_method == MatchMethod.NO_MATCH
                    or vendor_match_result.needs_manual_review
                ):
                    logger.info(
                        "analysis_vendor_match_issue",
                        run_id=str(run_id),
                        vendor_id=str(invoice.vendor_id),
                        match_method=vendor_match_result.match_method.value,
                    )
                    has_partial_success = True
                    # Continue to next invoice — don't attempt rules for
                    # unmatched vendors
                    await analysis_run_service.increment_processed(run, 1)
                    await db.flush()
                    continue

                # Load line items for this invoice
                li_stmt = select(InvoiceLineItem).where(
                    InvoiceLineItem.invoice_id == invoice.id,
                    InvoiceLineItem.tenant_id == tenant_id,
                )
                li_result = await db.execute(li_stmt)
                line_items = list(li_result.scalars().all())

                for line_item in line_items:
                    try:
                        # Run all three rules via rule_engine
                        rule_results = await evaluate_line_item(
                            invoice_line_item=line_item,
                            invoice=invoice,
                            vendor_name=vendor_name,
                            vendor_match_confidence=vendor_match_result.confidence,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            db=db,
                            checked_invoice_ids=checked_invoice_ids,
                        )

                        # Create leakage records for each result
                        for rr in rule_results:
                            try:
                                record = await leakage_service.create_leakage_record(
                                    rule_result=rr,
                                    tenant_id=tenant_id,
                                    run_id=run_id,
                                    db=db,
                                )
                                # Check for PENDING_FX_RATE
                                if rr.status == "PENDING_FX_RATE":
                                    has_pending_fx = True
                                    has_partial_success = True
                            except Exception as lr_exc:
                                logger.error(
                                    "analysis_leakage_record_creation_failed",
                                    run_id=str(run_id),
                                    error_type=type(lr_exc).__name__,
                                )
                                failed_items.append(str(line_item.id))

                    except Exception as item_exc:
                        # Per-item exception: log, track, continue
                        logger.error(
                            "analysis_line_item_failed",
                            run_id=str(run_id),
                            error_type=type(item_exc).__name__,
                        )
                        failed_items.append(str(line_item.id))
                        # Continue processing remaining items — do NOT abort

                # Increment processed document count after each invoice
                await analysis_run_service.increment_processed(run, 1)
                await db.flush()

            # ── Determine final run status ──────────────────────────────
            # Explicit conditionals, not implied
            if failed_items or has_partial_success or has_pending_fx:
                final_status = "PARTIAL_SUCCESS"
                error_summary = _build_partial_summary(failed_items, has_pending_fx)
            else:
                final_status = "COMPLETE"
                error_summary = None

            # Complete the run via analysis_run_service
            if final_status == "PARTIAL_SUCCESS":
                await analysis_run_service.complete_run(
                    run=run,
                    tenant_id=tenant_id,
                    db=db,
                    has_partial_issues=True,
                )
                if error_summary:
                    run.error_summary = error_summary
            else:
                await analysis_run_service.complete_run(
                    run=run,
                    tenant_id=tenant_id,
                    db=db,
                    has_partial_issues=False,
                )

            await db.commit()

            # ── Send notifications (Phase 8) ───────────────────────────
            # Notification failure must NEVER affect run status.
            # The run is already committed at this point.
            try:
                await send_run_notifications(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    final_status=final_status,
                    db=db,
                )
                await db.commit()
            except Exception as notif_exc:
                await db.rollback()
                logger.error(
                    "notification_send_failed",
                    run_id=str(run_id),
                    tenant_id=str(tenant_id),
                    error_type=type(notif_exc).__name__,
                    component="notification_service",
                )

            logger.info(
                "analysis_run_complete",
                run_id=str(run_id),
                tenant_id=str(tenant_id),
                status=run.status,
            )

            return {
                "status": run.status.lower() if isinstance(run.status, str) else run.status,
                "run_id": str(run_id),
                "leakage_record_count": run.leakage_record_count,
                "total_leakage_found": float(run.total_leakage_found or 0),
                "error_summary": run.error_summary,
            }

        except Exception as exc:
            # Unhandled exception at the run level
            await db.rollback()

            error_summary = f"{type(exc).__name__}: {str(exc)}"
            # Never include document contents or financial data
            # Truncate to prevent overly long error messages
            if len(error_summary) > 500:
                error_summary = error_summary[:500]

            try:
                await set_tenant_context(db, tenant_id)
                # Re-fetch the run to update it
                refetch_stmt = select(AnalysisRun).where(AnalysisRun.id == run_id)
                refetch_result = await db.execute(refetch_stmt)
                run = refetch_result.scalar_one_or_none()

                if run and run.status == "PROCESSING":
                    await analysis_run_service.fail_run(run, error_summary)
                    await db.commit()
                elif run and run.status == "QUEUED":
                    # If it failed before even transitioning to PROCESSING
                    run.status = "FAILED"
                    run.error_summary = error_summary
                    await db.commit()
            except Exception:
                logger.error(
                    "analysis_run_status_update_failed",
                    run_id=str(run_id),
                    tenant_id=str(tenant_id),
                    error_type=type(exc).__name__,
                )

            logger.error(
                "analysis_run_failed",
                run_id=str(run_id),
                tenant_id=str(tenant_id),
                error_type=type(exc).__name__,
            )

            return {
                "status": "failed",
                "run_id": str(run_id),
                "error": type(exc).__name__,
                "error_summary": error_summary,
            }


@celery_app.task(name="backend.app.tasks.analysis_run_task.run_analysis")
def run_analysis(run_id: str, tenant_id: str) -> dict:
    """Celery task: Run a full analysis pipeline.

    Processes all canonical invoice records for a run, runs vendor matching,
    contract resolution, all three rules, and creates leakage records.

    Final status is NEVER left as PROCESSING regardless of outcome.

    Args:
        run_id: String UUID of the analysis run.
        tenant_id: String UUID of the tenant.

    Returns:
        Status dict with final run status and summary.
    """
    # Step 1: Convert strings to UUIDs
    run_uuid = UUID(run_id)
    tenant_uuid = UUID(tenant_id)

    # Steps 2-end: Run the async analysis pipeline
    return _run_async(_run_analysis_async(run_uuid, tenant_uuid))

