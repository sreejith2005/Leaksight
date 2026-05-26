"""
LeakSight V1 — Digital PDF Parser

Source: docs/PARSING_SPEC.md (Section 5.2 — Digital PDF Parser)
       docs/ARCHITECTURE.md (Section 6.6 — Parsing Layer)

Handles text-based PDF files using pdfplumber (primary) and camelot (fallback).
Accuracy target: ≥ 85%.

Key behaviors:
  - Extract text and tables via pdfplumber first
  - Fall back to camelot (lattice, then stream) if pdfplumber tables are poor
  - Regex-based header parsing for vendor, doc number, date
  - Multi-page table concatenation
  - Footer/noise removal
  - Never crash on malformed files
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import pdfplumber

from backend.app.core.logging import get_logger
from backend.app.parsers.base_parser import (
    BaseParser,
    DocType,
    DocumentHeader,
    FailureFlag,
    LineItem,
    ParseResult,
)

logger = get_logger(__name__)

# ── Regex patterns for header extraction ──────────────────────────
_VENDOR_PATTERNS = [
    re.compile(
        r"(?:vendor|supplier|party|from|bill\s*(?:to|from)|ship\s*from)"
        r"\s*[:\-]?\s*(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"^M/s\.?\s+(.+)", re.IGNORECASE | re.MULTILINE),
]

_DOC_NUMBER_PATTERNS = [
    re.compile(
        r"(?:invoice|inv|bill)\s*(?:no|number|#|num)\.?\s*[:\-]?\s*(\S+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:po|purchase\s*order)\s*(?:no|number|#|num)\.?\s*[:\-]?\s*(\S+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:grn|goods\s*receipt)\s*(?:no|number|#|num)\.?\s*[:\-]?\s*(\S+)",
        re.IGNORECASE,
    ),
]

_DATE_PATTERNS = [
    re.compile(
        r"(?:date|invoice\s*date|po\s*date|grn\s*date|dated)"
        r"\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:date|invoice\s*date|po\s*date|grn\s*date|dated)"
        r"\s*[:\-]?\s*(\d{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s*\d{2,4})",
        re.IGNORECASE,
    ),
]

_TOTAL_PATTERNS = [
    re.compile(
        r"(?:grand\s*total|total\s*amount|net\s*amount|total)"
        r"\s*[:\-]?\s*[₹$€£]?\s*([\d,]+\.?\d*)",
        re.IGNORECASE,
    ),
]

_GST_PATTERN = re.compile(
    r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2})\b"
)

_CURRENCY_STRIP = re.compile(r"[₹$€£¥,\s]")

# Header keywords for table header detection
_TABLE_HEADER_KEYWORDS = {
    "item", "description", "desc", "particular", "particulars",
    "quantity", "qty", "unit", "uom",
    "price", "rate", "amount", "total", "value",
    "sl", "sr", "no", "sno",
}

# Footer patterns to ignore
_FOOTER_PATTERNS = [
    re.compile(r"page\s*\d+\s*(?:of\s*\d+)?", re.IGNORECASE),
    re.compile(r"thank\s*you\s*for\s*your\s*business", re.IGNORECASE),
    re.compile(r"bank\s*(?:details|account|name)", re.IGNORECASE),
    re.compile(r"terms\s*(?:and|&)\s*conditions", re.IGNORECASE),
    re.compile(r"authorized\s*sign", re.IGNORECASE),
]

# Column mapping patterns (same as excel_parser)
_ITEM_DESC_PATTERNS = re.compile(
    r"(item|desc|particular|product|service|material|name)", re.IGNORECASE
)
_QUANTITY_PATTERNS = re.compile(r"(qty|quantity|quant|nos)", re.IGNORECASE)
_UNIT_PATTERNS = re.compile(r"(unit|uom|measure)", re.IGNORECASE)
_UNIT_PRICE_PATTERNS = re.compile(
    r"(rate|unit.?price|price|per.?unit)", re.IGNORECASE
)
_LINE_TOTAL_PATTERNS = re.compile(
    r"(amount|total|value|line.?total|net.?amount)", re.IGNORECASE
)


def _parse_numeric(value: Any) -> Decimal | None:
    """Parse a value to Decimal, handling currency symbols and commas."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = _CURRENCY_STRIP.sub("", s)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_date_value(value: str) -> date | None:
    """Try to parse a date from various formats."""
    s = value.strip()
    if not s:
        return None
    for fmt in (
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%m/%d/%Y",
        "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
        "%d/%m/%y", "%d-%m-%y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _is_footer_line(text: str) -> bool:
    """Check if a text line is a footer/noise pattern."""
    return any(p.search(text) for p in _FOOTER_PATTERNS)


def _map_table_columns(headers: list[str]) -> dict[str, int | None]:
    """Map table column headers to schema field indices."""
    mapping: dict[str, int | None] = {
        "item_desc": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "line_total": None,
    }

    for idx, col in enumerate(headers):
        if col is None:
            continue
        col_lower = str(col).strip().lower()
        if mapping["item_desc"] is None and _ITEM_DESC_PATTERNS.search(col_lower):
            mapping["item_desc"] = idx
        elif mapping["quantity"] is None and _QUANTITY_PATTERNS.search(col_lower):
            mapping["quantity"] = idx
        elif mapping["unit"] is None and _UNIT_PATTERNS.search(col_lower):
            mapping["unit"] = idx
        elif mapping["unit_price"] is None and _UNIT_PRICE_PATTERNS.search(col_lower):
            mapping["unit_price"] = idx
        elif mapping["line_total"] is None and _LINE_TOTAL_PATTERNS.search(col_lower):
            mapping["line_total"] = idx

    return mapping


def _is_table_header_row(row: list[str | None]) -> bool:
    """Check if a table row looks like a header row."""
    if not row:
        return False
    values = [str(v).strip().lower() for v in row if v is not None and str(v).strip()]
    score = sum(
        1 for v in values
        if v in _TABLE_HEADER_KEYWORDS or any(kw in v for kw in _TABLE_HEADER_KEYWORDS)
    )
    return score >= 2


class DigitalPdfParser(BaseParser):
    """Parser for text-based (digital) PDF files.

    Uses pdfplumber for text/table extraction with camelot as fallback
    for complex tables.
    """

    @property
    def supported_formats(self) -> list[str]:
        return [".pdf"]

    @property
    def parser_name(self) -> str:
        return "pdf_digital_parser_v1"

    def parse(self, file_path: Path, document_id: UUID) -> ParseResult:
        """Parse a digital PDF into the normalized intermediate schema."""
        failure_flags: list[FailureFlag] = []
        line_items: list[LineItem] = []
        header = DocumentHeader()
        confidence = 1.0
        raw_data: dict = {}
        used_camelot = False

        try:
            with pdfplumber.open(str(file_path)) as pdf:
                raw_data["page_count"] = len(pdf.pages)

                # ── Extract header text from first page ───────────
                if pdf.pages:
                    first_page = pdf.pages[0]
                    full_text = first_page.extract_text() or ""
                    # Use first 1/3 of page text for header info
                    lines = full_text.split("\n")
                    header_lines = lines[:max(len(lines) // 3, 5)]
                    header_text = "\n".join(header_lines)
                    header = self._extract_header_info(header_text, failure_flags)
                    raw_data["header_text_lines"] = len(header_lines)

                # ── Extract tables from all pages ─────────────────
                all_tables = self._extract_tables_pdfplumber(pdf)

                # Check if pdfplumber tables are usable
                if not all_tables or all(len(t) <= 1 for t in all_tables):
                    # Fall back to camelot
                    camelot_tables = self._extract_tables_camelot(file_path)
                    if camelot_tables:
                        all_tables = camelot_tables
                        used_camelot = True
                        failure_flags.append(FailureFlag(
                            severity="INFO",
                            code="TABLE_EXTRACTION_FALLBACK",
                            message="Used camelot fallback for table extraction",
                        ))
                        confidence -= 0.10

                raw_data["table_count"] = len(all_tables)
                raw_data["used_camelot"] = used_camelot

                # ── Parse tables into line items ──────────────────
                for table in all_tables:
                    items = self._parse_table(table, len(line_items), failure_flags)
                    line_items.extend(items)

                # multi-page table detection
                if raw_data.get("page_count", 1) > 1 and len(all_tables) > 1:
                    # Check if tables on adjacent pages share column structure
                    # (simplified: just flag it)
                    failure_flags.append(FailureFlag(
                        severity="INFO",
                        code="MULTI_PAGE_TABLE_CONCATENATED",
                        message="Tables from multiple pages were concatenated",
                    ))
                    confidence -= 0.05

        except Exception as exc:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="CORRUPTED_FILE",
                message=f"Failed to parse PDF: {type(exc).__name__}",
            ))
            confidence = 0.0
            return ParseResult(
                document_id=document_id,
                doc_type=DocType.INVOICE,
                parser_used=self.parser_name,
                parser_version="1.0.0",
                parse_confidence=0.0,
                header=header,
                line_items=[],
                failure_flags=failure_flags,
                raw_extracted_data=raw_data,
            )

        # ── Confidence adjustments ────────────────────────────
        if not line_items:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="MISSING_LINE_ITEMS",
                message="No line items could be extracted from the PDF",
            ))
            confidence = max(confidence - 0.40, 0.0)
        else:
            incomplete_count = sum(
                1 for li in line_items
                if li.unit_price is None or li.quantity is None
            )
            deduction = min(incomplete_count * 0.02, 0.30)
            confidence -= deduction
            if incomplete_count > 0:
                failure_flags.append(FailureFlag(
                    severity="WARNING",
                    code="MISSING_UNIT_PRICE",
                    message=f"{incomplete_count} line items have missing required fields",
                ))

        if header.document_date is None:
            # Check if date ambiguity issue
            confidence -= 0.05

        confidence = max(round(confidence, 4), 0.0)

        return ParseResult(
            document_id=document_id,
            doc_type=DocType.INVOICE,
            parser_used=self.parser_name,
            parser_version="1.0.0",
            parse_confidence=confidence,
            header=header,
            line_items=line_items,
            failure_flags=failure_flags,
            raw_extracted_data=raw_data,
        )

    def _extract_header_info(
        self, text: str, failure_flags: list[FailureFlag]
    ) -> DocumentHeader:
        """Extract vendor, date, doc number, total, GST from header text."""
        header = DocumentHeader()

        # Vendor name
        for pattern in _VENDOR_PATTERNS:
            match = pattern.search(text)
            if match:
                header.vendor_name = match.group(1).strip()
                break

        # Document number
        for pattern in _DOC_NUMBER_PATTERNS:
            match = pattern.search(text)
            if match:
                header.document_number = match.group(1).strip()
                break

        if header.document_number is None:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="MISSING_DOCUMENT_NUMBER",
                message="Invoice/PO/GRN number could not be extracted",
            ))

        # Date
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text)
            if match:
                header.document_date = _parse_date_value(match.group(1))
                break

        if header.document_date is None:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="MISSING_DOCUMENT_DATE",
                message="Document date could not be extracted",
            ))

        # Total amount
        for pattern in _TOTAL_PATTERNS:
            match = pattern.search(text)
            if match:
                header.total_amount = _parse_numeric(match.group(1))
                break

        # GST ID
        gst_match = _GST_PATTERN.search(text)
        if gst_match:
            header.vendor_gst_id = gst_match.group(1)

        # Vendor name warning
        if header.vendor_name is None:
            failure_flags.append(FailureFlag(
                severity="WARNING",
                code="MISSING_VENDOR_NAME",
                message="Vendor name not found in document",
            ))

        return header

    def _extract_tables_pdfplumber(self, pdf: Any) -> list[list[list[str | None]]]:
        """Extract tables from all pages using pdfplumber."""
        all_tables: list[list[list[str | None]]] = []
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    # Filter out empty/noise rows
                    clean_table = [
                        row for row in table
                        if row and any(
                            cell is not None and str(cell).strip()
                            for cell in row
                        )
                    ]
                    if clean_table:
                        all_tables.append(clean_table)
        return all_tables

    def _extract_tables_camelot(
        self, file_path: Path
    ) -> list[list[list[str | None]]]:
        """Extract tables using camelot as fallback."""
        try:
            import camelot

            all_tables: list[list[list[str | None]]] = []

            # Try lattice first (bordered tables)
            tables = camelot.read_pdf(
                str(file_path), flavor="lattice", pages="all"
            )
            if tables and len(tables) > 0:
                for t in tables:
                    df = t.df
                    table_data = df.values.tolist()
                    if table_data:
                        all_tables.append(table_data)
                return all_tables

            # Fall back to stream (borderless tables)
            tables = camelot.read_pdf(
                str(file_path), flavor="stream", pages="all"
            )
            if tables and len(tables) > 0:
                for t in tables:
                    df = t.df
                    table_data = df.values.tolist()
                    if table_data:
                        all_tables.append(table_data)

            return all_tables
        except Exception:
            return []

    def _parse_table(
        self,
        table: list[list[str | None]],
        offset: int,
        failure_flags: list[FailureFlag],
    ) -> list[LineItem]:
        """Parse a table (list of rows) into line items."""
        if not table:
            return []

        # Find header row
        header_idx = None
        for idx, row in enumerate(table):
            if _is_table_header_row(row):
                header_idx = idx
                break

        if header_idx is None:
            # Use first row as header
            header_idx = 0

        headers = [str(v) if v else "" for v in table[header_idx]]
        col_mapping = _map_table_columns(headers)

        items: list[LineItem] = []
        for row_idx, row in enumerate(table[header_idx + 1:], start=1):
            # Skip footer rows
            row_text = " ".join(str(v) for v in row if v)
            if _is_footer_line(row_text):
                continue

            # Skip completely empty rows
            if not any(v is not None and str(v).strip() for v in row):
                continue

            item = self._extract_line_item_from_row(
                row, col_mapping, offset + row_idx
            )
            if item is not None:
                items.append(item)

        return items

    def _extract_line_item_from_row(
        self,
        row: list[str | None],
        col_mapping: dict[str, int | None],
        line_number: int,
    ) -> LineItem | None:
        """Extract a single line item from a table row."""
        item_desc = None
        if col_mapping["item_desc"] is not None and col_mapping["item_desc"] < len(row):
            val = row[col_mapping["item_desc"]]
            if val and str(val).strip():
                item_desc = str(val).strip()

        if not item_desc:
            return None

        quantity = None
        if col_mapping["quantity"] is not None and col_mapping["quantity"] < len(row):
            quantity = _parse_numeric(row[col_mapping["quantity"]])

        unit = None
        if col_mapping["unit"] is not None and col_mapping["unit"] < len(row):
            val = row[col_mapping["unit"]]
            if val and str(val).strip():
                unit = str(val).strip()

        unit_price = None
        if col_mapping["unit_price"] is not None and col_mapping["unit_price"] < len(row):
            unit_price = _parse_numeric(row[col_mapping["unit_price"]])

        line_total = None
        if col_mapping["line_total"] is not None and col_mapping["line_total"] < len(row):
            line_total = _parse_numeric(row[col_mapping["line_total"]])

        # Calculate line_total if missing
        if line_total is None and quantity is not None and unit_price is not None:
            line_total = quantity * unit_price

        field_confidences: dict[str, float] = {}
        if item_desc:
            field_confidences["item_desc"] = 1.0
        if quantity is not None:
            field_confidences["quantity"] = 1.0
        if unit_price is not None:
            field_confidences["unit_price"] = 1.0
        if line_total is not None:
            field_confidences["line_total"] = 1.0

        return LineItem(
            line_number=line_number,
            item_desc=item_desc,
            quantity=quantity,
            unit=unit,
            unit_price=unit_price,
            line_total=line_total,
            ordered_qty=None,
            received_qty=None,
            field_confidences=field_confidences,
        )
