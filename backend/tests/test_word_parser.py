"""
Tests for WordParser — backend/app/parsers/word_parser.py

Governing doc: docs/PARSING_SPEC.md §5.4

Uses both real docx fixtures and mocked python-docx objects.
Covers:
  1. Clean docx with tables — ≥ 0.85 confidence, line items extracted
  2. No tables — WARNING flag, confidence deduction
  3. Multi-table document — all tables processed
  4. Malformed file — no crash, confidence 0.0
  5. Header extraction from paragraphs
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.parsers.word_parser import WordParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser():
    return WordParser()


@pytest.fixture
def doc_id():
    return uuid4()


def _make_mock_cell(text: str):
    """Create a mock docx table cell."""
    cell = MagicMock()
    cell.text = text
    return cell


def _make_mock_row(cells: list[str]):
    """Create a mock docx table row."""
    row = MagicMock()
    row.cells = [_make_mock_cell(c) for c in cells]
    return row


def _make_mock_table(rows: list[list[str]]):
    """Create a mock docx Table."""
    table = MagicMock()
    table.rows = [_make_mock_row(r) for r in rows]
    return table


def _make_mock_paragraph(text: str):
    """Create a mock docx paragraph."""
    para = MagicMock()
    para.text = text
    return para


class TestCleanDocx:
    """Clean Word document with header paragraphs and table."""

    def _get_result(self, parser, doc_id):
        paragraphs = [
            _make_mock_paragraph("Vendor: Ultratech Cement Ltd"),
            _make_mock_paragraph("Invoice No: INV-2024-0567"),
            _make_mock_paragraph("Date: 15/03/2024"),
            _make_mock_paragraph("GSTIN: 29AABCU9603R1ZM"),
            _make_mock_paragraph(""),
        ]
        table = _make_mock_table([
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Cement OPC 53 Grade", "100", "Bags", "350.00", "35000.00"],
            ["TMT Steel 12mm", "500", "Kg", "72.50", "36250.00"],
            ["River Sand", "10", "Cum", "2800.00", "28000.00"],
        ])
        mock_doc = MagicMock()
        mock_doc.paragraphs = paragraphs
        mock_doc.tables = [table]

        with patch("backend.app.parsers.word_parser.DocxDocument", return_value=mock_doc):
            return parser.parse(Path("test.docx"), doc_id)

    def test_confidence_above_85(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.parse_confidence >= 0.85

    def test_extracts_vendor(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.vendor_name == "Ultratech Cement Ltd"

    def test_extracts_doc_number(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.document_number == "INV-2024-0567"

    def test_extracts_date(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.document_date is not None
        assert result.header.document_date.year == 2024

    def test_extracts_gst(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.vendor_gst_id == "29AABCU9603R1ZM"

    def test_extracts_all_line_items(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert len(result.line_items) == 3

    def test_first_item_values(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        item = result.line_items[0]
        assert item.item_desc == "Cement OPC 53 Grade"
        assert item.quantity == Decimal("100")
        assert item.unit_price == Decimal("350")

    def test_parser_metadata(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.parser_used == "word_parser_v1"


class TestNoTables:
    """Word document with no tables."""

    def test_no_tables_warning(self, parser, doc_id):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [_make_mock_paragraph("Some text")]
        mock_doc.tables = []

        with patch("backend.app.parsers.word_parser.DocxDocument", return_value=mock_doc):
            result = parser.parse(Path("test.docx"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "NO_TABLES_FOUND" in codes

    def test_confidence_reduced(self, parser, doc_id):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [_make_mock_paragraph("Some text")]
        mock_doc.tables = []

        with patch("backend.app.parsers.word_parser.DocxDocument", return_value=mock_doc):
            result = parser.parse(Path("test.docx"), doc_id)

        assert result.parse_confidence <= 0.80


class TestMultiTable:
    """Word document with multiple tables (e.g., contract with pricing categories)."""

    def test_extracts_from_all_tables(self, parser, doc_id):
        paragraphs = [
            _make_mock_paragraph("Vendor: Multi Corp"),
            _make_mock_paragraph("Contract Ref: CTR-001"),
            _make_mock_paragraph("Date: 01/06/2024"),
        ]
        table1 = _make_mock_table([
            ["Item", "Qty", "Unit", "Price", "Total"],
            ["Cement", "100", "Bags", "350", "35000"],
        ])
        table2 = _make_mock_table([
            ["Item", "Qty", "Unit", "Price", "Total"],
            ["Steel", "500", "Kg", "72", "36000"],
            ["Sand", "10", "Cum", "2800", "28000"],
        ])
        mock_doc = MagicMock()
        mock_doc.paragraphs = paragraphs
        mock_doc.tables = [table1, table2]

        with patch("backend.app.parsers.word_parser.DocxDocument", return_value=mock_doc):
            result = parser.parse(Path("test.docx"), doc_id)

        assert len(result.line_items) == 3


class TestMalformedFile:
    """Corrupted Word document."""

    def test_no_crash(self, parser, doc_id):
        with patch("backend.app.parsers.word_parser.DocxDocument", side_effect=Exception("Bad file")):
            result = parser.parse(Path("test.docx"), doc_id)
        assert result is not None

    def test_zero_confidence(self, parser, doc_id):
        with patch("backend.app.parsers.word_parser.DocxDocument", side_effect=Exception("Bad file")):
            result = parser.parse(Path("test.docx"), doc_id)
        assert result.parse_confidence == 0.0

    def test_corrupted_flag(self, parser, doc_id):
        with patch("backend.app.parsers.word_parser.DocxDocument", side_effect=Exception("Bad file")):
            result = parser.parse(Path("test.docx"), doc_id)
        codes = [f.code for f in result.failure_flags]
        assert "CORRUPTED_FILE" in codes


class TestHeaderExtraction:
    """Test various header extraction scenarios."""

    def test_missing_vendor_warning(self, parser, doc_id):
        paragraphs = [
            _make_mock_paragraph("Invoice No: INV-777"),
            _make_mock_paragraph("Date: 01/01/2024"),
        ]
        table = _make_mock_table([
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Item A", "1", "Nos", "100", "100"],
        ])
        mock_doc = MagicMock()
        mock_doc.paragraphs = paragraphs
        mock_doc.tables = [table]

        with patch("backend.app.parsers.word_parser.DocxDocument", return_value=mock_doc):
            result = parser.parse(Path("test.docx"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "MISSING_VENDOR_NAME" in codes

    def test_missing_date_reduces_confidence(self, parser, doc_id):
        paragraphs = [
            _make_mock_paragraph("Vendor: TestCo"),
            _make_mock_paragraph("Invoice No: INV-888"),
        ]
        table = _make_mock_table([
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Item B", "5", "Nos", "200", "1000"],
        ])
        mock_doc = MagicMock()
        mock_doc.paragraphs = paragraphs
        mock_doc.tables = [table]

        with patch("backend.app.parsers.word_parser.DocxDocument", return_value=mock_doc):
            result = parser.parse(Path("test.docx"), doc_id)

        assert result.parse_confidence <= 0.90


class TestRealDocxFixture:
    """Test with a real .docx file if it exists."""

    def test_real_docx_file(self, parser, doc_id):
        fixture_path = FIXTURES / "clean_invoice.docx"
        if not fixture_path.exists():
            pytest.skip("clean_invoice.docx fixture not generated")
        result = parser.parse(fixture_path, doc_id)
        assert result is not None
        assert result.parse_confidence >= 0.0
