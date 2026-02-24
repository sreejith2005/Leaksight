"""
Tests for Parser Router — backend/app/parsers/parser_router.py

Governing doc: docs/PARSING_SPEC.md §3

Covers:
  1. Extension routing — xlsx, xls, csv, docx → correct parser
  2. PDF routing — digital vs scanned detection
  3. Unsupported format — raises UnsupportedFormatError
  4. Ambiguous PDF detection — DETECTION_AMBIGUOUS flag
  5. parse_document integration — end-to-end routing
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.parsers.base_parser import DocType, UnsupportedFormatError
from backend.app.parsers.excel_parser import ExcelParser
from backend.app.parsers.pdf_digital_parser import DigitalPdfParser
from backend.app.parsers.pdf_scanned_parser import ScannedPdfParser
from backend.app.parsers.word_parser import WordParser
from backend.app.parsers.parser_router import (
    get_parser,
    is_scanned_pdf,
    parse_document,
    SUPPORTED_EXTENSIONS,
)


class TestExtensionRouting:
    """Test that non-PDF files route to the correct parser by extension."""

    def test_xlsx_routes_to_excel(self):
        parser = get_parser(Path("invoice.xlsx"))
        assert isinstance(parser, ExcelParser)

    def test_xls_routes_to_excel(self):
        parser = get_parser(Path("invoice.xls"))
        assert isinstance(parser, ExcelParser)

    def test_csv_routes_to_excel(self):
        parser = get_parser(Path("data.csv"))
        assert isinstance(parser, ExcelParser)

    def test_docx_routes_to_word(self):
        parser = get_parser(Path("contract.docx"))
        assert isinstance(parser, WordParser)

    def test_case_insensitive(self):
        parser = get_parser(Path("invoice.XLSX"))
        assert isinstance(parser, ExcelParser)


class TestPdfRouting:
    """Test PDF digital vs scanned detection and routing."""

    def test_digital_pdf_routes_to_digital_parser(self):
        with patch("backend.app.parsers.parser_router.is_scanned_pdf", return_value=False):
            parser = get_parser(Path("invoice.pdf"))
        assert isinstance(parser, DigitalPdfParser)

    def test_scanned_pdf_routes_to_scanned_parser(self):
        with patch("backend.app.parsers.parser_router.is_scanned_pdf", return_value=True):
            parser = get_parser(Path("scan.pdf"))
        assert isinstance(parser, ScannedPdfParser)


class TestIsScannedPdf:
    """Test the is_scanned_pdf detection logic."""

    def test_text_rich_pdf_is_digital(self):
        """PDF with ≥ 50 chars in first 3 pages → digital."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 100  # Well above threshold
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("backend.app.parsers.parser_router.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            assert is_scanned_pdf(Path("text.pdf")) is False

    def test_text_empty_pdf_is_scanned(self):
        """PDF with < 50 chars in first 3 pages → scanned."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 10  # Below threshold
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("backend.app.parsers.parser_router.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.return_value = mock_pdf
            assert is_scanned_pdf(Path("scan.pdf")) is True

    def test_corrupt_pdf_defaults_to_digital(self):
        """If PDF can't be opened, default to digital parser."""
        with patch("backend.app.parsers.parser_router.pdfplumber") as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("Bad PDF")
            assert is_scanned_pdf(Path("bad.pdf")) is False


class TestUnsupportedFormat:
    """Test that unsupported extensions raise UnsupportedFormatError."""

    def test_txt_raises_error(self):
        with pytest.raises(UnsupportedFormatError):
            get_parser(Path("notes.txt"))

    def test_jpg_raises_error(self):
        with pytest.raises(UnsupportedFormatError):
            get_parser(Path("image.jpg"))

    def test_no_extension_raises_error(self):
        with pytest.raises(UnsupportedFormatError):
            get_parser(Path("noext"))


class TestSupportedExtensions:
    """Verify the supported extensions set."""

    def test_all_expected_extensions(self):
        expected = {".xlsx", ".xls", ".csv", ".pdf", ".docx"}
        assert SUPPORTED_EXTENSIONS == expected


class TestParseDocument:
    """Test the parse_document integration function."""

    def test_routes_and_parses_excel(self):
        doc_id = uuid4()
        fixture_path = Path(__file__).parent / "fixtures" / "clean_invoice.xlsx"
        if not fixture_path.exists():
            pytest.skip("Fixture not available")

        result = parse_document(fixture_path, doc_id, DocType.INVOICE)
        assert result.document_id == doc_id
        assert result.doc_type == DocType.INVOICE
        assert result.parse_confidence > 0.0

    def test_routes_and_parses_csv(self):
        doc_id = uuid4()
        fixture_path = Path(__file__).parent / "fixtures" / "clean_invoice.csv"
        if not fixture_path.exists():
            pytest.skip("Fixture not available")

        result = parse_document(fixture_path, doc_id, DocType.INVOICE)
        assert result.document_id == doc_id
        assert result.parse_confidence > 0.0

    def test_unsupported_format_raises(self):
        doc_id = uuid4()
        with pytest.raises(UnsupportedFormatError):
            parse_document(Path("file.bmp"), doc_id)
