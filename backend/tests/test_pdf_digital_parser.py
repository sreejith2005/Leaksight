"""
Tests for DigitalPdfParser — backend/app/parsers/pdf_digital_parser.py

Governing doc: docs/PARSING_SPEC.md §5.2

Tests use mocked pdfplumber objects to avoid requiring real PDF files.
Covers:
  1. Clean digital PDF — header + table extraction, ≥ 0.85 confidence
  2. Camelot fallback — when pdfplumber tables are empty
  3. Multi-page PDF — concatenation of tables
  4. Malformed PDF — no crash, confidence 0.0
  5. Header extraction — vendor, doc number, date, GST
  6. Footer filtering — skips footer rows
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.parsers.pdf_digital_parser import DigitalPdfParser


@pytest.fixture
def parser():
    return DigitalPdfParser()


@pytest.fixture
def doc_id():
    return uuid4()


def _make_mock_page(text: str, tables: list[list[list[str | None]]] | None = None):
    """Create a mock pdfplumber page."""
    page = MagicMock()
    page.extract_text.return_value = text
    page.extract_tables.return_value = tables or []
    return page


def _make_mock_pdf(pages: list):
    """Create a mock pdfplumber PDF context manager."""
    mock_pdf = MagicMock()
    mock_pdf.pages = pages
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


class TestCleanDigitalPdf:
    """Clean single-page digital PDF with header and table."""

    def _get_result(self, parser, doc_id):
        header_text = (
            "Vendor: Ultratech Cement Ltd\n"
            "Invoice No: INV-2024-0567\n"
            "Date: 15/03/2024\n"
            "GSTIN: 29AABCU9603R1ZM\n"
            "Total: ₹1,45,000.00\n"
        )
        table = [
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Cement OPC 53 Grade", "100", "Bags", "350.00", "35000.00"],
            ["TMT Steel 12mm", "500", "Kg", "72.50", "36250.00"],
            ["River Sand", "10", "Cum", "2800.00", "28000.00"],
        ]
        page = _make_mock_page(header_text, [table])
        mock_pdf = _make_mock_pdf([page])

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            return parser.parse(Path("test.pdf"), doc_id)

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
        assert result.header.document_date.month == 3
        assert result.header.document_date.day == 15

    def test_extracts_gst(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.vendor_gst_id == "29AABCU9603R1ZM"

    def test_extracts_line_items(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert len(result.line_items) == 3

    def test_first_line_item_values(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        item = result.line_items[0]
        assert item.item_desc == "Cement OPC 53 Grade"
        assert item.quantity == Decimal("100")
        assert item.unit_price == Decimal("350")
        assert item.line_total == Decimal("35000")

    def test_parser_metadata(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.parser_used == "pdf_digital_parser_v1"
        assert result.document_id == doc_id


class TestCamelotFallback:
    """When pdfplumber tables are empty, camelot should be used."""

    def test_uses_camelot_when_pdfplumber_empty(self, parser, doc_id):
        header_text = "Invoice No: INV-001\nDate: 01/01/2024\nVendor: TestCo\n"
        page = _make_mock_page(header_text, [])  # No tables from pdfplumber
        mock_pdf = _make_mock_pdf([page])

        # Mock camelot to return a table
        mock_camelot_table = MagicMock()
        mock_camelot_df = MagicMock()
        mock_camelot_df.values.tolist.return_value = [
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Widget A", "10", "Nos", "100.00", "1000.00"],
        ]
        mock_camelot_table.df = mock_camelot_df

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            with patch("camelot.read_pdf", return_value=[mock_camelot_table]):
                result = parser.parse(Path("test.pdf"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "TABLE_EXTRACTION_FALLBACK" in codes

    def test_camelot_fallback_deducts_confidence(self, parser, doc_id):
        header_text = "Invoice No: INV-001\nDate: 01/01/2024\nVendor: TestCo\n"
        page = _make_mock_page(header_text, [])
        mock_pdf = _make_mock_pdf([page])

        mock_camelot_table = MagicMock()
        mock_camelot_df = MagicMock()
        mock_camelot_df.values.tolist.return_value = [
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Widget A", "10", "Nos", "100.00", "1000.00"],
        ]
        mock_camelot_table.df = mock_camelot_df

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            with patch("camelot.read_pdf", return_value=[mock_camelot_table]):
                result = parser.parse(Path("test.pdf"), doc_id)

        assert result.parse_confidence <= 0.90


class TestMultiPagePdf:
    """Test multi-page PDF table concatenation."""

    def test_concatenates_tables_across_pages(self, parser, doc_id):
        header_text = "Invoice No: INV-002\nDate: 10/04/2024\nVendor: Acc Ltd\n"
        table1 = [
            ["Item", "Qty", "Unit", "Price", "Amount"],
            ["Cement", "100", "Bags", "300", "30000"],
        ]
        table2 = [
            ["Item", "Qty", "Unit", "Price", "Amount"],
            ["Steel", "200", "Kg", "70", "14000"],
        ]
        page1 = _make_mock_page(header_text, [table1])
        page2 = _make_mock_page("", [table2])
        mock_pdf = _make_mock_pdf([page1, page2])

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            result = parser.parse(Path("test.pdf"), doc_id)

        assert len(result.line_items) >= 2

    def test_multi_page_flags_concatenation(self, parser, doc_id):
        header_text = "Invoice No: INV-003\nDate: 01/01/2024\nVendor: TestCo\n"
        table1 = [
            ["Description", "Qty", "Unit", "Rate", "Total"],
            ["Item A", "5", "Nos", "100", "500"],
        ]
        table2 = [
            ["Description", "Qty", "Unit", "Rate", "Total"],
            ["Item B", "10", "Nos", "200", "2000"],
        ]
        page1 = _make_mock_page(header_text, [table1])
        page2 = _make_mock_page("", [table2])
        mock_pdf = _make_mock_pdf([page1, page2])

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            result = parser.parse(Path("test.pdf"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "MULTI_PAGE_TABLE_CONCATENATED" in codes


class TestMalformedPdf:
    """Test handling of corrupted/unreadable PDF files."""

    def test_no_crash(self, parser, doc_id):
        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("Corrupted PDF")
            result = parser.parse(Path("test.pdf"), doc_id)

        assert result is not None

    def test_zero_confidence(self, parser, doc_id):
        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("Corrupted PDF")
            result = parser.parse(Path("test.pdf"), doc_id)

        assert result.parse_confidence == 0.0

    def test_corrupted_flag(self, parser, doc_id):
        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("Bad file")
            result = parser.parse(Path("test.pdf"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "CORRUPTED_FILE" in codes


class TestFooterFiltering:
    """Footer patterns should be skipped."""

    def test_skips_footer_rows(self, parser, doc_id):
        header_text = "Invoice No: INV-004\nDate: 01/06/2024\nVendor: MatCo\n"
        table = [
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Cement", "50", "Bags", "400", "20000"],
            ["Thank you for your business", None, None, None, None],
            ["Page 1 of 1", None, None, None, None],
        ]
        page = _make_mock_page(header_text, [table])
        mock_pdf = _make_mock_pdf([page])

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            result = parser.parse(Path("test.pdf"), doc_id)

        assert len(result.line_items) == 1
        assert result.line_items[0].item_desc == "Cement"


class TestHeaderExtraction:
    """Test various header extraction scenarios."""

    def test_missing_vendor_produces_warning(self, parser, doc_id):
        header_text = "Invoice No: INV-005\nDate: 01/01/2024\n"
        table = [
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Item X", "1", "Nos", "100", "100"],
        ]
        page = _make_mock_page(header_text, [table])
        mock_pdf = _make_mock_pdf([page])

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            result = parser.parse(Path("test.pdf"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "MISSING_VENDOR_NAME" in codes

    def test_total_amount_extraction(self, parser, doc_id):
        header_text = (
            "Vendor: ABC Corp\n"
            "Invoice No: INV-006\n"
            "Date: 20/05/2024\n"
            "Grand Total: ₹50,000.00\n"
        )
        table = [
            ["Description", "Qty", "Unit", "Rate", "Amount"],
            ["Sand", "20", "Cum", "2500", "50000"],
        ]
        page = _make_mock_page(header_text, [table])
        mock_pdf = _make_mock_pdf([page])

        with patch("backend.app.parsers.pdf_digital_parser.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            result = parser.parse(Path("test.pdf"), doc_id)

        assert result.header.total_amount == Decimal("50000")
