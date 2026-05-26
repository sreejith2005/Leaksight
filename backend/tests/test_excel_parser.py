"""
Tests for ExcelParser — backend/app/parsers/excel_parser.py

Governing doc: docs/PARSING_SPEC.md §5.1

Covers:
  1. Clean XLSX — ≥ 0.95 confidence, all 5 line items extracted
  2. Clean CSV  — ≥ 0.95 confidence, all 3 line items extracted
  3. Header at row 3 — header info extracted, confidence ≥ 0.90
  4. Merged cells with currency symbols — numeric parsing works
  5. Malformed file — no crash, confidence 0.0, CORRUPTED_FILE flag
"""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.parsers.excel_parser import ExcelParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser():
    return ExcelParser()


@pytest.fixture
def doc_id():
    return uuid4()


class TestCleanExcel:
    def test_confidence_above_95(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.xlsx", doc_id)
        assert result.parse_confidence >= 0.95, (
            f"Expected ≥ 0.95 but got {result.parse_confidence}"
        )

    def test_extracts_all_line_items(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.xlsx", doc_id)
        assert len(result.line_items) == 5

    def test_first_item_values(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.xlsx", doc_id)
        item = result.line_items[0]
        assert item.item_desc == "Cement OPC 53 Grade"
        assert item.quantity == Decimal("100")
        assert item.unit == "Bags"
        assert item.unit_price == Decimal("350")
        assert item.line_total == Decimal("35000")

    def test_parser_metadata(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.xlsx", doc_id)
        assert result.parser_used == "excel_parser_v1"
        assert result.document_id == doc_id


class TestCleanCSV:
    def test_confidence_above_95(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.csv", doc_id)
        assert result.parse_confidence >= 0.95, (
            f"Expected ≥ 0.95 but got {result.parse_confidence}"
        )

    def test_extracts_all_line_items(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.csv", doc_id)
        assert len(result.line_items) == 3

    def test_line_item_values(self, parser, doc_id):
        result = parser.parse(FIXTURES / "clean_invoice.csv", doc_id)
        item = result.line_items[0]
        assert item.item_desc == "Cement PPC"
        assert item.quantity == Decimal("200")


class TestHeaderOnRow3:
    def test_confidence_above_90(self, parser, doc_id):
        result = parser.parse(FIXTURES / "header_row3.xlsx", doc_id)
        assert result.parse_confidence >= 0.90, (
            f"Expected ≥ 0.90 but got {result.parse_confidence}"
        )

    def test_extracts_vendor_name(self, parser, doc_id):
        result = parser.parse(FIXTURES / "header_row3.xlsx", doc_id)
        assert result.header.vendor_name == "ABC Suppliers Pvt Ltd"

    def test_extracts_doc_number(self, parser, doc_id):
        result = parser.parse(FIXTURES / "header_row3.xlsx", doc_id)
        assert result.header.document_number == "INV-2024-0451"

    def test_extracts_line_items(self, parser, doc_id):
        result = parser.parse(FIXTURES / "header_row3.xlsx", doc_id)
        assert len(result.line_items) == 2
        assert result.line_items[0].item_desc == "20mm Aggregate"


class TestMergedCells:
    def test_handles_currency_symbols(self, parser, doc_id):
        result = parser.parse(FIXTURES / "merged_cells.xlsx", doc_id)
        assert len(result.line_items) >= 1
        item = result.line_items[0]
        assert item.unit_price == Decimal("380")

    def test_extracts_vendor_from_merged(self, parser, doc_id):
        result = parser.parse(FIXTURES / "merged_cells.xlsx", doc_id)
        assert result.header.vendor_name == "XYZ Materials"

    def test_no_crash(self, parser, doc_id):
        result = parser.parse(FIXTURES / "merged_cells.xlsx", doc_id)
        assert result.parse_confidence > 0.0


class TestMalformedFile:
    def test_no_crash(self, parser, doc_id):
        result = parser.parse(FIXTURES / "malformed.xlsx", doc_id)
        assert result is not None

    def test_zero_confidence(self, parser, doc_id):
        result = parser.parse(FIXTURES / "malformed.xlsx", doc_id)
        assert result.parse_confidence == 0.0

    def test_corrupted_flag(self, parser, doc_id):
        result = parser.parse(FIXTURES / "malformed.xlsx", doc_id)
        codes = [f.code for f in result.failure_flags]
        assert "CORRUPTED_FILE" in codes

    def test_no_line_items(self, parser, doc_id):
        result = parser.parse(FIXTURES / "malformed.xlsx", doc_id)
        assert len(result.line_items) == 0
