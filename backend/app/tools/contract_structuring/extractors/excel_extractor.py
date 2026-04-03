"""
Excel/CSV table extractor using pandas and openpyxl.
Each sheet is treated as a potential pricing table.
"""
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

PRICING_HEADER_KEYWORDS = [
    'item', 'description', 'particulars', 'material',
    'unit', 'uom', 'rate', 'price', 'unit price', 'amount', 'qty', 'quantity'
]

CLAUSE_COLUMN_ALIASES = {
    'VENDOR_NAME': ['vendor_name', 'vendor'],
    'EFFECTIVE_DATE': ['effective_start_date', 'start_date', 'effective_from'],
    'EXPIRY_DATE': ['effective_end_date', 'end_date', 'expiry_date'],
    'CONTRACT_REF': ['contract_id'],
}


@dataclass
class ExcelExtractionResult:
    raw_tables: List
    line_items: List
    clauses: List


def _normalize_column_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', (value or '').strip().lower()).strip('_')


def _load_excel_sheets(document_path: str) -> List[Tuple[str, "pd.DataFrame"]]:
    import pandas as pd

    if document_path.endswith('.csv'):
        sheets = {'Sheet1': pd.read_csv(document_path, dtype=str)}
    else:
        sheets = pd.read_excel(document_path, sheet_name=None, dtype=str)

    cleaned_sheets: List[Tuple[str, "pd.DataFrame"]] = []
    for sheet_name, df in sheets.items():
        df = df.dropna(how='all').fillna('')
        if df.empty:
            continue
        cleaned_sheets.append((sheet_name, df))
    return cleaned_sheets


def _first_non_empty_value(series) -> str | None:
    seen: set[str] = set()
    for raw_value in series:
        value = str(raw_value).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        return value
    return None


def _format_clause_date(value: str) -> str | None:
    if not value:
        return None

    try:
        from datetime import date
        from dateutil import parser as dateparser

        stripped = value.strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', stripped):
            return date.fromisoformat(stripped).isoformat()
        if re.fullmatch(r'\d{4}/\d{2}/\d{2}', stripped):
            return date.fromisoformat(stripped.replace('/', '-')).isoformat()

        parsed = dateparser.parse(
            stripped,
            dayfirst=not bool(re.match(r'^\d{4}\D', stripped)),
            yearfirst=bool(re.match(r'^\d{4}\D', stripped)),
        )
        if parsed is None:
            return None
        return parsed.date().isoformat()
    except Exception:
        logger.debug("Unable to normalize Excel clause date: %s", value)
        return None


def extract_clauses_from_excel(document_path: str) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import ExtractedClauseResult

    results = []
    emitted_clause_types: set[str] = set()

    try:
        for sheet_index, (sheet_name, df) in enumerate(_load_excel_sheets(document_path), start=1):
            normalized_columns: Dict[str, str] = {
                _normalize_column_name(column): str(column).strip()
                for column in df.columns
            }

            for clause_type, aliases in CLAUSE_COLUMN_ALIASES.items():
                if clause_type in emitted_clause_types:
                    continue

                source_column = next(
                    (normalized_columns[alias] for alias in aliases if alias in normalized_columns),
                    None,
                )
                if source_column is None:
                    continue

                raw_value = _first_non_empty_value(df[source_column].tolist())
                if raw_value is None:
                    continue

                extracted_value = raw_value
                if clause_type in {'EFFECTIVE_DATE', 'EXPIRY_DATE'}:
                    extracted_value = _format_clause_date(raw_value)
                    if extracted_value is None:
                        continue

                results.append(
                    ExtractedClauseResult(
                        clause_type=clause_type,
                        raw_text=f"{sheet_name}:{source_column}",
                        extracted_value=extracted_value,
                        source_page=sheet_index,
                        confidence=0.90,
                        needs_review=False,
                    )
                )
                emitted_clause_types.add(clause_type)
    except Exception as e:
        logger.error(f"Excel clause extraction failed: {e}")

    return results


def extract_tables_from_excel(document_path: str) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
    results = []
    try:
        for sheet_idx, (_sheet_name, df) in enumerate(_load_excel_sheets(document_path)):
            if len(df) < 2:
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

    def extract_clauses(self, document_path):
        return extract_clauses_from_excel(str(document_path))

    def extract(self, document_path, _tenant_id=None):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import normalize_tables

        raw_tables = extract_tables_from_excel(str(document_path))
        line_items = normalize_tables(raw_tables, stitched=False)
        clauses = extract_clauses_from_excel(str(document_path))
        return ExcelExtractionResult(
            raw_tables=raw_tables,
            line_items=line_items,
            clauses=clauses,
        )
