"""
PDF table extractor - three-tier strategy:
  Tier 1: camelot lattice (bordered tables)    -> confidence 0.85-1.0
  Tier 2: camelot stream (borderless tables)   -> confidence 0.60-0.85
  Tier 3: pdfplumber fallback                  -> confidence 0.40-0.70

Process in 50-page batches for large documents.
"""
import logging
from typing import List
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_tables_from_pdf(document_path: str) -> List["RawTableResult"]:
    """
    Extract all pricing tables from a PDF document.
    Returns list of RawTableResult sorted by source_page.
    Never raises - on any error, logs and returns empty list.
    """
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult

    path = Path(document_path)
    if not path.exists():
        logger.error(f"PDF not found: {document_path}")
        return []

    results = []

    try:
        import fitz
        doc = fitz.open(document_path)
        total_pages = len(doc)
        doc.close()
    except Exception:
        try:
            import pdfplumber
            with pdfplumber.open(document_path) as pdf:
                total_pages = len(pdf.pages)
        except Exception as e:
            logger.error(f"Cannot determine page count: {e}")
            return []

    batch_size = 50
    for batch_start in range(1, total_pages + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, total_pages)
        page_range = f"{batch_start}-{batch_end}"

        tier1_results = _try_camelot_lattice(document_path, page_range)
        results.extend(tier1_results)

        pages_with_tier1 = {r.source_page for r in tier1_results if r.table_confidence >= 0.6}
        tier2_results = _try_camelot_stream(document_path, page_range, exclude_pages=pages_with_tier1)
        results.extend(tier2_results)

        pages_covered = pages_with_tier1 | {r.source_page for r in tier2_results if r.table_confidence >= 0.5}
        tier3_results = _try_pdfplumber(document_path, batch_start, batch_end, exclude_pages=pages_covered)
        results.extend(tier3_results)

    return sorted(results, key=lambda r: r.source_page)


def _try_camelot_lattice(document_path: str, page_range: str) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
    results = []
    try:
        import camelot
        tables = camelot.read_pdf(document_path, pages=page_range, flavor='lattice')
        for table in tables:
            if table.df.empty or len(table.df) < 2:
                continue
            rows = table.df.to_dict('records')
            results.append(RawTableResult(
                source_page=table.page,
                extraction_method="CAMELOT_LATTICE",
                raw_table_json=_clean_rows(rows),
                table_confidence=min(1.0, 0.7 + (table.accuracy / 100) * 0.3),
                column_count=len(table.df.columns),
                row_count=len(table.df),
            ))
    except Exception as e:
        logger.debug(f"Camelot lattice failed for {page_range}: {e}")
    return results


def _try_camelot_stream(document_path: str, page_range: str, exclude_pages: set) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
    results = []
    try:
        import camelot
        tables = camelot.read_pdf(document_path, pages=page_range, flavor='stream')
        for table in tables:
            if table.page in exclude_pages:
                continue
            if table.df.empty or len(table.df) < 2:
                continue
            rows = table.df.to_dict('records')
            results.append(RawTableResult(
                source_page=table.page,
                extraction_method="CAMELOT_STREAM",
                raw_table_json=_clean_rows(rows),
                table_confidence=min(0.85, 0.5 + (table.accuracy / 100) * 0.35),
                column_count=len(table.df.columns),
                row_count=len(table.df),
            ))
    except Exception as e:
        logger.debug(f"Camelot stream failed for {page_range}: {e}")
    return results


def _try_pdfplumber(document_path: str, start_page: int, end_page: int, exclude_pages: set) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
    results = []
    try:
        import pdfplumber
        with pdfplumber.open(document_path) as pdf:
            for page_num in range(start_page, end_page + 1):
                if page_num in exclude_pages:
                    continue
                if page_num > len(pdf.pages):
                    break
                page = pdf.pages[page_num - 1]
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header = [str(c).strip() if c else "" for c in table[0]]
                    rows = [dict(zip(header, [str(c).strip() if c else "" for c in row])) for row in table[1:]]
                    results.append(RawTableResult(
                        source_page=page_num,
                        extraction_method="PDFPLUMBER",
                        raw_table_json=rows,
                        table_confidence=0.55,
                        column_count=len(header),
                        row_count=len(rows),
                    ))
    except Exception as e:
        logger.debug(f"pdfplumber failed for pages {start_page}-{end_page}: {e}")
    return results


def extract_text_from_pdf(document_path: str) -> str:
    """Extract full text from PDF for clause extraction. Returns empty string on failure."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(document_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        return ""


def _clean_rows(rows):
    """Convert all values to strings, strip whitespace."""
    return [{str(k).strip(): str(v).strip() for k, v in row.items()} for row in rows]


class PdfExtractor:
    """Backward-compatible wrapper for existing class-based extraction flows."""

    def extract_tables(self, document_path):
        return extract_tables_from_pdf(str(document_path))

    def extract_text(self, document_path):
        return extract_text_from_pdf(str(document_path))
