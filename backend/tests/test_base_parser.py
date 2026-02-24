"""
Tests for LeakSight V1 — Parser Base Class

Tests:
1. ParseResult with raw_extracted_data excluded from repr
2. LineItem validates correctly with all field types
3. failure_flags is always a list, never None
4. ParseResult.to_jsonb serializes correctly
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.app.parsers.base_parser import (
    BaseParser,
    DocType,
    DocumentHeader,
    FailureFlag,
    FailureSeverity,
    LineItem,
    ParseResult,
    UnsupportedFormatError,
)


DOC_ID = uuid4()


def _make_parse_result(**overrides) -> ParseResult:
    """Create a ParseResult with sensible defaults."""
    defaults = {
        "document_id": DOC_ID,
        "doc_type": DocType.INVOICE,
        "parser_used": "test_parser_v1",
        "parser_version": "1.0.0",
        "parse_confidence": 0.95,
        "header": DocumentHeader(
            vendor_name="Test Vendor Pvt Ltd",
            document_number="INV-001",
            document_date=date(2026, 1, 15),
            total_amount=Decimal("50000.00"),
            currency="INR",
        ),
        "line_items": [
            LineItem(
                line_number=1,
                item_desc="Cement OPC 53 Grade",
                quantity=Decimal("100"),
                unit="MT",
                unit_price=Decimal("350.00"),
                line_total=Decimal("35000.00"),
            ),
        ],
        "failure_flags": [],
        "raw_extracted_data": {"raw_text": "This is raw document text that must never be logged"},
    }
    defaults.update(overrides)
    return ParseResult(**defaults)


# ── Test 1: raw_extracted_data excluded from repr ─────────────────────


def test_raw_extracted_data_excluded_from_repr():
    """ParseResult repr must not contain raw_extracted_data content."""
    result = _make_parse_result(
        raw_extracted_data={"raw_text": "SENSITIVE DOCUMENT CONTENT HERE"}
    )
    repr_str = repr(result)

    assert "SENSITIVE DOCUMENT CONTENT HERE" not in repr_str
    assert "raw_text" not in repr_str
    assert "[EXCLUDED FROM REPR]" in repr_str
    # But the data is still accessible
    assert result.raw_extracted_data["raw_text"] == "SENSITIVE DOCUMENT CONTENT HERE"


# ── Test 2: LineItem validates correctly ──────────────────────────────


def test_line_item_validates_correctly():
    """LineItem correctly holds all field types."""
    item = LineItem(
        line_number=1,
        item_desc="Steel TMT 12mm",
        quantity=Decimal("50.5"),
        unit="MT",
        unit_price=Decimal("42000.00"),
        line_total=Decimal("2121000.00"),
        ordered_qty=Decimal("55"),
        received_qty=Decimal("50.5"),
        field_confidences={"item_desc": 0.98, "unit_price": 0.95},
        extraction_notes=["Price extracted from table row 3"],
    )

    assert item.line_number == 1
    assert item.item_desc == "Steel TMT 12mm"
    assert item.quantity == Decimal("50.5")
    assert item.unit == "MT"
    assert item.unit_price == Decimal("42000.00")
    assert item.line_total == Decimal("2121000.00")
    assert item.ordered_qty == Decimal("55")
    assert item.received_qty == Decimal("50.5")
    assert item.field_confidences["item_desc"] == 0.98
    assert len(item.extraction_notes) == 1


def test_line_item_optional_fields_default_none():
    """LineItem optional fields default to None or empty."""
    item = LineItem(line_number=1)

    assert item.item_desc is None
    assert item.quantity is None
    assert item.unit is None
    assert item.unit_price is None
    assert item.line_total is None
    assert item.ordered_qty is None
    assert item.received_qty is None
    assert item.field_confidences == {}
    assert item.extraction_notes == []


# ── Test 3: failure_flags is always a list ────────────────────────────


def test_failure_flags_defaults_to_empty_list():
    """failure_flags defaults to an empty list, not None."""
    result = ParseResult(
        document_id=DOC_ID,
        doc_type=DocType.INVOICE,
        parser_used="test",
        parser_version="1.0.0",
        parse_confidence=0.5,
        header=DocumentHeader(),
        line_items=[],
    )
    assert result.failure_flags is not None
    assert isinstance(result.failure_flags, list)
    assert len(result.failure_flags) == 0


def test_failure_flags_with_entries():
    """failure_flags correctly stores FailureFlag objects."""
    flags = [
        FailureFlag(
            severity="ERROR",
            code="MISSING_DOCUMENT_NUMBER",
            message="Invoice number could not be extracted",
        ),
        FailureFlag(
            severity="WARNING",
            code="MISSING_VENDOR_NAME",
            message="Vendor name not found in document",
            page_number=1,
            field_name="vendor_name",
        ),
    ]
    result = _make_parse_result(failure_flags=flags)

    assert len(result.failure_flags) == 2
    assert result.failure_flags[0].severity == "ERROR"
    assert result.failure_flags[0].code == "MISSING_DOCUMENT_NUMBER"
    assert result.failure_flags[1].page_number == 1


# ── Test 4: to_jsonb serialization ────────────────────────────────────


def test_to_jsonb_serializes_correctly():
    """ParseResult.to_jsonb produces a valid dict for JSONB storage."""
    result = _make_parse_result()
    jsonb = result.to_jsonb()

    assert jsonb["document_id"] == str(DOC_ID)
    assert jsonb["doc_type"] == "INVOICE"
    assert jsonb["parser_used"] == "test_parser_v1"
    assert jsonb["parse_confidence"] == 0.95
    assert jsonb["header"]["vendor_name"] == "Test Vendor Pvt Ltd"
    assert jsonb["header"]["document_number"] == "INV-001"
    assert jsonb["header"]["document_date"] == "2026-01-15"
    assert jsonb["header"]["total_amount"] == "50000.00"
    assert len(jsonb["line_items"]) == 1
    assert jsonb["line_items"][0]["item_desc"] == "Cement OPC 53 Grade"
    assert jsonb["line_items"][0]["quantity"] == "100"


# ── Test 5: UnsupportedFormatError ────────────────────────────────────


def test_unsupported_format_error():
    """UnsupportedFormatError stores the extension."""
    err = UnsupportedFormatError(".zip")
    assert err.extension == ".zip"
    assert ".zip" in str(err)
