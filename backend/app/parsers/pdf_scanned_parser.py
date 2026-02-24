"""
LeakSight V1 — Scanned PDF Parser

Source: docs/PARSING_SPEC.md (Section 5.3 — Scanned PDF Parser)
       docs/ARCHITECTURE.md (Section 6.6 — Parsing Layer)

Handles image-based (scanned) PDF files using PaddleOCR + PP-Structure.
Accuracy target: ≥ 70%.

Key behaviors:
  - Page-by-page processing with gc.collect() after each page
  - PaddleOCR for text recognition (NO TESSERACT — locked decision)
  - PP-Structure for table layout detection
  - Mobile model for V1 (lower RAM footprint)
  - Confidence starts at 0.80 and adjusts based on OCR character confidence
  - Never crash on malformed files
"""

import gc
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID

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

# ── PaddleOCR configuration (locked — no Tesseract) ──────────────
PADDLE_OCR_CONFIG = {
    "use_angle_cls": True,
    "lang": "en",
    "use_gpu": False,
    "show_log": False,
    "det_model_dir": None,
    "rec_model_dir": None,
    "cls_model_dir": None,
    "use_mp": False,
    "total_process_num": 1,
}

# Regex patterns for header extraction
_VENDOR_PATTERNS = re.compile(
    r"(?:vendor|supplier|party|from|bill\s*(?:to|from))"
    r"\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_DOC_NUMBER_PATTERNS = re.compile(
    r"(?:invoice|inv|po|grn|bill)\s*(?:no|number|#|num)\.?\s*[:\-]?\s*(\S+)",
    re.IGNORECASE,
)
_DATE_PATTERNS = re.compile(
    r"(?:date|dated)\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
    re.IGNORECASE,
)
_TOTAL_PATTERNS = re.compile(
    r"(?:grand\s*total|total\s*amount|net\s*amount|total)"
    r"\s*[:\-]?\s*[₹$€£]?\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_GST_PATTERN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2})\b")

_CURRENCY_STRIP = re.compile(r"[₹$€£¥,\s]")

# Column-mapping patterns
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

# Low OCR quality threshold
_LOW_QUALITY_CHAR_CONFIDENCE = 0.60


def _parse_numeric(value: Any) -> Decimal | None:
    """Parse a value to Decimal, handling currency and commas."""
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
    for fmt in (
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%m/%d/%Y",
        "%d-%b-%Y", "%d %b %Y",
        "%d/%m/%y", "%d-%m-%y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _map_table_columns(headers: list[str]) -> dict[str, int | None]:
    """Map OCR-detected column headers to schema field indices."""
    mapping: dict[str, int | None] = {
        "item_desc": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "line_total": None,
    }
    for idx, col in enumerate(headers):
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


class ScannedPdfParser(BaseParser):
    """Parser for scanned (image-based) PDF files.

    Uses PaddleOCR for text recognition and PP-Structure for table
    layout detection. Processes pages one at a time with gc.collect()
    after each page to manage memory.

    NO TESSERACT — this is a locked architectural decision.
    """

    def __init__(self):
        self._ocr_engine = None
        self._structure_engine = None

    @property
    def supported_formats(self) -> list[str]:
        return [".pdf"]

    @property
    def parser_name(self) -> str:
        return "pdf_scanned_parser_v1"

    def _get_ocr_engine(self):
        """Lazy-initialize PaddleOCR engine."""
        if self._ocr_engine is None:
            from paddleocr import PaddleOCR
            self._ocr_engine = PaddleOCR(**PADDLE_OCR_CONFIG)
        return self._ocr_engine

    def _get_structure_engine(self):
        """Lazy-initialize PP-Structure engine."""
        if self._structure_engine is None:
            try:
                from ppstructure.predict_system import StructureSystem
                self._structure_engine = StructureSystem(
                    det_model_dir=None,
                    rec_model_dir=None,
                    table_model_dir=None,
                    layout_model_dir=None,
                    show_log=False,
                )
            except ImportError:
                # PP-Structure may not be available; fall back to OCR-only
                self._structure_engine = None
        return self._structure_engine

    def parse(self, file_path: Path, document_id: UUID) -> ParseResult:
        """Parse a scanned PDF into the normalized intermediate schema.

        Processes page-by-page with memory cleanup after each page.
        """
        failure_flags: list[FailureFlag] = []
        all_line_items: list[LineItem] = []
        header = DocumentHeader()
        confidence = 0.80  # Start lower for scanned PDFs
        raw_data: dict = {}
        all_char_confidences: list[float] = []

        try:
            page_images = self._convert_pdf_to_images(file_path)
            raw_data["page_count"] = len(page_images)

            if not page_images:
                failure_flags.append(FailureFlag(
                    severity="ERROR",
                    code="EMPTY_FILE",
                    message="PDF contains no pages or could not be converted to images",
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

            for page_num, image in enumerate(page_images, 1):
                try:
                    page_result = self._process_page(
                        image, page_num, failure_flags
                    )
                    text = page_result.get("text", "")
                    table_rows = page_result.get("table_rows", [])
                    char_confidences = page_result.get("char_confidences", [])
                    all_char_confidences.extend(char_confidences)

                    # Extract header from first page
                    if page_num == 1:
                        header = self._extract_header_info(text, failure_flags)

                    # Extract line items from table rows
                    items = self._parse_table_rows(
                        table_rows, len(all_line_items)
                    )
                    all_line_items.extend(items)

                    # Check for low OCR quality on this page
                    if char_confidences and mean(char_confidences) < _LOW_QUALITY_CHAR_CONFIDENCE:
                        failure_flags.append(FailureFlag(
                            severity="WARNING",
                            code="LOW_OCR_QUALITY",
                            message=f"OCR character confidence below {_LOW_QUALITY_CHAR_CONFIDENCE} on page {page_num}",
                            page_number=page_num,
                        ))

                finally:
                    # Release memory immediately — critical for PaddleOCR
                    del image
                    gc.collect()

            # ── Confidence calculation ────────────────────────────
            if all_char_confidences:
                avg_char_confidence = mean(all_char_confidences)
                confidence = confidence * avg_char_confidence
            else:
                confidence = 0.0

            if not all_line_items:
                failure_flags.append(FailureFlag(
                    severity="ERROR",
                    code="MISSING_LINE_ITEMS",
                    message="No line items could be extracted from the scanned PDF",
                ))
                confidence = max(confidence - 0.20, 0.0)

            # Low OCR quality across document
            if all_char_confidences and mean(all_char_confidences) < _LOW_QUALITY_CHAR_CONFIDENCE:
                confidence -= 0.10

            confidence = max(round(confidence, 4), 0.0)

        except Exception as exc:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="CORRUPTED_FILE",
                message=f"Failed to parse scanned PDF: {type(exc).__name__}",
            ))
            confidence = 0.0

        return ParseResult(
            document_id=document_id,
            doc_type=DocType.INVOICE,
            parser_used=self.parser_name,
            parser_version="1.0.0",
            parse_confidence=confidence,
            header=header,
            line_items=all_line_items,
            failure_flags=failure_flags,
            raw_extracted_data=raw_data,
        )

    def _convert_pdf_to_images(self, file_path: Path) -> list:
        """Convert PDF pages to images for OCR processing."""
        try:
            from pdf2image import convert_from_path
            return convert_from_path(str(file_path), dpi=200)
        except ImportError:
            # Fallback: use pypdfium2
            try:
                import pypdfium2 as pdfium
                pdf = pdfium.PdfDocument(str(file_path))
                images = []
                for page in pdf:
                    bitmap = page.render(scale=2)
                    pil_image = bitmap.to_pil()
                    images.append(pil_image)
                return images
            except Exception:
                return []
        except Exception:
            return []

    def _process_page(
        self,
        image: Any,
        page_num: int,
        failure_flags: list[FailureFlag],
    ) -> dict:
        """Process a single page image with OCR.

        Returns dict with 'text', 'table_rows', and 'char_confidences'.
        """
        import numpy as np

        ocr = self._get_ocr_engine()
        img_array = np.array(image)
        result = ocr.ocr(img_array, cls=True)

        text_lines: list[str] = []
        char_confidences: list[float] = []
        table_rows: list[list[str]] = []

        if result and result[0]:
            for line in result[0]:
                # line format: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, confidence)
                if len(line) >= 2:
                    text_content = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                    conf = line[1][1] if isinstance(line[1], (list, tuple)) and len(line[1]) > 1 else 0.5
                    text_lines.append(text_content)
                    char_confidences.append(float(conf))

        full_text = "\n".join(text_lines)

        # Try PP-Structure for table detection
        try:
            structure = self._get_structure_engine()
            if structure is not None:
                struct_result = structure(img_array)
                for item in struct_result:
                    if item.get("type") == "table":
                        table_data = item.get("res", {})
                        if isinstance(table_data, list):
                            table_rows.extend(table_data)
        except Exception:
            # Fall back to line-based parsing
            pass

        # If no table rows from structure, try to parse from OCR text
        if not table_rows and text_lines:
            table_rows = self._infer_table_from_text(text_lines)

        return {
            "text": full_text,
            "table_rows": table_rows,
            "char_confidences": char_confidences,
        }

    def _infer_table_from_text(self, text_lines: list[str]) -> list[list[str]]:
        """Attempt to infer table rows from OCR text lines.

        This is a fallback when PP-Structure is unavailable.
        Splits lines into columns based on whitespace gaps.
        """
        rows: list[list[str]] = []
        for line in text_lines:
            # Split by multiple spaces (tab-separated or space-padded columns)
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) >= 3:  # At least 3 columns suggests a table row
                rows.append(parts)
        return rows

    def _extract_header_info(
        self, text: str, failure_flags: list[FailureFlag]
    ) -> DocumentHeader:
        """Extract header information from OCR text."""
        header = DocumentHeader()

        vendor_match = _VENDOR_PATTERNS.search(text)
        if vendor_match:
            header.vendor_name = vendor_match.group(1).strip()
        else:
            failure_flags.append(FailureFlag(
                severity="WARNING",
                code="MISSING_VENDOR_NAME",
                message="Vendor name not found in scanned document",
            ))

        num_match = _DOC_NUMBER_PATTERNS.search(text)
        if num_match:
            header.document_number = num_match.group(1).strip()
        else:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="MISSING_DOCUMENT_NUMBER",
                message="Document number could not be extracted from scanned PDF",
            ))

        date_match = _DATE_PATTERNS.search(text)
        if date_match:
            header.document_date = _parse_date_value(date_match.group(1))
        if header.document_date is None:
            failure_flags.append(FailureFlag(
                severity="ERROR",
                code="MISSING_DOCUMENT_DATE",
                message="Document date could not be extracted from scanned PDF",
            ))

        total_match = _TOTAL_PATTERNS.search(text)
        if total_match:
            header.total_amount = _parse_numeric(total_match.group(1))

        gst_match = _GST_PATTERN.search(text)
        if gst_match:
            header.vendor_gst_id = gst_match.group(1)

        return header

    def _parse_table_rows(
        self, rows: list[list[str]], offset: int
    ) -> list[LineItem]:
        """Parse OCR table rows into LineItem objects."""
        if not rows:
            return []

        # Try to detect header row
        header_idx = None
        for idx, row in enumerate(rows):
            row_text = " ".join(str(v).lower() for v in row)
            if any(kw in row_text for kw in ("item", "desc", "qty", "quantity", "price", "rate", "amount")):
                header_idx = idx
                break

        if header_idx is not None:
            headers = [str(v) for v in rows[header_idx]]
            data_rows = rows[header_idx + 1:]
        else:
            headers = []
            data_rows = rows

        col_mapping = _map_table_columns(headers) if headers else {
            "item_desc": 0 if len(rows[0]) > 0 else None,
            "quantity": 1 if len(rows[0]) > 1 else None,
            "unit": 2 if len(rows[0]) > 2 else None,
            "unit_price": 3 if len(rows[0]) > 3 else None,
            "line_total": 4 if len(rows[0]) > 4 else None,
        }

        items: list[LineItem] = []
        for row_idx, row in enumerate(data_rows, start=1):
            item = self._extract_line_item(row, col_mapping, offset + row_idx)
            if item is not None:
                items.append(item)

        return items

    def _extract_line_item(
        self,
        row: list[str],
        col_mapping: dict[str, int | None],
        line_number: int,
    ) -> LineItem | None:
        """Extract a single line item from a table row."""
        item_desc = None
        if col_mapping["item_desc"] is not None and col_mapping["item_desc"] < len(row):
            val = str(row[col_mapping["item_desc"]]).strip()
            if val:
                item_desc = val

        if not item_desc:
            return None

        quantity = None
        if col_mapping["quantity"] is not None and col_mapping["quantity"] < len(row):
            quantity = _parse_numeric(row[col_mapping["quantity"]])

        unit = None
        if col_mapping["unit"] is not None and col_mapping["unit"] < len(row):
            val = str(row[col_mapping["unit"]]).strip()
            if val:
                unit = val

        unit_price = None
        if col_mapping["unit_price"] is not None and col_mapping["unit_price"] < len(row):
            unit_price = _parse_numeric(row[col_mapping["unit_price"]])

        line_total = None
        if col_mapping["line_total"] is not None and col_mapping["line_total"] < len(row):
            line_total = _parse_numeric(row[col_mapping["line_total"]])

        if line_total is None and quantity is not None and unit_price is not None:
            line_total = quantity * unit_price

        field_confidences: dict[str, float] = {}
        if item_desc:
            field_confidences["item_desc"] = 0.80  # Lower confidence for OCR
        if quantity is not None:
            field_confidences["quantity"] = 0.80
        if unit_price is not None:
            field_confidences["unit_price"] = 0.80
        if line_total is not None:
            field_confidences["line_total"] = 0.80

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
