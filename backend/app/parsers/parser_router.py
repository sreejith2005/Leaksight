"""
LeakSight V1 — Parser Router

Source: docs/PARSING_SPEC.md (Section 3 — Supported Formats and Parser Routing)
       docs/ARCHITECTURE.md (Section 6.6 — Parsing Layer)

Routes documents to the correct parser based on:
  1. File extension (primary signal)
  2. Content sniffing for PDFs (digital vs scanned detection)

If PDF detection is ambiguous, defaults to digital parser and flags uncertainty.
"""

from pathlib import Path
from uuid import UUID

import pdfplumber

from backend.app.core.logging import get_logger
from backend.app.parsers.base_parser import (
    BaseParser,
    DocType,
    FailureFlag,
    ParseResult,
    UnsupportedFormatError,
)
from backend.app.parsers.excel_parser import ExcelParser
from backend.app.parsers.pdf_digital_parser import DigitalPdfParser
from backend.app.parsers.pdf_scanned_parser import ScannedPdfParser
from backend.app.parsers.word_parser import WordParser

logger = get_logger(__name__)

# Extension → parser mapping (non-PDF)
_EXTENSION_MAP: dict[str, type[BaseParser]] = {
    ".xlsx": ExcelParser,
    ".xls": ExcelParser,
    ".csv": ExcelParser,
    ".docx": WordParser,
}

# Supported extensions
SUPPORTED_EXTENSIONS: set[str] = {".xlsx", ".xls", ".csv", ".pdf", ".docx"}

# Minimum text character count to consider a PDF as digital
_PDF_DIGITAL_TEXT_THRESHOLD = 50

# Number of pages to check for digital vs scanned detection
_PDF_DETECTION_PAGES = 3


def is_scanned_pdf(file_path: Path) -> bool:
    """Determine if a PDF is scanned (image-based) vs digital (text-based).

    A PDF is considered scanned if pdfplumber extracts less than 50
    characters of text from the first 3 pages.

    Per PARSING_SPEC.md §3.2.
    """
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            text_chars = 0
            for page in pdf.pages[:_PDF_DETECTION_PAGES]:
                text = page.extract_text() or ""
                text_chars += len(text.strip())
            return text_chars < _PDF_DIGITAL_TEXT_THRESHOLD
    except Exception:
        # If we can't even open the PDF, default to digital parser
        # (it will produce CORRUPTED_FILE error)
        return False


def get_parser(file_path: Path) -> BaseParser:
    """Route a file to the appropriate parser based on extension and content.

    Args:
        file_path: Path to the document file.

    Returns:
        An instance of the appropriate parser.

    Raises:
        UnsupportedFormatError: If the file extension is not supported.
    """
    ext = file_path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file format: {ext}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # Non-PDF files: route by extension
    if ext in _EXTENSION_MAP:
        parser_cls = _EXTENSION_MAP[ext]
        return parser_cls()

    # PDF files: detect digital vs scanned
    if ext == ".pdf":
        if is_scanned_pdf(file_path):
            return ScannedPdfParser()
        return DigitalPdfParser()

    raise UnsupportedFormatError(f"No parser available for extension: {ext}")


def parse_document(
    file_path: Path,
    document_id: UUID,
    doc_type: DocType = DocType.INVOICE,
) -> ParseResult:
    """Parse a document file, routing to the correct parser.

    This is the main entry point for the parsing pipeline.

    Args:
        file_path: Path to the document file.
        document_id: UUID of the document record.
        doc_type: Type of document (default: INVOICE).

    Returns:
        ParseResult with extracted data and confidence score.
    """
    parser = get_parser(file_path)

    logger.info(
        "parsing_document",
        document_id=str(document_id),
        parser=parser.parser_name,
        file_extension=file_path.suffix.lower(),
    )

    result = parser.parse(file_path, document_id)

    # Override doc_type if explicitly specified
    result.doc_type = doc_type

    # Add DETECTION_AMBIGUOUS flag for PDFs if detection was uncertain
    if file_path.suffix.lower() == ".pdf":
        _check_pdf_detection_ambiguity(file_path, parser, result)

    logger.info(
        "parse_complete",
        document_id=str(document_id),
        parser=parser.parser_name,
        confidence=result.parse_confidence,
        line_items_count=len(result.line_items),
        failure_flags_count=len(result.failure_flags),
    )

    return result


def _check_pdf_detection_ambiguity(
    file_path: Path,
    parser: BaseParser,
    result: ParseResult,
) -> None:
    """Check if PDF digital/scanned detection was ambiguous.

    If a PDF has some extractable text but less than expected,
    the detection may be uncertain — flag it.
    """
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            text_chars = 0
            for page in pdf.pages[:_PDF_DETECTION_PAGES]:
                text = page.extract_text() or ""
                text_chars += len(text.strip())

            # Ambiguous: between 20 and 100 chars (not clearly digital or scanned)
            if 20 <= text_chars <= 100:
                result.failure_flags.append(FailureFlag(
                    severity="WARNING",
                    code="DETECTION_AMBIGUOUS",
                    message=(
                        f"PDF digital/scanned detection was ambiguous "
                        f"({text_chars} text chars in first {_PDF_DETECTION_PAGES} pages). "
                        f"Defaulted to {parser.parser_name}."
                    ),
                ))
    except Exception:
        pass  # Don't fail the parse just because detection check failed
