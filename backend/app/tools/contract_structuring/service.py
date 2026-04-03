"""Service layer for Tool A contract structuring runs."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tools.contract_structuring.models import (
    ContractStructuringRun,
    ContractStructuringRunDocument,
)
from backend.app.tools.contract_structuring.tasks import (
    _update_structuring_run_status_async,
    structure_single_contract,
)


async def create_structuring_run(
    document_ids: list[UUID],
    run_label: str,
    tenant_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> UUID:
    """Create a structuring run and queue one task per document."""
    run = ContractStructuringRun(
        tenant_id=tenant_id,
        run_label=run_label,
        status="PENDING",
        total_documents=len(document_ids),
        processed_documents=0,
        total_line_items_found=0,
        total_clauses_found=0,
        created_by_user_id=user_id,
    )
    db.add(run)
    await db.flush()

    run_docs: list[ContractStructuringRunDocument] = []
    for doc_id in document_ids:
        run_doc = ContractStructuringRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=doc_id,
            task_status="PENDING",
        )
        db.add(run_doc)
        run_docs.append(run_doc)

    await db.flush()

    run.started_at = datetime.now(timezone.utc)
    await db.commit()

    dispatch_failed = False
    for run_doc in run_docs:
        try:
            structure_single_contract.delay(
                str(run_doc.document_id),
                str(run_doc.id),
                str(tenant_id),
            )
        except Exception as exc:
            dispatch_failed = True
            run_doc.task_status = "FAILED"
            run_doc.error_message = (
                f"Task dispatch failed: {type(exc).__name__}: {exc}"
            )
            run_doc.processing_time_seconds = 0.0

    if dispatch_failed:
        await db.commit()
        await _update_structuring_run_status_async(run.id, tenant_id)

    return run.id
