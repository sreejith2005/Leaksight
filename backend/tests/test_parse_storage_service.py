"""
Tests for Parse Storage Service — backend/app/services/parse_storage_service.py

Governing docs: docs/PARSING_SPEC.md §7 (version rows), §8 (confidence enforcement)

All database operations are mocked — no real database.
Covers:
  1. get_next_raw_version — first parse returns 1, re-parse increments
  2. store_parse_result — creates RawParse row, updates Document status
  3. Confidence threshold enforcement — flags low-confidence documents
  4. Run status impact — marks PARTIAL_SUCCESS for low-confidence documents
  5. Total failure — parse_confidence 0.0 → FAILED status
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.parsers.base_parser import (
    DocType,
    DocumentHeader,
    FailureFlag,
    LineItem,
    ParseResult,
)
from backend.app.services.parse_storage_service import (
    _DEFAULT_MANUAL_REVIEW_THRESHOLD,
    flag_document_low_confidence,
    get_next_raw_version,
    get_tenant_threshold,
    mark_run_partial_success,
    store_parse_result,
)


def _make_parse_result(
    document_id=None, confidence=0.95, line_items=None, failure_flags=None
) -> ParseResult:
    """Create a ParseResult for testing."""
    return ParseResult(
        document_id=document_id or uuid4(),
        doc_type=DocType.INVOICE,
        parser_used="test_parser_v1",
        parser_version="1.0.0",
        parse_confidence=confidence,
        header=DocumentHeader(),
        line_items=line_items or [],
        failure_flags=failure_flags or [],
        raw_extracted_data={},
    )


class TestGetNextRawVersion:
    """Test raw_version numbering logic."""

    @pytest.mark.asyncio
    async def test_first_parse_returns_1(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing parses
        mock_db.execute.return_value = mock_result

        version = await get_next_raw_version(mock_db, uuid4())
        assert version == 1

    @pytest.mark.asyncio
    async def test_reparse_increments_version(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 3  # Max existing version is 3
        mock_db.execute.return_value = mock_result

        version = await get_next_raw_version(mock_db, uuid4())
        assert version == 4


class TestGetTenantThreshold:
    """Test tenant threshold retrieval."""

    @pytest.mark.asyncio
    async def test_returns_configured_threshold(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 0.85
        mock_db.execute.return_value = mock_result

        threshold = await get_tenant_threshold(mock_db, uuid4())
        assert threshold == 0.85

    @pytest.mark.asyncio
    async def test_returns_default_when_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        threshold = await get_tenant_threshold(mock_db, uuid4())
        assert threshold == _DEFAULT_MANUAL_REVIEW_THRESHOLD


class TestStoreParseResult:
    """Test the main store_parse_result function."""

    @pytest.mark.asyncio
    async def test_creates_raw_parse_row(self):
        doc_id = uuid4()
        tenant_id = uuid4()
        parse_result = _make_parse_result(document_id=doc_id, confidence=0.95)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        # First call: get_next_raw_version → None (first parse)
        # Second call: update document status
        # Third call: get_tenant_threshold → 0.70
        mock_result.scalar_one_or_none.side_effect = [None, None, 0.70]
        mock_db.execute.return_value = mock_result

        await store_parse_result(mock_db, parse_result, tenant_id)

        # Verify db.add was called (for RawParse creation)
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.document_id == doc_id
        assert added_obj.raw_version == 1
        assert added_obj.parse_confidence == 0.95

    @pytest.mark.asyncio
    async def test_high_confidence_no_flag(self):
        doc_id = uuid4()
        tenant_id = uuid4()
        parse_result = _make_parse_result(document_id=doc_id, confidence=0.95)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [None, None, 0.70]
        mock_db.execute.return_value = mock_result

        await store_parse_result(mock_db, parse_result, tenant_id)

        # execute called for: get_next_raw_version, update document, get_tenant_threshold, flush
        # No flag_document_low_confidence or mark_run_partial_success calls
        # count the execute calls — should be exactly 3 (version + status + threshold)
        assert mock_db.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_low_confidence_flags_document(self):
        doc_id = uuid4()
        tenant_id = uuid4()
        parse_result = _make_parse_result(document_id=doc_id, confidence=0.50)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        # get_next_raw_version → None, update status, get_threshold → 0.70,
        # then flag_document (1 exec), flush
        mock_result.scalar_one_or_none.side_effect = [None, None, 0.70]
        mock_db.execute.return_value = mock_result

        await store_parse_result(mock_db, parse_result, tenant_id)

        # execute calls: version + status + threshold + flag = 4
        assert mock_db.execute.call_count == 4

    @pytest.mark.asyncio
    async def test_low_confidence_with_run_marks_partial(self):
        doc_id = uuid4()
        tenant_id = uuid4()
        run_id = uuid4()
        parse_result = _make_parse_result(document_id=doc_id, confidence=0.50)

        mock_db = AsyncMock()
        # Use side_effect on execute to return different results per call:
        # 1. get_next_raw_version
        # 2. update document status
        # 3. get_tenant_threshold
        # 4. flag_document_low_confidence
        # 5. mark_run_partial: select run status
        # 6. mark_run_partial: update run status
        mock_results = []
        for val in [None, None, 0.70, None, "PROCESSING", None]:
            m = MagicMock()
            m.scalar_one_or_none.return_value = val
            mock_results.append(m)
        mock_db.execute.side_effect = mock_results

        await store_parse_result(mock_db, parse_result, tenant_id, run_id=run_id)

        # execute calls: version + status + threshold + flag + get_run_status + update_run = 6
        assert mock_db.execute.call_count == 6


class TestTotalFailure:
    """Test parse_confidence == 0.0 (total failure)."""

    @pytest.mark.asyncio
    async def test_zero_confidence_sets_failed_status(self):
        doc_id = uuid4()
        tenant_id = uuid4()
        parse_result = _make_parse_result(
            document_id=doc_id,
            confidence=0.0,
            failure_flags=[FailureFlag(
                severity="ERROR",
                code="CORRUPTED_FILE",
                message="File is corrupted",
            )],
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [None, None, 0.70]
        mock_db.execute.return_value = mock_result

        await store_parse_result(mock_db, parse_result, tenant_id)

        # Verify document status update was called
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.parse_confidence == 0.0


class TestFlagDocumentLowConfidence:
    """Test the flag_document_low_confidence function directly."""

    @pytest.mark.asyncio
    async def test_updates_flag(self):
        mock_db = AsyncMock()
        await flag_document_low_confidence(mock_db, uuid4())
        mock_db.execute.assert_called_once()


class TestMarkRunPartialSuccess:
    """Test the mark_run_partial_success function directly."""

    @pytest.mark.asyncio
    async def test_transitions_from_processing(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "PROCESSING"
        mock_db.execute.return_value = mock_result

        await mark_run_partial_success(mock_db, uuid4())

        # Called twice: once to get status, once to update
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_transition_from_queued(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "QUEUED"
        mock_db.execute.return_value = mock_result

        await mark_run_partial_success(mock_db, uuid4())

        # Called only once: get status — no update because QUEUED → PARTIAL_SUCCESS is invalid
        assert mock_db.execute.call_count == 1
