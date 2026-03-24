"""
Excel/CSV table extractor using pandas and openpyxl.
Each sheet is treated as a potential pricing table.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

PRICING_HEADER_KEYWORDS = [
    'item', 'description', 'particulars', 'material',
    'unit', 'uom', 'rate', 'price', 'unit price', 'amount', 'qty', 'quantity'
]


def extract_tables_from_excel(document_path: str) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
    results = []
    try:
        import pandas as pd
        if document_path.endswith('.csv'):
            sheets = {'Sheet1': pd.read_csv(document_path, dtype=str)}
        else:
            sheets = pd.read_excel(document_path, sheet_name=None, dtype=str)

        for sheet_idx, (sheet_name, df) in enumerate(sheets.items()):
            df = df.dropna(how='all').fillna('')
            if df.empty or len(df) < 2:
                continue
            header = [str(c).strip().lower() for c in df.columns]
            confidence = _score_pricing_sheet(header)
            if confidence < 0.2:
                continue
            rows = df.to_dict('records')
            rows_clean = [{str(k).strip(): str(v).strip() for k, v in row.items()} for row in rows]
            results.append(RawTableResult(
                source_page=sheet_idx + 1,
                extraction_method="EXCEL_SHEET",
                raw_table_json=rows_clean,
                table_confidence=confidence,
                column_count=len(df.columns),
                row_count=len(df),
            ))
    except Exception as e:
        logger.error(f"Excel extraction failed: {e}")
    return results


def _score_pricing_sheet(header: List[str]) -> float:
    matches = sum(1 for h in header if any(kw in h for kw in PRICING_HEADER_KEYWORDS))
    return min(1.0, matches / max(1, len(header)) * 2)


class ExcelExtractor:
    """Backward-compatible wrapper for existing class-based extraction flows."""

    def extract_tables(self, document_path):
        return extract_tables_from_excel(str(document_path))

    def extract_text(self, document_path):
        tables = extract_tables_from_excel(str(document_path))
        text_rows = []
        for table in tables:
            for row in table.raw_table_json:
                text_rows.append(" ".join(str(v) for v in row.values() if str(v).strip()))
        return "\n".join(text_rows)
