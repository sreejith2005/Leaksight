"""
LeakSight V1 - Excel and CSV Parser (FIXED for batch format)

Handles two formats:
1. Single-document format: one invoice/contract per file, vendor in pre-header rows
2. Batch format: many invoices/contracts per file, one per row with identifying columns

Batch format is auto-detected by presence of Invoice_Number/Contract_ID columns.
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
    "vendor", "invoice", "contract", "date", "currency",
}

# Column name mappings for schema fields
_ITEM_DESC_PATTERNS = re.compile(
    r"(^item$|item.?desc|item.?description|description|particular|product|service|material)", re.IGNORECASE
)
_QUANTITY_PATTERNS = re.compile(r"^(qty|quantity|quant|nos|contract.?quantity)$", re.IGNORECASE)
_UNIT_PATTERNS = re.compile(r"^(unit|uom|measure)$", re.IGNORECASE)
_UNIT_PRICE_PATTERNS = re.compile(
    r"^(rate|unit.?price|price|per.?unit)$", re.IGNORECASE
)
_LINE_TOTAL_PATTERNS = re.compile(
    r"(^amount$|^total$|^value$|line.?total|net.?amount)", re.IGNORECASE
)
_ORDERED_QTY_PATTERNS = re.compile(r"(ordered|order.?qty)", re.IGNORECASE)
_RECEIVED_QTY_PATTERNS = re.compile(r"(received|recv|rcvd)", re.IGNORECASE)

# Batch format column patterns
_INVOICE_NO_PATTERNS = re.compile(r"(invoice.?no|invoice.?num|invoice.?number|inv.?no)", re.IGNORECASE)
_CONTRACT_ID_PATTERNS = re.compile(r"(contract.?id|contract.?no|contract.?number)", re.IGNORECASE)
_VENDOR_NAME_PATTERNS = re.compile(r"^(vendor.?name|supplier.?name|vendor|supplier)$", re.IGNORECASE)
_INVOICE_DATE_PATTERNS = re.compile(r"^(invoice.?date|inv.?date)$", re.IGNORECASE)
_CURRENCY_COL_PATTERNS = re.compile(r"^(currency|curr|ccy)$", re.IGNORECASE)
_START_DATE_PATTERNS = re.compile(r"(effective.?start|start.?date|valid.?from)", re.IGNORECASE)
_END_DATE_PATTERNS = re.compile(r"(effective.?end|end.?date|valid.?to)", re.IGNORECASE)
_VERSION_NO_PATTERNS = re.compile(r"(version.?no|version.?number|ver.?no|version)", re.IGNORECASE)
_ITEM_CODE_PATTERNS = re.compile(r"(item.?code|item.?id)", re.IGNORECASE)
_PO_NO_PATTERNS = re.compile(r"(po.?no|po.?num|po.?number|purchase.?order.?no|purchase.?order.?number)", re.IGNORECASE)
_PO_DATE_PATTERNS = re.compile(r"^(po.?date|purchase.?order.?date)$", re.IGNORECASE)

# Vendor name patterns in header area (for single-doc format)
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
    if value is None or (isinstance(value, float) and pd.isna(value)):
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


def _parse_date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
        "%d/%m/%y", "%d-%m-%y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _detect_header_row(df: pd.DataFrame, max_scan: int = 10) -> int | None:
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
    return best_row if best_score >= 2 else None


def _map_columns(columns: list[str]) -> dict[str, str | None]:
    """Map column names to schema fields. Now includes batch-format columns."""
    mapping: dict[str, str | None] = {
        # Standard line item fields
        "item_desc": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "line_total": None,
        "ordered_qty": None,
        "received_qty": None,
        # Batch format identifying fields
        "invoice_no": None,
        "contract_id": None,
        "po_no": None,
        "po_date": None,
        "vendor_name": None,
        "invoice_date": None,
        "currency": None,
        "effective_start_date": None,
        "effective_end_date": None,
        "version_number": None,
        "item_code": None,
    }

    for col in columns:
        col_str = str(col).strip()
        col_lower = col_str.lower()

        # Batch identifier columns (check these first, more specific)
        if mapping["invoice_no"] is None and _INVOICE_NO_PATTERNS.search(col_lower):
            mapping["invoice_no"] = col_str
        elif mapping["contract_id"] is None and _CONTRACT_ID_PATTERNS.search(col_lower):
            mapping["contract_id"] = col_str
        elif mapping["vendor_name"] is None and _VENDOR_NAME_PATTERNS.search(col_lower):
            mapping["vendor_name"] = col_str
        elif mapping["invoice_date"] is None and _INVOICE_DATE_PATTERNS.search(col_lower):
            mapping["invoice_date"] = col_str
        elif mapping["currency"] is None and _CURRENCY_COL_PATTERNS.search(col_lower):
            mapping["currency"] = col_str
        elif mapping["effective_start_date"] is None and _START_DATE_PATTERNS.search(col_lower):
            mapping["effective_start_date"] = col_str
        elif mapping["effective_end_date"] is None and _END_DATE_PATTERNS.search(col_lower):
            mapping["effective_end_date"] = col_str
        elif mapping["version_number"] is None and _VERSION_NO_PATTERNS.search(col_lower):
            mapping["version_number"] = col_str
        elif mapping["item_code"] is None and _ITEM_CODE_PATTERNS.search(col_lower):
            mapping["item_code"] = col_str
        elif mapping["po_no"] is None and _PO_NO_PATTERNS.search(col_lower):
            mapping["po_no"] = col_str
        elif mapping["po_date"] is None and _PO_DATE_PATTERNS.search(col_lower):
            mapping["po_date"] = col_str
        # Standard line item columns
        elif mapping["item_desc"] is None and _ITEM_DESC_PATTERNS.search(col_lower):
            mapping["item_desc"] = col_str
        elif mapping["quantity"] is None and _QUANTITY_PATTERNS.search(col_lower):
            mapping["quantity"] = col_str
        elif mapping["unit"] is None and _UNIT_PATTERNS.search(col_lower):
            mapping["unit"] = col_str
        elif mapping["unit_price"] is None and _UNIT_PRICE_PATTERNS.search(col_lower):
            mapping["unit_price"] = col_str
        elif mapping["line_total"] is None and _LINE_TOTAL_PATTERNS.search(col_lower):
            mapping["line_total"] = col_str
        elif mapping["ordered_qty"] is None and _ORDERED_QTY_PATTERNS.search(col_lower):
            mapping["ordered_qty"] = col_str
        elif mapping["received_qty"] is None and _RECEIVED_QTY_PATTERNS.search(col_lower):
            mapping["received_qty"] = col_str

    return mapping


def _is_batch_format(col_mapping: dict[str, str | None]) -> bool:
    """Detect if this is a batch file (multiple invoices/contracts/POs per file)."""
    has_invoice_id = col_mapping.get("invoice_no") is not None
    has_contract_id = col_mapping.get("contract_id") is not None
    has_po_no = col_mapping.get("po_no") is not None
    has_vendor_col = col_mapping.get("vendor_name") is not None
    return (has_invoice_id or has_contract_id or has_po_no) and has_vendor_col


def _detect_batch_type(col_mapping: dict[str, str | None]) -> str:
    """Determine if batch is INVOICE, CONTRACT, or PO type."""
    if col_mapping.get("contract_id") is not None and col_mapping.get("invoice_no") is None:
        return "CONTRACT"
    if col_mapping.get("po_no") is not None and col_mapping.get("invoice_no") is None and col_mapping.get("contract_id") is None:
        return "PO"
    return "INVOICE"


class ExcelParser(BaseParser):
    """Parser for Excel (XLSX, XLS) and CSV files."""

    @property
    def supported_formats(self) -> list[str]:
        return [".xlsx", ".xls", ".csv"]

    @property
    def parser_name(self) -> str:
        return "excel_parser_v1"

    def parse(self, file_path: Path, document_id: UUID) -> ParseResult:
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

            raw_data["original_shape"] = list(df.shape)

            # Detect header row
            header_row_idx = _detect_header_row(df)
            header_detected = header_row_idx is not None

            if header_detected:
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

            # Extract pre-header vendor info (for single-doc format)
            if header_row_idx is not None and header_row_idx > 0:
                header_text_rows = df.iloc[:header_row_idx]
                header = self._extract_header_info(header_text_rows)

            # Map columns
            col_mapping = _map_columns(new_columns)
            raw_data["column_mapping"] = {k: v for k, v in col_mapping.items() if v}

            # ── BATCH FORMAT DETECTION ────────────────────────────────
            if _is_batch_format(col_mapping):
                batch_type = _detect_batch_type(col_mapping)
                batch_rows = self._extract_batch_rows(df_data, col_mapping)
                raw_data["batch_rows"] = batch_rows
                raw_data["batch_type"] = batch_type
                raw_data["batch_count"] = len(batch_rows)

                doc_type = DocType.CONTRACT if batch_type == "CONTRACT" else (DocType.PO if batch_type == "PO" else DocType.INVOICE)

                logger.info(
                    "batch_format_detected",
                    document_id=str(document_id),
                    batch_type=batch_type,
                    row_count=len(batch_rows),
                )

                if not batch_rows:
                    failure_flags.append(FailureFlag(
                        severity="ERROR",
                        code="EMPTY_BATCH",
                        message="Batch file contains no data rows",
                    ))
                    confidence = 0.0

                return ParseResult(
                    document_id=document_id,
                    doc_type=doc_type,
                    parser_used=self.parser_name,
                    parser_version="1.0.0",
                    parse_confidence=round(confidence, 4),
                    header=header,
                    line_items=[],  # batch_rows used instead
                    failure_flags=failure_flags,
                    raw_extracted_data=raw_data,
                )

            # ── SINGLE-DOCUMENT FORMAT (original path) ────────────────
            for row_idx, (_, row) in enumerate(df_data.iterrows(), start=1):
                item = self._extract_line_item(row, col_mapping, row_idx)
                if item is not None:
                    line_items.append(item)

            if not line_items:
                failure_flags.append(FailureFlag(
                    severity="ERROR",
                    code="MISSING_LINE_ITEMS",
                    message="No line items could be extracted from the document",
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

            confidence = max(confidence, 0.0)

        except Exception as exc:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="CORRUPTED_FILE",
                message=f"Failed to parse file: {type(exc).__name__}: {exc}",
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

    def _extract_batch_rows(
        self,
        df_data: pd.DataFrame,
        col_mapping: dict[str, str | None],
    ) -> list[dict]:
        """Extract all rows from a batch format file into a list of dicts."""
        rows = []
        for _, row in df_data.iterrows():
            if all(pd.isna(v) for v in row.values):
                continue

            def get_str(field: str) -> str | None:
                col = col_mapping.get(field)
                if col and col in row.index:
                    val = row[col]
                    if pd.notna(val):
                        return str(val).strip() or None
                return None

            def get_num(field: str) -> float | None:
                col = col_mapping.get(field)
                if col and col in row.index:
                    val = _parse_numeric(row[col])
                    return float(val) if val is not None else None
                return None

            def get_date(field: str) -> str | None:
                col = col_mapping.get(field)
                if col and col in row.index:
                    val = _parse_date_value(row[col])
                    return val.isoformat() if val else None
                return None

            batch_row = {
                "invoice_no": get_str("invoice_no"),
                "contract_id": get_str("contract_id"),
                "po_no": get_str("po_no"),
                "po_date": get_date("po_date"),
                "vendor_name": get_str("vendor_name"),
                "invoice_date": get_date("invoice_date"),
                "currency": get_str("currency"),
                "effective_start_date": get_date("effective_start_date"),
                "effective_end_date": get_date("effective_end_date"),
                "version_number": get_str("version_number"),
                "item_desc": get_str("item_desc"),
                "item_code": get_str("item_code"),
                "quantity": get_num("quantity"),
                "ordered_qty": get_num("ordered_qty"),
                "unit": get_str("unit"),
                "unit_price": get_num("unit_price"),
            }

            # Only include rows that have at least an item description
            if batch_row["item_desc"]:
                rows.append(batch_row)

        return rows

    def _read_file(
        self,
        file_path: Path,
        ext: str,
        failure_flags: list[FailureFlag],
    ) -> pd.DataFrame | None:
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
        header = DocumentHeader()
        for _, row in header_rows.iterrows():
            for val in row:
                if pd.isna(val):
                    continue
                text = str(val).strip()
                if not text:
                    continue
                vendor_match = _VENDOR_PATTERNS.search(text)
                if vendor_match and header.vendor_name is None:
                    header.vendor_name = vendor_match.group(1).strip()
                date_match = _DATE_PATTERNS.search(text)
                if date_match and header.document_date is None:
                    header.document_date = _parse_date_value(date_match.group(1).strip())
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
        if all(pd.isna(v) for v in row.values):
            return None

        item_desc = None
        if col_mapping["item_desc"] and col_mapping["item_desc"] in row.index:
            val = row[col_mapping["item_desc"]]
            if pd.notna(val):
                item_desc = str(val).strip()

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

        if line_total is None and quantity is not None and unit_price is not None:
            line_total = quantity * unit_price

        ordered_qty = None
        if col_mapping["ordered_qty"] and col_mapping["ordered_qty"] in row.index:
            ordered_qty = _parse_numeric(row[col_mapping["ordered_qty"]])

        received_qty = None
        if col_mapping["received_qty"] and col_mapping["received_qty"] in row.index:
            received_qty = _parse_numeric(row[col_mapping["received_qty"]])

        field_confidences: dict[str, float] = {}
        if item_desc:
            field_confidences["item_desc"] = 1.0
        if quantity is not None:
            field_confidences["quantity"] = 1.0
        if unit_price is not None:
            field_confidences["unit_price"] = 1.0

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