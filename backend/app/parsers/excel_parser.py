"""
LeakSight V1 — Excel and CSV Parser

Source: docs/PARSING_SPEC.md (Section 5.1 — Excel/CSV Parser),
       docs/ARCHITECTURE.md (Section 6.6 — Parsing Layer)

Handles XLSX, XLS, and CSV formats using pandas and openpyxl.
Accuracy target: ≥ 95%.

Key behaviors:
  - Auto-detect header row by scanning first 10 rows for keywords
  - Map detected columns to ParseResult line items
  - Never crash on malformed files — catch all exceptions
  - No silent drops — every issue becomes a failure_flag
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

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

# Keywords for header row detection (case-insensitive)
HEADER_KEYWORDS: set[str] = {
    "item", "description", "desc", "particular", "particulars",
    "quantity", "qty", "unit", "uom",
    "price", "rate", "amount", "total", "value",
    "sl", "sr", "no", "sno", "s.no",
}

# Column name mappings for schema fields
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
_ORDERED_QTY_PATTERNS = re.compile(r"(ordered|order.?qty)", re.IGNORECASE)
_RECEIVED_QTY_PATTERNS = re.compile(r"(received|recv|rcvd)", re.IGNORECASE)

# Vendor name patterns in header area
_VENDOR_PATTERNS = re.compile(
    r"(?:vendor|supplier|party|bill\s*to|ship\s*from)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_DATE_PATTERNS = re.compile(
    r"(?:date|invoice\s*date|po\s*date|grn\s*date)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_DOC_NUMBER_PATTERNS = re.compile(
    r"(?:invoice\s*(?:no|number|#)|po\s*(?:no|number|#)|grn\s*(?:no|number|#))\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)

# Currency symbols
_CURRENCY_STRIP = re.compile(r"[₹$€£¥,\s]")


def _parse_numeric(value: Any) -> Decimal | None:
    """Parse a value to Decimal, handling currency symbols and commas."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    # Strip currency symbols and commas
    s = _CURRENCY_STRIP.sub("", s)
    # Handle parentheses for negative numbers
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_date_value(value: Any) -> date | None:
    """Try to parse a date from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Try common date formats (prefer DD/MM/YYYY per Indian convention)
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


def _detect_header_row(df: pd.DataFrame, max_scan: int = 10) -> int | None:
    """Scan first max_scan rows to find the header row.

    Returns the row index (0-based) that contains the most header keywords,
    or None if no suitable header row is found.
    """
    best_row = None
    best_score = 0

    rows_to_scan = min(max_scan, len(df))
    for idx in range(rows_to_scan):
        row_values = [str(v).strip().lower() for v in df.iloc[idx] if pd.notna(v)]
        score = sum(1 for v in row_values if v in HEADER_KEYWORDS or
                    any(kw in v for kw in HEADER_KEYWORDS))
        if score > best_score:
            best_score = score
            best_row = idx

    # Require at least 2 keyword matches to be a header
    return best_row if best_score >= 2 else None


def _map_columns(
    columns: list[str],
) -> dict[str, str | None]:
    """Map detected column names to schema field names.

    Returns dict mapping: schema_field -> column_name
    """
    mapping: dict[str, str | None] = {
        "item_desc": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "line_total": None,
        "ordered_qty": None,
        "received_qty": None,
    }

    for col in columns:
        col_lower = col.strip().lower()
        if mapping["item_desc"] is None and _ITEM_DESC_PATTERNS.search(col_lower):
            mapping["item_desc"] = col
        elif mapping["quantity"] is None and _QUANTITY_PATTERNS.search(col_lower):
            mapping["quantity"] = col
        elif mapping["unit"] is None and _UNIT_PATTERNS.search(col_lower):
            mapping["unit"] = col
        elif mapping["unit_price"] is None and _UNIT_PRICE_PATTERNS.search(col_lower):
            mapping["unit_price"] = col
        elif mapping["line_total"] is None and _LINE_TOTAL_PATTERNS.search(col_lower):
            mapping["line_total"] = col
        elif mapping["ordered_qty"] is None and _ORDERED_QTY_PATTERNS.search(col_lower):
            mapping["ordered_qty"] = col
        elif mapping["received_qty"] is None and _RECEIVED_QTY_PATTERNS.search(col_lower):
            mapping["received_qty"] = col

    return mapping


class ExcelParser(BaseParser):
    """Parser for Excel (XLSX, XLS) and CSV files.

    Uses pandas for data reading and openpyxl for XLSX format.
    Auto-detects header rows and maps columns to the normalized schema.
    """

    @property
    def supported_formats(self) -> list[str]:
        return [".xlsx", ".xls", ".csv"]

    @property
    def parser_name(self) -> str:
        return "excel_parser_v1"

    def parse(self, file_path: Path, document_id: UUID) -> ParseResult:
        """Parse an Excel or CSV file into the normalized intermediate schema.

        Args:
            file_path: Path to the Excel/CSV file.
            document_id: UUID of the document record.

        Returns:
            ParseResult with extracted data and confidence score.
        """
        failure_flags: list[FailureFlag] = []
        line_items: list[LineItem] = []
        header = DocumentHeader()
        confidence = 1.0
        raw_data: dict = {}

        try:
            ext = file_path.suffix.lower()
            df = self._read_file(file_path, ext, failure_flags)

            if df is None or df.empty:
                failure_flags.append(FailureFlag(
                    severity="ERROR",
                    code="EMPTY_FILE",
                    message="File contains no data",
                ))
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

            # Store raw shape for debugging
            raw_data["original_shape"] = list(df.shape)

            # ── Detect header row ──────────────────────────────────
            header_row_idx = _detect_header_row(df)
            header_detected = header_row_idx is not None

            if header_detected:
                # Re-read with detected header row
                new_columns = [str(v) for v in df.iloc[header_row_idx]]
                data_start = header_row_idx + 1
                df_data = df.iloc[data_start:].copy()
                df_data.columns = new_columns[:len(df_data.columns)]
            else:
                failure_flags.append(FailureFlag(
                    severity="WARNING",
                    code="HEADER_ROW_NOT_DETECTED",
                    message="Table header row was not auto-detected",
                ))
                confidence -= 0.10
                df_data = df
                new_columns = [str(c) for c in df_data.columns]

            # ── Extract header info from pre-data rows ─────────────
            if header_row_idx is not None and header_row_idx > 0:
                header_text_rows = df.iloc[:header_row_idx]
                header = self._extract_header_info(header_text_rows)

            # ── Map columns ────────────────────────────────────────
            col_mapping = _map_columns(new_columns)
            raw_data["column_mapping"] = {k: v for k, v in col_mapping.items() if v}

            # ── Extract line items ─────────────────────────────────
            for row_idx, (_, row) in enumerate(df_data.iterrows(), start=1):
                item = self._extract_line_item(row, col_mapping, row_idx)
                if item is not None:
                    line_items.append(item)

            # ── Calculate confidence ───────────────────────────────
            if not line_items:
                failure_flags.append(FailureFlag(
                    severity="ERROR",
                    code="MISSING_LINE_ITEMS",
                    message="No line items could be extracted from the document",
                ))
                confidence = max(confidence - 0.40, 0.0)
            else:
                # Deduct for incomplete line items
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

            confidence = max(confidence, 0.0)

        except Exception as exc:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="CORRUPTED_FILE",
                message=f"Failed to parse file: {type(exc).__name__}",
            ))
            confidence = 0.0

        return ParseResult(
            document_id=document_id,
            doc_type=DocType.INVOICE,
            parser_used=self.parser_name,
            parser_version="1.0.0",
            parse_confidence=round(confidence, 4),
            header=header,
            line_items=line_items,
            failure_flags=failure_flags,
            raw_extracted_data=raw_data,
        )

    def _read_file(
        self,
        file_path: Path,
        ext: str,
        failure_flags: list[FailureFlag],
    ) -> pd.DataFrame | None:
        """Read file into a DataFrame based on extension."""
        try:
            if ext == ".csv":
                try:
                    return pd.read_csv(file_path, header=None, encoding="utf-8")
                except UnicodeDecodeError:
                    return pd.read_csv(file_path, header=None, encoding="latin-1")
            elif ext in (".xlsx", ".xls"):
                return pd.read_excel(
                    file_path,
                    header=None,
                    engine="openpyxl" if ext == ".xlsx" else None,
                )
            return None
        except Exception as exc:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="CORRUPTED_FILE",
                message=f"Cannot read file: {type(exc).__name__}",
            ))
            return None

    def _extract_header_info(self, header_rows: pd.DataFrame) -> DocumentHeader:
        """Extract vendor, date, doc number from pre-header rows."""
        header = DocumentHeader()

        for _, row in header_rows.iterrows():
            for val in row:
                if pd.isna(val):
                    continue
                text = str(val).strip()
                if not text:
                    continue

                # Try vendor
                vendor_match = _VENDOR_PATTERNS.search(text)
                if vendor_match and header.vendor_name is None:
                    header.vendor_name = vendor_match.group(1).strip()

                # Try date
                date_match = _DATE_PATTERNS.search(text)
                if date_match and header.document_date is None:
                    header.document_date = _parse_date_value(date_match.group(1).strip())

                # Try doc number
                num_match = _DOC_NUMBER_PATTERNS.search(text)
                if num_match and header.document_number is None:
                    header.document_number = num_match.group(1).strip()

        return header

    def _extract_line_item(
        self,
        row: pd.Series,
        col_mapping: dict[str, str | None],
        line_number: int,
    ) -> LineItem | None:
        """Extract a single line item from a DataFrame row."""
        # Skip completely empty rows
        if all(pd.isna(v) for v in row.values):
            return None

        item_desc = None
        if col_mapping["item_desc"] and col_mapping["item_desc"] in row.index:
            val = row[col_mapping["item_desc"]]
            if pd.notna(val):
                item_desc = str(val).strip()

        # Skip rows with no item description (likely subtotal/footer)
        if not item_desc:
            return None

        quantity = None
        if col_mapping["quantity"] and col_mapping["quantity"] in row.index:
            quantity = _parse_numeric(row[col_mapping["quantity"]])

        unit = None
        if col_mapping["unit"] and col_mapping["unit"] in row.index:
            val = row[col_mapping["unit"]]
            if pd.notna(val):
                unit = str(val).strip()

        unit_price = None
        if col_mapping["unit_price"] and col_mapping["unit_price"] in row.index:
            unit_price = _parse_numeric(row[col_mapping["unit_price"]])

        line_total = None
        if col_mapping["line_total"] and col_mapping["line_total"] in row.index:
            line_total = _parse_numeric(row[col_mapping["line_total"]])

        # Calculate line_total if missing but quantity and price are present
        if line_total is None and quantity is not None and unit_price is not None:
            line_total = quantity * unit_price

        ordered_qty = None
        if col_mapping["ordered_qty"] and col_mapping["ordered_qty"] in row.index:
            ordered_qty = _parse_numeric(row[col_mapping["ordered_qty"]])

        received_qty = None
        if col_mapping["received_qty"] and col_mapping["received_qty"] in row.index:
            received_qty = _parse_numeric(row[col_mapping["received_qty"]])

        # Build field confidences
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
            ordered_qty=ordered_qty,
            received_qty=received_qty,
            field_confidences=field_confidences,
        )
