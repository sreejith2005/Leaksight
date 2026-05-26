"""
LeakSight V1 — Normalization Task Unit Tests

Tests:
  - Successful normalization → canonical records created, success status
  - Normalization raises exception → error flag written, failure status, no unhandled exc
  - Raw parse not found → failure status returned cleanly
  - Tenant context set before any DB operation → confirm call order
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.normalization_service import NormalizationResult


@pytest.fixture
def mock_raw_parse():
    """A mock RawParse ORM instance."""
    rp = MagicMock()
    rp.id = uuid.uuid4()
    rp.document_id = uuid.uuid4()
    rp.tenant_id = uuid.uuid4()
    rp.raw_version = 1
    rp.parser_used = "excel_parser_v1"
    rp.parser_version = "1.0.0"
    rp.parse_confidence = 0.95
    rp.failure_flags = []
    rp.structured_output_jsonb = {
        "doc_type": "INVOICE",
        "header": {
            "vendor_name": "Test Vendor Pvt Ltd",
            "vendor_gst_id": "29ABCDE1234F1Z5",
            "document_number": "INV-2026-001",
            "document_date": "2026-01-15",
            "total_amount": 500000.0,
            "currency": "INR",
        },
        "line_items": [
            {
                "line_number": 1,
                "item_desc": "Steel TMT 12mm",
                "quantity": 100.0,
                "unit": "MT",
                "unit_price": 5000.0,
                "line_total": 500000.0,
            },
        ],
        "raw_extracted_data": None,
    }
    return rp


@pytest.fixture
def mock_norm_result():
    """A mock NormalizationResult."""
    return NormalizationResult(
        document_id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        vendor_match_method="GST_EXACT",
        vendor_match_confidence=1.0,
        invoice_id=uuid.uuid4(),
        line_items_created=3,
        skipped=False,
        skip_reason=None,
    )


class TestNormalizeDocumentTask:
    """Tests for normalize_document Celery task."""

    @patch("backend.app.tasks.normalize_task.normalize_service_fn")
    @patch("backend.app.tasks.normalize_task.set_tenant_context")
    @patch("backend.app.tasks.normalize_task.async_session_factory")
    def test_successful_normalization(
        self,
        mock_session_factory,
        mock_set_tenant,
        mock_normalize_svc,
        mock_raw_parse,
        mock_norm_result,
    ):
        """Successful normalization returns success with summary."""
        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_raw_parse
        mock_db.execute.return_value = mock_result

        mock_set_tenant.return_value = None
        mock_normalize_svc.return_value = mock_norm_result

        from backend.app.tasks.normalize_task import normalize_document

        result = normalize_document(
            str(mock_raw_parse.id), str(mock_raw_parse.tenant_id)
        )

        assert result["status"] == "success"
        assert result["raw_parse_id"] == str(mock_raw_parse.id)
        assert "canonical_records_created" in result
        mock_set_tenant.assert_called()

    @patch("backend.app.tasks.normalize_task.normalize_service_fn")
    @patch("backend.app.tasks.normalize_task.set_tenant_context")
    @patch("backend.app.tasks.normalize_task.async_session_factory")
    def test_normalization_raises_exception(
        self,
        mock_session_factory,
        mock_set_tenant,
        mock_normalize_svc,
        mock_raw_parse,
    ):
        """Exception during normalization → error flag written, failure status."""
        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_raw_parse
        mock_db.execute.return_value = mock_result

        mock_set_tenant.return_value = None
        mock_normalize_svc.side_effect = RuntimeError("DB constraint violation")

        from backend.app.tasks.normalize_task import normalize_document

        result = normalize_document(
            str(mock_raw_parse.id), str(mock_raw_parse.tenant_id)
        )

        assert result["status"] == "failed"
        assert result["error"] == "RuntimeError"

    @patch("backend.app.tasks.normalize_task.set_tenant_context")
    @patch("backend.app.tasks.normalize_task.async_session_factory")
    def test_raw_parse_not_found(
        self,
        mock_session_factory,
        mock_set_tenant,
    ):
        """Raw parse not found → clean failure status."""
        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        mock_set_tenant.return_value = None

        from backend.app.tasks.normalize_task import normalize_document

        rp_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        result = normalize_document(rp_id, tenant_id)

        assert result["status"] == "failed"
        assert result["raw_parse_id"] == rp_id
        assert result["error"] == "RawParseNotFound"

    @patch("backend.app.tasks.normalize_task.normalize_service_fn")
    @patch("backend.app.tasks.normalize_task.set_tenant_context")
    @patch("backend.app.tasks.normalize_task.async_session_factory")
    def test_tenant_context_set_before_db_operations(
        self,
        mock_session_factory,
        mock_set_tenant,
        mock_normalize_svc,
        mock_raw_parse,
        mock_norm_result,
    ):
        """Tenant context must be set before any database query."""
        call_order = []

        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        async def record_tenant_call(*args, **kwargs):
            call_order.append("set_tenant_context")

        async def record_db_call(*args, **kwargs):
            call_order.append("db_execute")
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_raw_parse
            return mock_result

        mock_set_tenant.side_effect = record_tenant_call
        mock_db.execute.side_effect = record_db_call
        mock_normalize_svc.return_value = mock_norm_result

        from backend.app.tasks.normalize_task import normalize_document

        normalize_document(str(mock_raw_parse.id), str(mock_raw_parse.tenant_id))

        assert call_order[0] == "set_tenant_context"

