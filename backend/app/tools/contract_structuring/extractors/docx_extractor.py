"""
Word document table extractor using python-docx.
Detects pricing tables by header row keyword matching.
"""
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

PRICING_HEADER_KEYWORDS = [
    'item', 'description', 'particulars', 'material', 'product',
    'unit', 'uom', 'u/m', 'unit of measure',
    'rate', 'price', 'unit price', 'amount',
    'qty', 'quantity'
]


def extract_tables_from_docx(document_path: str) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
    results = []
    try:
        from docx import Document
        doc = Document(document_path)
        for table_idx, table in enumerate(doc.tables):
            if len(table.rows) < 2:
                continue
            header_row = [cell.text.strip().lower() for cell in table.rows[0].cells]
            confidence = _score_pricing_table(header_row)
            if confidence < 0.3:
                continue
            header_clean = [cell.text.strip() for cell in table.rows[0].cells]
            rows = []
            for row in table.rows[1:]:
                row_dict = {}
                for col_idx, cell in enumerate(row.cells):
                    col_name = header_clean[col_idx] if col_idx < len(header_clean) else f"col_{col_idx}"
                    row_dict[col_name] = cell.text.strip()
                rows.append(row_dict)
            results.append(RawTableResult(
                source_page=table_idx + 1,
                extraction_method="DOCX_TABLE",
                raw_table_json=rows,
                table_confidence=confidence,
                column_count=len(header_clean),
                row_count=len(rows),
            ))
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
    return results


def extract_text_from_docx(document_path: str) -> str:
    """Extract full text from DOCX for clause extraction."""
    try:
        from docx import Document
        doc = Document(document_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        paragraphs.append(cell.text.strip())
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX text extraction failed: {e}")
        return ""


def _score_pricing_table(header_row: List[str]) -> float:
    """Score 0.0-1.0 how likely a table is a pricing table based on headers."""
    if not header_row:
        return 0.0
    matches = sum(1 for h in header_row if any(kw in h for kw in PRICING_HEADER_KEYWORDS))
    return min(1.0, matches / max(1, len(header_row)) * 2)


class DocxExtractor:
    """Backward-compatible wrapper for existing class-based extraction flows."""

    def extract_tables(self, document_path):
        return extract_tables_from_docx(str(document_path))

    def extract_text(self, document_path):
        return extract_text_from_docx(str(document_path))
