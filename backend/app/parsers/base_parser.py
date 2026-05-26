"""
LeakSight V1 — Parser Base Class and Normalized Intermediate Schema

Source: docs/PARSING_SPEC.md (Section 4 — Normalized Intermediate Schema),
       docs/PARSING_SPEC.md (Section 6 — Failure Flagging Behavior),
       docs/ARCHITECTURE.md (Section 6.6 — Parsing Layer)

Every parser must output ParseResult (the normalized intermediate schema).
This decouples document format from all downstream business logic.

Critical rule: raw_extracted_data and raw text must NEVER appear in logs.
The __repr__ methods exclude these fields to prevent accidental logging.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import UUID


class DocType(str, Enum):
    """Supported document types."""

    INVOICE = "INVOICE"
    CONTRACT = "CONTRACT"
    PO = "PO"
    GRN = "GRN"


class FailureSeverity(str, Enum):
    """Severity levels for failure flags per PARSING_SPEC.md Section 6.1."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class FailureFlag:
    """Represents a specific parsing failure or warning.

    Per PARSING_SPEC.md Section 6.2, standard codes include:
    MISSING_DOCUMENT_NUMBER, MISSING_DOCUMENT_DATE, MISSING_VENDOR_NAME,
    MISSING_LINE_ITEMS, MISSING_UNIT_PRICE, MISSING_QUANTITY,
    AMBIGUOUS_DATE_FORMAT, HEADER_ROW_NOT_DETECTED, TABLE_EXTRACTION_FALLBACK,
    LOW_OCR_QUALITY, PASSWORD_PROTECTED, CORRUPTED_FILE, EMPTY_FILE,
    UNSUPPORTED_FORMAT, DETECTION_AMBIGUOUS, etc.

    Attributes:
        severity: ERROR, WARNING, or INFO.
        code: Machine-readable failure code.
        message: Human-readable description.
        page_number: Page where the issue occurred (if applicable).
        field_name: Field affected (if applicable).
    """

    severity: str
    code: str
    message: str
    page_number: int | None = None
    field_name: str | None = None


@dataclass
class DocumentHeader:
    """Common header fields extracted from the document.

    Attributes:
        vendor_name: Raw vendor name as it appears in the document.
        vendor_gst_id: GST/Tax ID if found.
        document_number: Invoice no / PO no / GRN no / Contract ref.
        document_date: Invoice date / PO date / GRN date.
        total_amount: Total document amount (invoices).
        currency: ISO 4217 code, or raw currency string.
        valid_from: Contract start date.
        valid_to: Contract end date.
        version_number: Contract version/amendment number.
    """

    vendor_name: str | None = None
    vendor_gst_id: str | None = None
    document_number: str | None = None
    document_date: date | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    version_number: int | None = None


@dataclass
class LineItem:
    """Individual line item from a document.

    Attributes:
        line_number: Sequential line number.
        item_desc: Item/service description (raw).
        quantity: Quantity.
        unit: Unit of measure (raw).
        unit_price: Unit price.
        line_total: Line total (quantity * unit_price, or as stated).
        ordered_qty: PO: ordered quantity.
        received_qty: GRN: received quantity.
        field_confidences: Per-field confidence scores.
        extraction_notes: Notes about extraction issues.
    """

    line_number: int
    item_desc: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    ordered_qty: Decimal | None = None
    received_qty: Decimal | None = None
    field_confidences: dict[str, float] = field(default_factory=dict)
    extraction_notes: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    """Output contract for all parsers — the normalized intermediate schema.

    Every parser, regardless of input format, must return this exact schema.
    This is the contract between parsers and all downstream services
    (normalization, matching, rules engine).

    Critical: raw_extracted_data must NEVER be logged. The __repr__ method
    excludes it to prevent accidental log exposure.

    Attributes:
        document_id: UUID of the source document.
        doc_type: INVOICE, CONTRACT, PO, or GRN.
        parser_used: Name of the parser that produced this result.
        parser_version: Version string of the parser code.
        parse_confidence: 0.0 to 1.0 overall confidence score.
        header: Extracted document header fields.
        line_items: List of extracted line items.
        failure_flags: List of failure/warning flags (never None).
        raw_extracted_data: Full parser output before normalization (never logged).
    """

    document_id: UUID
    doc_type: DocType
    parser_used: str
    parser_version: str
    parse_confidence: float
    header: DocumentHeader
    line_items: list[LineItem]
    failure_flags: list[FailureFlag] = field(default_factory=list)
    raw_extracted_data: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        """Custom repr that excludes raw_extracted_data to prevent log exposure.

        raw_extracted_data may contain raw document text which must never
        appear in any log output per docs/CLAUDE.md logging convention.
        """
        return (
            f"ParseResult("
            f"document_id={self.document_id!r}, "
            f"doc_type={self.doc_type!r}, "
            f"parser_used={self.parser_used!r}, "
            f"parser_version={self.parser_version!r}, "
            f"parse_confidence={self.parse_confidence!r}, "
            f"header={self.header!r}, "
            f"line_items_count={len(self.line_items)}, "
            f"failure_flags_count={len(self.failure_flags)}, "
            f"raw_extracted_data='[EXCLUDED FROM REPR]'"
            f")"
        )

    def to_jsonb(self) -> dict:
        """Serialize to a dict suitable for structured_output_jsonb storage.

        Returns:
            Dictionary with all fields serialized for JSONB storage.
        """
        return {
            "document_id": str(self.document_id),
            "doc_type": self.doc_type.value if isinstance(self.doc_type, DocType) else self.doc_type,
            "parser_used": self.parser_used,
            "parser_version": self.parser_version,
            "parse_confidence": self.parse_confidence,
            "header": {
                "vendor_name": self.header.vendor_name,
                "vendor_gst_id": self.header.vendor_gst_id,
                "document_number": self.header.document_number,
                "document_date": str(self.header.document_date) if self.header.document_date else None,
                "total_amount": str(self.header.total_amount) if self.header.total_amount else None,
                "currency": self.header.currency,
                "valid_from": str(self.header.valid_from) if self.header.valid_from else None,
                "valid_to": str(self.header.valid_to) if self.header.valid_to else None,
                "version_number": self.header.version_number,
            },
            "line_items": [
                {
                    "line_number": li.line_number,
                    "item_desc": li.item_desc,
                    "quantity": str(li.quantity) if li.quantity is not None else None,
                    "unit": li.unit,
                    "unit_price": str(li.unit_price) if li.unit_price is not None else None,
                    "line_total": str(li.line_total) if li.line_total is not None else None,
                    "ordered_qty": str(li.ordered_qty) if li.ordered_qty is not None else None,
                    "received_qty": str(li.received_qty) if li.received_qty is not None else None,
                    "field_confidences": li.field_confidences,
                    "extraction_notes": li.extraction_notes,
                }
                for li in self.line_items
            ],
            "failure_flags": [
                {
                    "severity": ff.severity,
                    "code": ff.code,
                    "message": ff.message,
                    "page_number": ff.page_number,
                    "field_name": ff.field_name,
                }
                for ff in self.failure_flags
            ],
            "raw_extracted_data": self.raw_extracted_data or {},
        }


class UnsupportedFormatError(Exception):
    """Raised when a file format is not supported by any parser.

    Attributes:
        extension: The unsupported file extension.
    """

    def __init__(self, extension: str) -> None:
        self.extension = extension
        super().__init__(f"Unsupported file format: {extension}")


class BaseParser(ABC):
    """Abstract base class for all document parsers.

    Every parser implementation must:
    1. Inherit from BaseParser
    2. Implement parse() returning ParseResult
    3. Define supported_formats property
    4. Define parser_name property

    Parsers only calculate and return confidence scores. They do NOT
    make routing decisions based on confidence — that is the
    responsibility of parse_storage_service.py (Step 4.8/4.9).
    """

    @abstractmethod
    def parse(self, file_path: Path, document_id: UUID) -> ParseResult:
        """Parse a document and return the normalized intermediate schema.

        Args:
            file_path: Path to the file on disk.
            document_id: UUID of the document record.

        Returns:
            ParseResult with all extracted data and confidence score.

        Note:
            Must never raise unhandled exceptions. All errors must be
            caught and added to failure_flags. Return a partial
            ParseResult with low confidence rather than crashing.
        """
        ...

    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """File extensions this parser can handle (e.g., ['.pdf'])."""
        ...

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Human-readable parser identifier (e.g., 'excel_parser_v1')."""
        ...
