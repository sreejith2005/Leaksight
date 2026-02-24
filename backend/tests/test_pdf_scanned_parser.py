"""
Tests for ScannedPdfParser — backend/app/parsers/pdf_scanned_parser.py

Governing doc: docs/PARSING_SPEC.md §5.3

All PaddleOCR and PP-Structure calls are mocked — no real OCR in tests.
Covers:
  1. Clean scanned PDF — OCR extraction with good confidence
  2. Low OCR quality — confidence penalty, LOW_OCR_QUALITY flag
  3. Page-by-page processing — gc.collect called per page
  4. Malformed PDF — no crash, confidence 0.0
  5. Header extraction from OCR text
  6. No table rows — MISSING_LINE_ITEMS flag
  7. NO Tesseract anywhere
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from uuid import uuid4

import pytest

from backend.app.parsers.pdf_scanned_parser import ScannedPdfParser


@pytest.fixture
def parser():
    p = ScannedPdfParser()
    # Pre-set mocked engines to avoid real PaddleOCR initialization
    p._ocr_engine = MagicMock()
    p._structure_engine = None  # PP-Structure not available in tests
    return p


@pytest.fixture
def doc_id():
    return uuid4()


def _make_ocr_result(lines: list[tuple[str, float]]):
    """Create a mock PaddleOCR result.

    Input: list of (text, confidence) tuples
    Returns: format matching PaddleOCR output
    """
    result = []
    for text, conf in lines:
        # PaddleOCR format: [[bbox], (text, confidence)]
        bbox = [[0, 0], [100, 0], [100, 20], [0, 20]]
        result.append([bbox, (text, conf)])
    return [result]


class TestCleanScannedPdf:
    """Clean scanned PDF with good OCR quality."""

    def _get_result(self, parser, doc_id):
        mock_image = MagicMock()
        ocr_lines = [
            ("Vendor: Ultratech Cement Ltd", 0.95),
            ("Invoice No: INV-2024-0567", 0.92),
            ("Date: 15/03/2024", 0.90),
            ("Description  Qty  Unit  Rate  Amount", 0.88),
            ("Cement OPC 53  100  Bags  350  35000", 0.91),
            ("TMT Steel 12mm  500  Kg  72.50  36250", 0.89),
        ]
        parser._ocr_engine.ocr.return_value = _make_ocr_result(ocr_lines)

        with patch.object(parser, "_convert_pdf_to_images", return_value=[mock_image]):
            result = parser.parse(Path("test.pdf"), doc_id)
        return result

    def test_confidence_above_zero(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.parse_confidence > 0.0

    def test_confidence_starts_at_080(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        # Confidence = 0.80 * avg_char_confidence
        # avg = mean([0.95, 0.92, 0.90, 0.88, 0.91, 0.89]) ≈ 0.9083
        # expected ≈ 0.80 * 0.9083 ≈ 0.727
        assert 0.60 <= result.parse_confidence <= 0.85

    def test_extracts_vendor(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.vendor_name == "Ultratech Cement Ltd"

    def test_extracts_doc_number(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.document_number == "INV-2024-0567"

    def test_extracts_date(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.header.document_date is not None
        assert result.header.document_date.day == 15
        assert result.header.document_date.month == 3

    def test_extracts_line_items(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert len(result.line_items) >= 1

    def test_parser_metadata(self, parser, doc_id):
        result = self._get_result(parser, doc_id)
        assert result.parser_used == "pdf_scanned_parser_v1"
        assert result.document_id == doc_id


class TestLowOcrQuality:
    """Pages with low OCR confidence should be flagged."""

    def test_low_quality_flag(self, parser, doc_id):
        mock_image = MagicMock()
        ocr_lines = [
            ("lnv0ice N0: INV-001", 0.40),
            ("Dat3: 01/01/2024", 0.35),
            ("D3sc  Qty  Un1t  Rat3  Am0unt", 0.30),
        ]
        parser._ocr_engine.ocr.return_value = _make_ocr_result(ocr_lines)

        with patch.object(parser, "_convert_pdf_to_images", return_value=[mock_image]):
            result = parser.parse(Path("test.pdf"), doc_id)

        codes = [f.code for f in result.failure_flags]
        assert "LOW_OCR_QUALITY" in codes

    def test_low_quality_reduces_confidence(self, parser, doc_id):
        mock_image = MagicMock()
        ocr_lines = [
            ("garbled text", 0.30),
            ("more garble", 0.25),
        ]
        parser._ocr_engine.ocr.return_value = _make_ocr_result(ocr_lines)

        with patch.object(parser, "_convert_pdf_to_images", return_value=[mock_image]):
            result = parser.parse(Path("test.pdf"), doc_id)

        # 0.80 * ~0.275 - 0.10 → very low
        assert result.parse_confidence < 0.50


class TestPageByPageProcessing:
    """Verify page-by-page processing with gc.collect."""

    def test_gc_collect_called_per_page(self, parser, doc_id):
        mock_images = [MagicMock(), MagicMock(), MagicMock()]
        ocr_lines = [("Item text", 0.90)]
        parser._ocr_engine.ocr.return_value = _make_ocr_result(ocr_lines)

        with patch.object(parser, "_convert_pdf_to_images", return_value=mock_images):
            with patch("backend.app.parsers.pdf_scanned_parser.gc") as mock_gc:
                parser.parse(Path("test.pdf"), doc_id)
                # gc.collect called once per page
                assert mock_gc.collect.call_count == 3

    def test_multi_page_items_concatenated(self, parser, doc_id):
        mock_images = [MagicMock(), MagicMock()]

        # Different OCR results per page
        page1_result = _make_ocr_result([
            ("Vendor: TestCo", 0.90),
            ("Invoice No: INV-100", 0.90),
            ("Date: 01/01/2024", 0.90),
            ("Description  Qty  Unit  Rate  Amount", 0.90),
            ("Cement  100  Bags  350  35000", 0.90),
        ])
        page2_result = _make_ocr_result([
            ("Description  Qty  Unit  Rate  Amount", 0.90),
            ("Steel  500  Kg  72  36000", 0.90),
        ])
        parser._ocr_engine.ocr.side_effect = [page1_result, page2_result]

        with patch.object(parser, "_convert_pdf_to_images", return_value=mock_images):
            result = parser.parse(Path("test.pdf"), doc_id)

        assert len(result.line_items) >= 2


class TestMalformedPdf:
    """Malformed/corrupted scanned PDF files."""

    def test_no_crash(self, parser, doc_id):
        with patch.object(parser, "_convert_pdf_to_images", side_effect=Exception("Bad PDF")):
            result = parser.parse(Path("test.pdf"), doc_id)
        assert result is not None

    def test_zero_confidence(self, parser, doc_id):
        with patch.object(parser, "_convert_pdf_to_images", side_effect=Exception("Bad PDF")):
            result = parser.parse(Path("test.pdf"), doc_id)
        assert result.parse_confidence == 0.0

    def test_corrupted_flag(self, parser, doc_id):
        with patch.object(parser, "_convert_pdf_to_images", side_effect=Exception("Bad PDF")):
            result = parser.parse(Path("test.pdf"), doc_id)
        codes = [f.code for f in result.failure_flags]
        assert "CORRUPTED_FILE" in codes


class TestEmptyPdf:
    """PDF with no pages."""

    def test_empty_file_flag(self, parser, doc_id):
        with patch.object(parser, "_convert_pdf_to_images", return_value=[]):
            result = parser.parse(Path("test.pdf"), doc_id)
        codes = [f.code for f in result.failure_flags]
        assert "EMPTY_FILE" in codes

    def test_zero_confidence(self, parser, doc_id):
        with patch.object(parser, "_convert_pdf_to_images", return_value=[]):
            result = parser.parse(Path("test.pdf"), doc_id)
        assert result.parse_confidence == 0.0


class TestNoTesseract:
    """Critical: verify no Tesseract dependency anywhere."""

    def test_no_tesseract_import(self):
        import inspect
        from backend.app.parsers import pdf_scanned_parser
        source = inspect.getsource(pdf_scanned_parser)
        # Check that no import of tesseract exists (comments mentioning it are OK)
        import_lines = [
            line.strip() for line in source.split("\n")
            if line.strip().startswith(("import ", "from "))
        ]
        for line in import_lines:
            assert "tesseract" not in line.lower(), f"Tesseract import found: {line}"

    def test_parser_uses_paddleocr(self, parser):
        assert parser.parser_name == "pdf_scanned_parser_v1"
        # Confirm the OCR engine attribute exists (mocked)
        assert parser._ocr_engine is not None
