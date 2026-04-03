import uuid
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from backend.app.tools.contract_structuring.models import (
    ContractStructuringRun,
    ContractStructuringRunDocument,
)
from backend.app.tools.contract_structuring.service import create_structuring_run


class _DummyDb:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                setattr(obj, "id", uuid.uuid4())

    async def commit(self) -> None:
        self._events.append("commit")


@pytest.mark.asyncio
async def test_create_structuring_run_commits_before_dispatch():
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_ids = [uuid.uuid4(), uuid.uuid4()]
    events: list[str] = []
    db = _DummyDb(events)

    def _record_delay(document_id: str, run_document_id: str, tenant_id_arg: str) -> None:
        events.append(f"delay:{document_id}:{run_document_id}:{tenant_id_arg}")

    with patch(
        "backend.app.tools.contract_structuring.service.structure_single_contract.delay",
        side_effect=_record_delay,
    ):
        run_id = await create_structuring_run(
            document_ids=document_ids,
            run_label="demo",
            tenant_id=tenant_id,
            user_id=user_id,
            db=db,
        )

    assert isinstance(run_id, uuid.UUID)
    assert events[0] == "commit"
    assert len([event for event in events if event.startswith("delay:")]) == 2


@pytest.mark.asyncio
async def test_create_structuring_run_marks_dispatch_failures_failed():
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    failing_document_id = uuid.uuid4()
    passing_document_id = uuid.uuid4()
    events: list[str] = []
    db = _DummyDb(events)

    def _delay(document_id: str, run_document_id: str, tenant_id_arg: str) -> None:
        events.append(f"delay:{document_id}:{run_document_id}:{tenant_id_arg}")
        if document_id == str(failing_document_id):
            raise RuntimeError("broker unavailable")

    with patch(
        "backend.app.tools.contract_structuring.service.structure_single_contract.delay",
        side_effect=_delay,
    ), patch(
        "backend.app.tools.contract_structuring.service._update_structuring_run_status_async",
        new_callable=AsyncMock,
    ) as mock_status_update:
        await create_structuring_run(
            document_ids=[failing_document_id, passing_document_id],
            run_label="demo",
            tenant_id=tenant_id,
            user_id=user_id,
            db=db,
        )

    run_docs = [obj for obj in db.added if isinstance(obj, ContractStructuringRunDocument)]
    failed_doc = next(doc for doc in run_docs if doc.document_id == failing_document_id)
    passed_doc = next(doc for doc in run_docs if doc.document_id == passing_document_id)
    run = next(obj for obj in db.added if isinstance(obj, ContractStructuringRun))

    assert failed_doc.task_status == "FAILED"
    assert "Task dispatch failed" in (failed_doc.error_message or "")
    assert passed_doc.task_status == "PENDING"
    assert events.count("commit") == 2
    mock_status_update.assert_awaited_once_with(run.id, tenant_id)
