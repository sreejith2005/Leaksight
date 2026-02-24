# LeakSight V1 — Parsing Specification

## 1. Overview

The parsing layer converts raw uploaded documents (PDF, Excel, CSV, Word) into a **normalized intermediate schema** that all downstream services consume. No downstream logic (normalization, matching, rules engine) ever touches raw file bytes — only the structured output from parsers.

### Core Principles

1. **No silent drops** — Every failure must surface as a visible flag. A parser never silently returns empty results when it encountered an error.
2. **Normalized intermediate schema** — Every parser outputs the same schema structure, regardless of input format. This decouples document format from business logic.
3. **Parse confidence** — Every parse result includes a confidence score. Low-confidence results are flagged, not hidden.
4. **Version tracking** — Re-parsing a document creates a new `raw_version` row in `raw_parses`. Old versions are never overwritten.

---

## 2. Accuracy Targets

| Format | Library | Target Accuracy | Notes |
|---|---|---|---|
| **Excel (.xlsx, .xls)** | pandas + openpyxl | **≥ 95%** | Structured data; failures are formatting edge cases |
| **CSV** | pandas | **≥ 95%** | Same as Excel; delimiter detection may vary |
| **Digital PDF** (text-based) | pdfplumber + camelot | **≥ 85%** | Table extraction is the challenge; multi-page tables especially |
| **Scanned PDF** (image-based) | PaddleOCR + PP-Structure | **≥ 70%** | Manual assist allowed; low-confidence results flagged |
| **Word (.docx)** | python-docx | **≥ 85%** | Tables are reliable; complex formatting may degrade |

**Accuracy definition:** Percentage of line items where all key fields (item description, quantity, unit, unit price, line total) are correctly extracted. A line item with any field wrong or missing counts as an accuracy miss.

---

## 3. Supported Formats and Parser Routing

### 3.1 Format Detection

The parser router (`parsers/parser_router.py`) determines which parser to use based on:

1. **File extension** — primary signal
2. **Content sniffing** — secondary signal for PDF (detect whether scanned or digital)

| Extension | MIME Type | Parser | Notes |
|---|---|---|---|
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `excel_parser.py` | Via openpyxl |
| `.xls` | `application/vnd.ms-excel` | `excel_parser.py` | Via openpyxl (legacy format) |
| `.csv` | `text/csv` | `excel_parser.py` | Same parser, different read mode |
| `.pdf` (digital) | `application/pdf` | `pdf_digital_parser.py` | Text extractable via pdfplumber |
| `.pdf` (scanned) | `application/pdf` | `pdf_scanned_parser.py` | Image-based; requires OCR |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `word_parser.py` | Via python-docx |

### 3.2 PDF Digital vs Scanned Detection

Before routing a PDF, the parser router must determine whether it is digital (text-based) or scanned (image-based):

```python
def is_scanned_pdf(file_path: str) -> bool:
    """
    A PDF is considered scanned if:
    1. pdfplumber extracts less than 50 characters of text from the first 3 pages
    2. OR the PDF contains embedded images covering >80% of page area
    """
    with pdfplumber.open(file_path) as pdf:
        text_chars = 0
        for page in pdf.pages[:3]:  # Check first 3 pages only
            text = page.extract_text() or ""
            text_chars += len(text.strip())
        return text_chars < 50
```

**If detection is ambiguous** (e.g., a PDF with some text and some images): default to the **digital PDF parser**, flag uncertainty in the parse result's `failure_flags`.

---

## 4. Normalized Intermediate Schema

**Every parser must output this exact schema**, regardless of input format. This is the contract between parsers and all downstream services.

### 4.1 Schema Definition

```python
@dataclass
class ParseResult:
    """Output contract for all parsers."""
    
    # Identification
    document_id: UUID
    doc_type: DocType  # INVOICE, CONTRACT, PO, GRN
    parser_used: str   # e.g., "excel_parser_v1"
    parser_version: str  # e.g., "1.0.0"
    
    # Confidence
    parse_confidence: float  # 0.0 to 1.0
    
    # Extracted data — varies by doc_type
    header: DocumentHeader
    line_items: list[LineItem]
    
    # Failure tracking
    failure_flags: list[FailureFlag]
    
    # Raw extracted data (for debugging)
    raw_extracted_data: dict  # Full parser output before normalization


@dataclass
class DocumentHeader:
    """Common header fields extracted from the document."""
    
    # Vendor identification
    vendor_name: str | None          # Raw vendor name as it appears
    vendor_gst_id: str | None        # GST/Tax ID if found
    
    # Document identification
    document_number: str | None      # Invoice no / PO no / GRN no / Contract ref
    document_date: date | None       # Invoice date / PO date / GRN date
    
    # Financial
    total_amount: Decimal | None     # Total document amount (invoices)
    currency: str | None             # ISO 4217 code, or raw currency string
    
    # Contract-specific
    valid_from: date | None          # Contract start date
    valid_to: date | None            # Contract end date
    version_number: int | None       # Contract version/amendment number


@dataclass
class LineItem:
    """Individual line item from a document."""
    
    line_number: int                 # Sequential line number
    item_desc: str | None            # Item/service description (raw)
    quantity: Decimal | None         # Quantity
    unit: str | None                 # Unit of measure (raw)
    unit_price: Decimal | None       # Unit price
    line_total: Decimal | None       # Line total (quantity × unit_price, or as stated)
    
    # For PO/GRN
    ordered_qty: Decimal | None      # PO: ordered quantity
    received_qty: Decimal | None     # GRN: received quantity
    
    # Extraction confidence per field
    field_confidences: dict[str, float]  # e.g., {"item_desc": 0.95, "unit_price": 0.88}
    
    # Flags
    extraction_notes: list[str]      # Any notes about extraction issues


@dataclass
class FailureFlag:
    """Represents a specific parsing failure or warning."""
    
    severity: str          # "ERROR" | "WARNING" | "INFO"
    code: str              # Machine-readable code, e.g., "MISSING_HEADER_DATE"
    message: str           # Human-readable description
    page_number: int | None  # Which page the issue was on (if applicable)
    field_name: str | None   # Which field was affected (if applicable)
```

### 4.2 Field Extraction Rules

| Field | Required By | Extraction Rule |
|---|---|---|
| `vendor_name` | All types | Look for vendor/supplier name in header area. If not found, set to None and add WARNING flag. |
| `document_number` | All types | Invoice number, PO number, GRN number, or contract reference. Must be found — if missing, add ERROR flag. |
| `document_date` | All types | Parse date in any common format (DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-Mon-YYYY). If ambiguous, prefer DD/MM/YYYY (Indian format). If not found, add ERROR flag. |
| `total_amount` | INVOICE | Total invoice amount. Look for "Total", "Grand Total", "Net Amount". If missing, sum line items. |
| `item_desc` | All types | Item/service description. Strip excess whitespace. Preserve original text (normalization happens later). |
| `quantity` | INVOICE, PO, GRN | Numeric value. Handle comma-separated thousands (1,000 → 1000). Handle Indian numbering (1,00,000 → 100000). |
| `unit` | All types | Extract as raw string. Normalization via abbreviation_dictionary happens downstream. |
| `unit_price` | INVOICE, CONTRACT | Numeric value. Same numeric parsing rules as quantity. |
| `line_total` | INVOICE | If present, extract directly. If missing, calculate as `quantity × unit_price`. If both are missing, add ERROR flag. |

---

## 5. Parser Implementations

### 5.1 Excel/CSV Parser (`parsers/excel_parser.py`)

**Library:** pandas + openpyxl

**Behavior:**

1. **Header detection:** Scan first 10 rows to find the header row. Look for keywords: "Description", "Item", "Qty", "Quantity", "Unit", "Rate", "Price", "Amount", "Total".
2. **Column mapping:** Map detected columns to schema fields. Use fuzzy matching on column headers if exact match fails.
3. **Data extraction:** Read remaining rows as line items.
4. **Multi-sheet handling:** If workbook has multiple sheets, process each sheet that appears to contain tabular data. Rate cards and pricing tables may be on separate sheets.
5. **Numeric parsing:** Strip currency symbols (₹, $, €), remove commas, handle parentheses for negative numbers.

**Confidence calculation:**
```python
confidence = 1.0
if header_row_not_auto_detected:
    confidence -= 0.10
if any_column_mapped_by_fuzzy:
    confidence -= 0.05 per fuzzy-mapped column
if any_line_item_has_missing_required_field:
    confidence -= 0.02 per incomplete line item (max 0.30 deduction)
# Floor at 0.0
```

### 5.2 Digital PDF Parser (`parsers/pdf_digital_parser.py`)

**Library:** pdfplumber (primary), camelot (for complex tables)

**Behavior:**

1. **Text extraction:** Use pdfplumber to extract all text.
2. **Header parsing:** Regex-based extraction of vendor name, invoice/PO/GRN number, date, totals from the header area (typically first 1/3 of page 1).
3. **Table extraction:** Use pdfplumber's `extract_tables()` first. If tables are poorly detected (few rows, fragmented), fall back to camelot with `flavor='lattice'` (for bordered tables) then `flavor='stream'` (for borderless tables).
4. **Multi-page table handling:** Detect tables that span multiple pages (same column structure continuing on next page). Concatenate into a single table.
5. **Footer/noise removal:** Ignore common footer patterns (page numbers, "Thank you for your business", bank details below table).

**Confidence calculation:**
```python
confidence = 1.0
if table_extraction_required_camelot_fallback:
    confidence -= 0.10
if multi_page_table_detected:
    confidence -= 0.05  # Concatenation introduces risk
if date_format_ambiguous:
    confidence -= 0.05
if any_line_item_has_missing_required_field:
    confidence -= 0.02 per incomplete line item (max 0.30 deduction)
```

### 5.3 Scanned PDF Parser (`parsers/pdf_scanned_parser.py`)

**Library:** PaddleOCR + PP-Structure

**Behavior:**

1. **Page-by-page processing:** Process each page individually. Load page image, OCR it, write result, discard image before next page. This is **critical** for memory management — PaddleOCR can consume 6–10GB without page-level cleanup.
2. **Table detection:** Use PP-Structure for table layout detection. This identifies table regions, columns, and row boundaries in the page image.
3. **Text extraction:** Use PaddleOCR for character recognition within detected regions.
4. **Post-processing:** Reconstruct table data from OCR results + layout detection.
5. **Garbage collection:** Call `gc.collect()` after each page to release memory.
6. **Model selection:** Use PaddleOCR mobile model for V1 (100–200MB RAM vs 300–500MB for server model). Accuracy is sufficient for the ≥70% target.

**Confidence calculation:**
```python
confidence = 0.80  # Start lower for scanned PDFs
per_character_confidences = [char.confidence for char in ocr_results]
avg_char_confidence = mean(per_character_confidences)
confidence = confidence * avg_char_confidence
if table_regions_detected == 0:
    confidence -= 0.20  # No table structure found
if any_page_had_low_ocr_quality:
    confidence -= 0.10
```

**Critical:** This parser must **never** import or depend on Tesseract. PaddleOCR is the only OCR engine for LeakSight V1. This is a locked architectural decision.

### 5.4 Word Parser (`parsers/word_parser.py`)

**Library:** python-docx

**Behavior:**

1. **Table extraction:** Iterate over `doc.tables` to extract tabular data (pricing tables, line items).
2. **Paragraph extraction:** Extract header information from paragraphs.
3. **Multi-table handling:** Process all tables in the document. For contracts, multiple tables may contain pricing data for different categories.
4. **Formatting handling:** Strip bold, italic, and other formatting from text. Preserve content only.

**Confidence calculation:**
```python
confidence = 1.0
if no_tables_found:
    confidence -= 0.20
if date_not_found_in_paragraphs:
    confidence -= 0.10
if any_line_item_has_missing_required_field:
    confidence -= 0.02 per incomplete line item (max 0.30 deduction)
```

---

## 6. Failure Flagging Behavior

### 6.1 Severity Levels

| Severity | Meaning | System Behavior |
|---|---|---|
| `ERROR` | Critical field missing or parser crash | Document marked as `parse_status = FAILED`. Specific error logged. Run may continue with other documents. |
| `WARNING` | Non-critical issue (ambiguous date, fuzzy column mapping) | Document still processed. Warning recorded in `failure_flags`. May affect parse confidence. |
| `INFO` | Informational (e.g., "used camelot fallback for table extraction") | No impact on processing. Recorded for debugging. |

### 6.2 Standard Failure Flag Codes

| Code | Severity | Description |
|---|---|---|
| `MISSING_DOCUMENT_NUMBER` | ERROR | Invoice/PO/GRN number could not be extracted |
| `MISSING_DOCUMENT_DATE` | ERROR | Document date could not be extracted |
| `MISSING_VENDOR_NAME` | WARNING | Vendor name not found in document |
| `MISSING_LINE_ITEMS` | ERROR | No line items could be extracted from the document |
| `MISSING_UNIT_PRICE` | WARNING | One or more line items have no unit price |
| `MISSING_QUANTITY` | WARNING | One or more line items have no quantity |
| `AMBIGUOUS_DATE_FORMAT` | WARNING | Date format could not be determined with certainty |
| `HEADER_ROW_NOT_DETECTED` | WARNING | Table header row was not auto-detected (Excel) |
| `TABLE_EXTRACTION_FALLBACK` | INFO | Used camelot fallback for table extraction (PDF) |
| `MULTI_PAGE_TABLE_CONCATENATED` | INFO | Table spanning multiple pages was concatenated |
| `LOW_OCR_QUALITY` | WARNING | OCR character confidence below 0.60 on one or more pages |
| `PASSWORD_PROTECTED` | ERROR | File is password protected; cannot parse |
| `CORRUPTED_FILE` | ERROR | File is corrupted; cannot open |
| `EMPTY_FILE` | ERROR | File contains no content |
| `UNSUPPORTED_FORMAT` | ERROR | File format is not supported |
| `DETECTION_AMBIGUOUS` | WARNING | PDF digital/scanned detection was ambiguous |
| `CROSS_DIMENSION_UNIT` | WARNING | Unit detected but may be cross-dimension (e.g., KG found where L expected) |

### 6.3 No Silent Drops

**This is a non-negotiable rule.** If a parser encounters ANY issue:
- It must add a `FailureFlag` to the result
- It must adjust `parse_confidence` downward
- It must return a `ParseResult` (even if partially filled) — never return nothing
- If the issue is severe enough to prevent any useful extraction (PASSWORD_PROTECTED, CORRUPTED_FILE), set `parse_status = FAILED` on the document and add an ERROR flag

---

## 7. RAW Version Row Creation Rule

### 7.1 On First Parse

When a document is parsed for the first time:
- Create a `raw_parses` row with `raw_version = 1`
- Set `structured_output_jsonb` to the full `ParseResult` (serialized)
- Set `parse_confidence` from the parser's calculation
- Set `failure_flags` from the parser's output

### 7.2 On Re-Parse

When a document is re-parsed (e.g., after parser upgrade, or user triggers re-upload of same document):
- **Never update the existing `raw_parses` row**
- Create a **new** `raw_parses` row with `raw_version = previous_max + 1`
- The canonical layer is updated to reflect the latest parse (normalization re-runs)
- Old `raw_parses` rows are preserved for audit trail

### 7.3 On Re-Upload (Same Document, Same SHA-256)

When a user re-uploads a file whose SHA-256 hash matches an existing document:
- Create a new `document_hashes` row with `hash_type = REUPLOAD`, `comparison_status = UNCHANGED`
- Do **not** create a new `documents` row (same document)
- Do **not** re-parse (no new content)
- Return the existing `document_id`

### 7.4 On Re-Upload (Modified Document, Different SHA-256)

When a user re-uploads a file with the same filename but different SHA-256:
- Create a new `document_hashes` row with `hash_type = REUPLOAD`, `comparison_status = MODIFIED`
- Trigger a re-parse
- New `raw_parses` row created with incremented `raw_version`
- Canonical layer updated to reflect new parse

---

## 8. Parse Confidence Threshold Enforcement

### 8.1 Where This Logic Lives

The confidence threshold enforcement step lives in `services/parse_storage_service.py` — **not** inside individual parsers. Parsers calculate and return confidence. The storage service makes routing decisions based on confidence.

### 8.2 Enforcement Logic

```python
def store_parse_result(parse_result: ParseResult, tenant_id: UUID) -> None:
    """
    Store parse result and apply confidence threshold enforcement.
    """
    # Get tenant settings
    settings = get_tenant_settings(tenant_id)
    
    # Write raw_parses row (always — even low confidence results are stored)
    write_raw_parse(parse_result)
    
    # Confidence threshold check
    if parse_result.parse_confidence < settings.manual_review_threshold:
        # Flag the document
        flag_document_low_confidence(parse_result.document_id)
        # Mark the run for PARTIAL_SUCCESS (if a run is active)
        mark_run_partial_success(parse_result.run_id)
        # Still proceed — do not halt processing
    
    # Continue to normalization regardless
    proceed_to_normalization(parse_result)
```

### 8.3 What Happens at Each Confidence Level

| Condition | Action |
|---|---|
| `parse_confidence >= manual_review_threshold` (default 0.70) | Document proceeds normally. No flag. |
| `parse_confidence < manual_review_threshold` | Document flagged (`documents.low_confidence_flag = TRUE`). Parse result still stored. Normalization still runs. Run status transitions to `PARTIAL_SUCCESS`. UI shows a low-confidence warning for this document. |
| `parse_confidence = 0` (total failure) | Document `parse_status = FAILED`. Error flag added. Parse result stored (empty/minimal). Normalization skips this document. |

### 8.4 Impact on Run Status

- If **all** documents in a run have `parse_confidence >= manual_review_threshold` and no other issues: run status = `COMPLETE`
- If **one or more** documents have `parse_confidence < manual_review_threshold`: run status = `PARTIAL_SUCCESS`
- The `PARTIAL_SUCCESS` status tells the user: "The run completed, but some documents need manual verification. Check the flagged documents."

### 8.5 Configurable Threshold

The threshold is per-tenant: `tenant_settings.manual_review_threshold` (default `0.70`). Tenants with higher data quality can raise this to `0.85`. Tenants with consistently messy documents can lower it to `0.50` to reduce false flags.

---

## 9. Parser Configuration

### 9.1 PaddleOCR Configuration

```python
PADDLE_OCR_CONFIG = {
    "use_angle_cls": True,       # Detect and correct rotated text
    "lang": "en",                # English language model
    "use_gpu": False,            # CPU only for V1
    "show_log": False,           # Suppress verbose logging
    "det_model_dir": None,       # Use default mobile model
    "rec_model_dir": None,       # Use default mobile model
    "cls_model_dir": None,       # Use default mobile model
    "use_mp": False,             # No multiprocessing within a single parse
    "total_process_num": 1,      # One process per parse
}
```

### 9.2 pdfplumber Configuration

```python
PDFPLUMBER_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "min_words_vertical": 3,
    "min_words_horizontal": 1,
    "snap_tolerance": 3,
    "join_tolerance": 3,
}
```

### 9.3 camelot Configuration

```python
CAMELOT_CONFIG = {
    "lattice": {
        "line_scale": 40,
        "process_background": True,
    },
    "stream": {
        "edge_tol": 50,
        "row_tol": 10,
    }
}
```

---

## 10. Memory Management (Scanned PDF Parser)

### 10.1 Page-by-Page Processing

The scanned PDF parser **must** process pages individually:

```python
def parse_scanned_pdf(file_path: str) -> ParseResult:
    images = convert_pdf_to_images(file_path)
    all_line_items = []
    
    for page_num, image in enumerate(images, 1):
        # Process single page
        page_result = ocr_engine.ocr(image)
        line_items = extract_line_items_from_ocr(page_result)
        all_line_items.extend(line_items)
        
        # Release memory immediately
        del image
        del page_result
        gc.collect()
    
    return build_parse_result(all_line_items)
```

### 10.2 Memory Monitoring

After each document parse, log memory usage:

```python
import psutil
process = psutil.Process()
memory_mb = process.memory_info().rss / (1024 * 1024)
logger.info("parse_complete", document_id=doc_id, memory_mb=memory_mb)
```

If memory exceeds 8GB warning threshold, log a WARNING. This is a signal to reduce Celery concurrency.
