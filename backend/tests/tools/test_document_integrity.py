"""Tests for Tool B document integrity components and API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from backend.app.core.database import get_db
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.tools.document_integrity.analyzers.hash_comparator import HashComparator
from backend.app.tools.document_integrity.analyzers.metadata_extractor import MetadataExtractor
from backend.app.tools.document_integrity.analyzers.numeric_comparator import NumericComparator
from backend.app.tools.document_integrity.analyzers.risk_scorer import RiskScorer
from backend.app.tools.document_integrity.router import router

TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
DOCUMENT_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
HASH_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")


def _create_app(user: CurrentUser | None = None, db_mock: AsyncMock | None = None) -> FastAPI:
    app = FastAPI()
    api_router = APIRouter(prefix="/api/v1/integrity", tags=["integrity"])
    api_router.include_router(router)
    app.include_router(api_router)

    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if db_mock is not None:

        async def _db():
            yield db_mock

        app.dependency_overrides[get_db] = _db

    return app


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        email="admin@example.com",
        role="ADMIN",
    )


def _db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock()
    return db


def _document() -> SimpleNamespace:
    return SimpleNamespace(
        id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        original_filename="Sample Contract 1.pdf",
        doc_type="CONTRACT",
        created_at=datetime.now(timezone.utc),
    )


def _hash() -> SimpleNamespace:
    return SimpleNamespace(
        id=HASH_ID,
        document_id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        risk_score=72,
        comparison_status="MODIFIED",
        flagged_anomalies_jsonb={
            "flags": ["Document hash has changed since baseline"],
            "numeric_changes": [
                {
                    "previous_value": 100.0,
                    "current_value": 125.0,
                    "context": "Total amount payable",
                    "change_pct": 25.0,
                }
            ],
        },
        metadata_jsonb={"author": "tester", "anomalies": []},
        created_at=datetime.now(timezone.utc),
    )


def _scalar_one_result(value: int):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _rows_result(rows: list[tuple[object, object]]):
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_metadata_extractor_real_pdf_returns_dict_without_raising():
    extractor = MetadataExtractor()
    pdf_path = Path("data/demo/Sample Contract 1.pdf")

    metadata = extractor.extract(pdf_path, "CONTRACT")

    assert isinstance(metadata, dict)
    assert set(metadata.keys()) == {
        "creation_date",
        "modification_date",
        "author",
        "software",
        "page_count",
        "revision_count",
        "anomalies",
    }


def test_risk_scorer_new_document_scores_zero():
    scorer = RiskScorer()

    score, flags = scorer.score(
        hash_result={"status": "NEW"},
        metadata={"anomalies": []},
        numeric_changes=[],
    )

    assert score == 0
    assert flags == []


def test_risk_scorer_modified_without_numeric_changes_scores_40():
    scorer = RiskScorer()

    score, flags = scorer.score(
        hash_result={"status": "MODIFIED"},
        metadata={"anomalies": []},
        numeric_changes=[],
    )

    assert score == 40
    assert "Document hash has changed since baseline" in flags


def test_risk_scorer_modified_with_numeric_changes_scores_at_least_65():
    scorer = RiskScorer()

    score, flags = scorer.score(
        hash_result={"status": "MODIFIED"},
        metadata={"anomalies": []},
        numeric_changes=[
            {
                "previous_value": 100.0,
                "current_value": 125.0,
                "context": "invoice total",
                "change_pct": 25.0,
            }
        ],
    )

    assert score >= 65
    assert any("numeric values changed" in flag for flag in flags)


def test_risk_scorer_metadata_anomaly_adds_expected_score():
    scorer = RiskScorer()

    score, flags = scorer.score(
        hash_result={"status": "NEW"},
        metadata={"anomalies": ["missing_author_metadata"]},
        numeric_changes=[],
    )

    assert score == 5
    assert "Metadata author field is missing" in flags


def test_numeric_comparator_compare_same_values_returns_empty():
    comparator = NumericComparator()

    changes = comparator.compare(
        current=[{"value": 100.0, "context": "Net amount due", "location": "Page 1"}],
        previous=[{"value": 100.0, "context": "Net amount due", "location": "Page 1"}],
    )

    assert changes == []


def test_numeric_comparator_compare_changed_value_returns_change_pct():
    comparator = NumericComparator()

    changes = comparator.compare(
        current=[{"value": 125.0, "context": "Net amount due", "location": "Page 1"}],
        previous=[{"value": 100.0, "context": "Net amount due", "location": "Page 1"}],
    )

    assert len(changes) == 1
    assert changes[0]["previous_value"] == 100.0
    assert changes[0]["current_value"] == 125.0
    assert changes[0]["change_pct"] == 25.0


def test_hash_comparator_uses_previous_document_with_same_filename():
    tenant_id = uuid.uuid4()
    previous_document_id = uuid.uuid4()
    previous_hash_id = uuid.uuid4()
    db_session = MagicMock()

    current_document = SimpleNamespace(
        id=DOCUMENT_ID,
        tenant_id=tenant_id,
        original_filename="Sample Invoice.xlsx",
        doc_type="INVOICE",
    )
    current_hash = SimpleNamespace(
        id=HASH_ID,
        document_id=DOCUMENT_ID,
        tenant_id=tenant_id,
        hash_sha256="b" * 64,
        upload_sequence=1,
    )
    previous_document = SimpleNamespace(
        id=previous_document_id,
        tenant_id=tenant_id,
        original_filename="Sample Invoice.xlsx",
        doc_type="INVOICE",
    )
    previous_hash = SimpleNamespace(
        id=previous_hash_id,
        document_id=previous_document_id,
        tenant_id=tenant_id,
        hash_sha256="a" * 64,
        upload_sequence=1,
    )

    db_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=current_document)),
        MagicMock(scalars=MagicMock(return_value=[current_hash])),
        MagicMock(scalars=MagicMock(return_value=[previous_document])),
        MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=previous_hash)))),
    ]

    result = HashComparator().compare(
        document_id=str(DOCUMENT_ID),
        tenant_id=str(tenant_id),
        db_session=db_session,
    )

    assert result["status"] == "MODIFIED"
    assert result["previous_version_id"] == str(previous_hash_id)
    assert result["version_count"] == 2
    assert result["hash_changed"] is True

def test_post_analyze_document_returns_202():
    db = _db()
    db.scalar = AsyncMock(return_value=_document())

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.document_integrity.router.set_tenant_context", new_callable=AsyncMock):
        with patch("backend.app.tools.document_integrity.router.run_integrity_analysis") as task_mock:
            response = client.post(f"/api/v1/integrity/analyze/{DOCUMENT_ID}")

    assert response.status_code == 202
    assert response.json() == {
        "task_queued": True,
        "document_id": str(DOCUMENT_ID),
    }
    task_mock.delay.assert_called_once_with(str(DOCUMENT_ID), str(TENANT_ID))


def test_get_integrity_documents_returns_list():
    db = _db()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_result(1),
            _rows_result([(_document(), _hash())]),
        ]
    )

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.document_integrity.router.set_tenant_context", new_callable=AsyncMock):
        response = client.get("/api/v1/integrity/documents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert len(payload["items"]) == 1
    assert payload["items"][0]["document_id"] == str(DOCUMENT_ID)
    assert payload["items"][0]["risk_level"] == "HIGH"


def test_get_integrity_document_keeps_null_risk_fields():
    db = _db()
    pending_hash = SimpleNamespace(
        id=HASH_ID,
        document_id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        risk_score=None,
        comparison_status="NEW",
        flagged_anomalies_jsonb=None,
        metadata_jsonb=None,
        created_at=datetime.now(timezone.utc),
    )
    db.scalar = AsyncMock(return_value=_document())
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=[pending_hash])),
            _scalar_one_result(2),
        ]
    )

    app = _create_app(user=_user(), db_mock=db)
    client = TestClient(app)

    with patch("backend.app.tools.document_integrity.router.set_tenant_context", new_callable=AsyncMock):
        response = client.get(f"/api/v1/integrity/documents/{DOCUMENT_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_score"] is None
    assert payload["risk_level"] is None
    assert payload["version_count"] == 2
    assert payload["analyzed_at"] is None
