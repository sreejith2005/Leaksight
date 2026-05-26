import asyncio
import sys

from backend.app.tools.contract_structuring.extractors.pdf_extractor import PdfExtractor


def _get_tables(result):
    if hasattr(result, "tables"):
        return list(getattr(result, "tables") or [])
    if hasattr(result, "raw_tables"):
        return list(getattr(result, "raw_tables") or [])
    if isinstance(result, list):
        return result
    return []


def _get_rows(table):
    if hasattr(table, "rows"):
        return list(getattr(table, "rows") or [])
    if hasattr(table, "raw_table_json"):
        return list(getattr(table, "raw_table_json") or [])
    return []


def _get_headers(table):
    if hasattr(table, "headers"):
        return list(getattr(table, "headers") or [])
    rows = _get_rows(table)
    if rows and isinstance(rows[0], dict):
        return list(rows[0].keys())
    return []


async def run():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not pdf_path:
        print("Usage: script.py <path_to_pdf>")
        return

    extractor = PdfExtractor()
    result = extractor.extract(pdf_path) if hasattr(extractor, "extract") else extractor.extract_tables(pdf_path)

    tables = _get_tables(result)
    confidence = getattr(result, "confidence", None)
    failure_flags = getattr(result, "failure_flags", None)

    print("Tables found:", len(tables))
    print("Total rows:", sum(len(_get_rows(t)) for t in tables))
    print("Confidence:", confidence)
    print("Failure flags:", failure_flags)
    for i, table in enumerate(tables):
        rows = _get_rows(table)
        print(f"Table {i}: {len(rows)} rows, headers: {_get_headers(table)}")
        if rows:
            print("  First 3 rows:", rows[:3])


asyncio.run(run())
