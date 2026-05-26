"""
Excel/CSV extractor with dynamic header detection across every sheet.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List

from backend.app.tools.contract_structuring.extractors.base_extractor import (
    DocumentExtractionResult,
    ExtractedClauseResult,
    RawTableResult,
)
from backend.app.tools.contract_structuring.extractors.table_normalizer import normalize_tables_detailed

logger = logging.getLogger(__name__)

CLAUSE_COLUMN_ALIASES = {
    "VENDOR_NAME": ["vendor_name", "vendor"],
    "EFFECTIVE_DATE": ["effective_start_date", "start_date", "effective_from"],
    "EXPIRY_DATE": ["effective_end_date", "end_date", "expiry_date"],
    "CONTRACT_REF": ["contract_id", "contract_ref"],
}


def _normalize_column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _clean_cell(value) -> str:
    return str(value or "").strip()


def _sanitize_headers(values: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, value in enumerate(values, start=1):
        header = _clean_cell(value) or f"column_{index}"
        seen[header] = seen.get(header, 0) + 1
        if seen[header] > 1:
            header = f"{header}_{seen[header]}"
        headers.append(header)
    return headers


def _is_numeric_like(value: str) -> bool:
    text = _clean_cell(value)
    if not text:
        return False
    return bool(re.fullmatch(r"(?:[A-Za-z$₹€£]{0,8}\s*)?[\d,]+(?:\.\d+)?", text))


def _detect_header_row(df) -> int:
    max_rows = min(len(df.index), 10)
    for row_index in range(max_rows):
        values = [_clean_cell(value) for value in df.iloc[row_index].tolist()]
        non_empty = [value for value in values if value]
        if not non_empty:
            continue
        string_cells = sum(1 for value in non_empty if not _is_numeric_like(value))
        if string_cells / len(non_empty) > 0.5:
            return row_index
    return 0


def _row_is_blank(row: dict[str, str]) -> bool:
    return not any(_clean_cell(value) for value in row.values())


def _sheet_has_numeric_values(rows: list[dict[str, str]]) -> bool:
    return any(_is_numeric_like(value) for row in rows for value in row.values())


def _load_sheet_frames(document_path: str) -> list[tuple[str, "pd.DataFrame"]]:
    import pandas as pd

    if document_path.lower().endswith(".csv"):
        sheets = {"Sheet1": pd.read_csv(document_path, header=None, dtype=str, keep_default_na=False)}
    else:
        sheets = pd.read_excel(document_path, sheet_name=None, header=None, dtype=str, keep_default_na=False)

    loaded: list[tuple[str, "pd.DataFrame"]] = []
    for sheet_name, df in sheets.items():
        if df is None or df.empty:
            continue
        loaded.append((sheet_name, df.fillna("")))
    return loaded


def _frame_to_rows(df) -> tuple[list[dict[str, str]], list[str], int]:
    header_row_index = _detect_header_row(df)
    headers = _sanitize_headers(df.iloc[header_row_index].tolist())
    rows: list[dict[str, str]] = []
    for row_index in range(header_row_index + 1, len(df.index)):
        values = df.iloc[row_index].tolist()
        row = {
            headers[column_index]: _clean_cell(values[column_index]) if column_index < len(values) else ""
            for column_index in range(len(headers))
        }
        if _row_is_blank(row):
            continue
        rows.append(row)
    return rows, headers, header_row_index


def _first_non_empty_value(series) -> str | None:
    seen: set[str] = set()
    for raw_value in series:
        value = _clean_cell(raw_value)
        if not value or value in seen:
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
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
            return date.fromisoformat(stripped).isoformat()
        parsed = dateparser.parse(stripped, dayfirst=not bool(re.match(r"^\d{4}\D", stripped)))
        if parsed is None:
            return None
        return parsed.date().isoformat()
    except Exception:
        logger.debug("Unable to normalize Excel clause date: %s", value)
        return None


def extract_clauses_from_excel(document_path: str) -> List[ExtractedClauseResult]:
    clauses: list[ExtractedClauseResult] = []
    emitted: set[str] = set()

    try:
        for sheet_index, (sheet_name, df) in enumerate(_load_sheet_frames(document_path), start=1):
            header_row_index = _detect_header_row(df)
            headers = _sanitize_headers(df.iloc[header_row_index].tolist())
            records = [
                {
                    headers[column_index]: _clean_cell(row_values[column_index]) if column_index < len(row_values) else ""
                    for column_index in range(len(headers))
                }
                for row_values in df.iloc[header_row_index + 1 :].values.tolist()
            ]
            if not records:
                continue

            normalized_columns: Dict[str, str] = {_normalize_column_name(column): column for column in headers}
            for clause_type, aliases in CLAUSE_COLUMN_ALIASES.items():
                if clause_type in emitted:
                    continue
                source_column = next((normalized_columns[alias] for alias in aliases if alias in normalized_columns), None)
                if source_column is None:
                    continue
                raw_value = _first_non_empty_value(record.get(source_column) for record in records)
                if raw_value is None:
                    continue
                extracted_value = raw_value
                if clause_type in {"EFFECTIVE_DATE", "EXPIRY_DATE"}:
                    extracted_value = _format_clause_date(raw_value)
                    if extracted_value is None:
                        continue
                clauses.append(
                    ExtractedClauseResult(
                        clause_type=clause_type,
                        raw_text=f"{sheet_name}:{source_column}",
                        extracted_value=extracted_value,
                        source_page=sheet_index,
                        confidence=0.90,
                        needs_review=False,
                    )
                )
                emitted.add(clause_type)
    except Exception as exc:
        logger.error("Excel clause extraction failed: %s", exc)

    return clauses


def _extract_excel_document(document_path: str) -> DocumentExtractionResult:
    raw_tables: list[RawTableResult] = []
    failure_flags: list[str] = []

    try:
        for sheet_index, (sheet_name, df) in enumerate(_load_sheet_frames(document_path), start=1):
            rows, headers, header_row_index = _frame_to_rows(df)
            if not headers:
                failure_flags.append(f"EMPTY_SHEET_SKIPPED:{sheet_name}")
                continue

            source_row_count = sum(
                1
                for row_values in df.iloc[header_row_index + 1 :].values.tolist()
                if any(_clean_cell(value) for value in row_values)
            )

            table_confidence = 0.65 if _sheet_has_numeric_values(rows) else 0.45
            raw_tables.append(
                RawTableResult(
                    source_page=sheet_index,
                    extraction_method="EXCEL_SHEET",
                    raw_table_json=rows,
                    table_confidence=table_confidence,
                    column_count=len(headers),
                    row_count=len(rows),
                    source_name=sheet_name,
                    source_row_count=source_row_count,
                )
            )
    except Exception as exc:
        logger.error("Excel extraction failed: %s", exc)
        failure_flags.append(f"EXCEL_EXTRACTION_FAILED:{type(exc).__name__}")

    clauses = extract_clauses_from_excel(document_path)
    normalization = normalize_tables_detailed(raw_tables, stitched=False)
    failure_flags.extend(normalization.failure_flags)

    return DocumentExtractionResult(
        tables=raw_tables,
        line_items=normalization.line_items,
        clauses=clauses,
        confidence=normalization.confidence,
        failure_flags=list(dict.fromkeys(failure_flags)),
        text="\n".join(" ".join(row.values()) for table in raw_tables for row in table.raw_table_json),
    )


def extract_tables_from_excel(document_path: str) -> List[RawTableResult]:
    return _extract_excel_document(document_path).tables


class ExcelExtractor:
    def extract_tables(self, document_path):
        return extract_tables_from_excel(str(document_path))

    def extract_text(self, document_path):
        return _extract_excel_document(str(document_path)).text

    def extract_clauses(self, document_path):
        return extract_clauses_from_excel(str(document_path))

    def extract(self, document_path, _tenant_id=None):
        return _extract_excel_document(str(document_path))
