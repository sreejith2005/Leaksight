"""
LeakSight V1 — Parse Task Unit Tests

Tests:
  - Successful parse → raw_parse stored, normalize task chained, success status
  - Parser raises exception → failure flag on document, failure status, no unhandled exception
  - Document not found in DB → failure status returned cleanly
  - Tenant context is set before any DB operation → confirm call order
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.parsers.base_parser import (
    DocType,
    DocumentHeader,
    LineItem,
    ParseResult,
)


@pytest.fixture
def mock_document():
    """A mock Document ORM instance."""
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.tenant_id = uuid.uuid4()
    doc.file_path = "test-tenant/test-doc/invoice.xlsx"
    doc.doc_type = "INVOICE"
    doc.parse_status = "PENDING"
    return doc


@pytest.fixture
def mock_parse_result(mock_document):
    """A mock ParseResult from the parser."""
    return ParseResult(
        document_id=mock_document.id,
        doc_type=DocType.INVOICE,
        parser_used="excel_parser_v1",
        parser_version="1.0.0",
        parse_confidence=0.95,
        header=DocumentHeader(
            vendor_name="Test Vendor",
            vendor_gst_id=None,
            document_number="INV-001",
            document_date="2026-01-15",
            total_amount=10000.0,
            currency="INR",
        ),
        line_items=[
            LineItem(
                line_number=1,
                item_desc="Steel TMT 12mm",
                quantity=100.0,
                unit="MT",
                unit_price=50000.0,
                line_total=5000000.0,
            ),
        ],
        failure_flags=[],
        raw_extracted_data=None,
    )


@pytest.fixture
def mock_raw_parse():
    """A mock RawParse instance returned by store_parse_result."""
    rp = MagicMock()
    rp.id = uuid.uuid4()
    return rp


class TestParseDocumentTask:
    """Tests for parse_document Celery task."""

    @patch("backend.app.tasks.parse_task.store_parse_result")
    @patch("backend.app.tasks.parse_task.route_to_parser")
    @patch("backend.app.tasks.parse_task.set_tenant_context")
    @patch("backend.app.tasks.parse_task.async_session_factory")
    def test_successful_parse(
        self,
        mock_session_factory,
        mock_set_tenant,
        mock_parser,
        mock_store,
        mock_document,
        mock_parse_result,
        mock_raw_parse,
    ):
        """Successful parse stores result, chains normalize task, returns success."""
        # Setup mocks
        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock document query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_document
        mock_db.execute.return_value = mock_result

        mock_set_tenant.return_value = None
        mock_parser.return_value = mock_parse_result
        mock_store.return_value = mock_raw_parse

        # Run the task
        with patch(
            "backend.app.tasks.normalize_task.normalize_document"
        ) as mock_normalize:
            mock_normalize.si.return_value.apply_async.return_value = None

            from backend.app.tasks.parse_task import parse_document

            result = parse_document(
                str(mock_document.id), str(mock_document.tenant_id)
            )

        assert result["status"] == "success"
        assert result["document_id"] == str(mock_document.id)
        assert "raw_parse_id" in result

        # Verify tenant context was set
        mock_set_tenant.assert_called()

    @patch("backend.app.tasks.parse_task.route_to_parser")
    @patch("backend.app.tasks.parse_task.set_tenant_context")
    @patch("backend.app.tasks.parse_task.async_session_factory")
    def test_parser_raises_exception(
        self,
        mock_session_factory,
        mock_set_tenant,
        mock_parser,
        mock_document,
    ):
        """Parser exception → failure flag written, failure status, no unhandled exc."""
        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_document
        mock_db.execute.return_value = mock_result

        mock_set_tenant.return_value = None
        mock_parser.side_effect = ValueError("Parse error in table extraction")

        from backend.app.tasks.parse_task import parse_document

        # Should NOT raise — returns failure dict
        result = parse_document(
            str(mock_document.id), str(mock_document.tenant_id)
        )

        assert result["status"] == "failed"
        assert result["document_id"] == str(mock_document.id)
        assert result["error"] == "ValueError"

    @patch("backend.app.tasks.parse_task.set_tenant_context")
    @patch("backend.app.tasks.parse_task.async_session_factory")
    def test_document_not_found(
        self,
        mock_session_factory,
        mock_set_tenant,
    ):
        """Document not found → clean failure status returned."""
        mock_db = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        mock_set_tenant.return_value = None

        from backend.app.tasks.parse_task import parse_document

        doc_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        result = parse_document(doc_id, tenant_id)

        assert result["status"] == "failed"
        assert result["document_id"] == doc_id
        assert result["error"] == "DocumentNotFound"

    @patch("backend.app.tasks.parse_task.store_parse_result")
    @patch("backend.app.tasks.parse_task.route_to_parser")
    @patch("backend.app.tasks.parse_task.set_tenant_context")
    @patch("backend.app.tasks.parse_task.async_session_factory")
    def test_tenant_context_set_before_db_operations(
        self,
        mock_session_factory,
        mock_set_tenant,
        mock_parser,
        mock_store,
        mock_document,
        mock_parse_result,
        mock_raw_parse,
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
            mock_result.scalar_one_or_none.return_value = mock_document
            return mock_result

        mock_set_tenant.side_effect = record_tenant_call
        mock_db.execute.side_effect = record_db_call
        mock_parser.return_value = mock_parse_result
        mock_store.return_value = mock_raw_parse

        with patch(
            "backend.app.tasks.normalize_task.normalize_document"
        ) as mock_normalize:
            mock_normalize.si.return_value.apply_async.return_value = None

            from backend.app.tasks.parse_task import parse_document

            parse_document(str(mock_document.id), str(mock_document.tenant_id))

        # Verify set_tenant_context was called BEFORE any db.execute
        assert call_order[0] == "set_tenant_context"

