"""Run Tool A structuring flow from CLI using service layer.

Usage:
    .venv\\Scripts\\python.exe _run_tool_a_structuring.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from backend.app.core.database import async_session_factory
from backend.app.core.tenant_context import set_tenant_context
from backend.app.models.raw import Document
from backend.app.models.tenant import User
from backend.app.tools.contract_structuring.models import (
    ContractStructuringRun,
    ContractStructuringRunDocument,
    ExtractedClause,
    ExtractedLineItem,
)
from backend.app.tools.contract_structuring.service import create_structuring_run

TARGET_TENANT_ID = UUID("edeb6d4c-6b06-4909-9bf2-f97ef0a149c8")


async def _pick_context_ids() -> tuple[UUID, UUID, UUID]:
    async with async_session_factory() as db:
        user = await db.scalar(
            select(User)
            .where(User.tenant_id == TARGET_TENANT_ID)
            .limit(1)
        )
        if user is None:
            raise RuntimeError("No users found for tenant edeb6d4c-6b06-4909-9bf2-f97ef0a149c8")

        tenant_id = user.tenant_id
        await set_tenant_context(db, tenant_id)

        doc = await db.scalar(
            select(Document)
            .where(Document.tenant_id == tenant_id, Document.doc_type == "CONTRACT")
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        if doc is None:
            doc = await db.scalar(
                select(Document)
                .where(Document.tenant_id == tenant_id)
                .order_by(Document.created_at.desc())
                .limit(1)
            )
        if doc is None:
            raise RuntimeError("No documents found for selected tenant")

        return tenant_id, user.id, doc.id


async def _create_and_poll_run(tenant_id: UUID, user_id: UUID, document_id: UUID) -> None:
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)
        run_id = await create_structuring_run(
            document_ids=[document_id],
            run_label="CLI Tool A run",
            tenant_id=tenant_id,
            user_id=user_id,
            db=db,
        )

    print(f"Created structuring run: {run_id}")

    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
    terminal_statuses = {"COMPLETE", "PARTIAL_SUCCESS", "FAILED"}
    last_status = None

    while datetime.now(timezone.utc) < deadline:
        await asyncio.sleep(3)
        async with async_session_factory() as db:
            await set_tenant_context(db, tenant_id)
            run = await db.scalar(
                select(ContractStructuringRun).where(
                    ContractStructuringRun.id == run_id,
                    ContractStructuringRun.tenant_id == tenant_id,
                )
            )
            if run is None:
                raise RuntimeError("Run not found during polling")

            if run.status != last_status:
                print(
                    f"Run status={run.status} processed={run.processed_documents}/{run.total_documents} "
                    f"line_items={run.total_line_items_found} clauses={run.total_clauses_found}"
                )
                last_status = run.status

            if run.status in terminal_statuses:
                run_docs = list(
                    (
                        await db.execute(
                            select(ContractStructuringRunDocument).where(
                                ContractStructuringRunDocument.run_id == run_id,
                                ContractStructuringRunDocument.tenant_id == tenant_id,
                            )
                        )
                    ).scalars()
                )
                item_count = (
                    await db.execute(
                        select(ExtractedLineItem).where(
                            ExtractedLineItem.run_id == run_id,
                            ExtractedLineItem.tenant_id == tenant_id,
                        )
                    )
                ).scalars().all()
                clause_count = (
                    await db.execute(
                        select(ExtractedClause).where(
                            ExtractedClause.run_id == run_id,
                            ExtractedClause.tenant_id == tenant_id,
                        )
                    )
                ).scalars().all()

                print("Final run summary:")
                print(f"  run_status={run.status}")
                print(f"  line_items_extracted={len(item_count)}")
                print(f"  clauses_extracted={len(clause_count)}")
                print("Run documents:")
                for rd in run_docs:
                    print(
                        f"  document={rd.document_id} status={rd.task_status} error={rd.error_message}"
                    )
                errors = [rd.error_message for rd in run_docs if rd.error_message]
                if errors:
                    print("Error messages:")
                    for err in errors:
                        print(f"  {err}")
                else:
                    print("Error messages: none")
                return

    raise TimeoutError("Structuring run polling timed out after 5 minutes")


async def main() -> int:
    tenant_id, user_id, document_id = await _pick_context_ids()
    print(f"Using tenant={tenant_id} user={user_id} document={document_id}")
    try:
        await _create_and_poll_run(tenant_id, user_id, document_id)
        return 0
    except Exception as exc:
        print(f"Run failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
