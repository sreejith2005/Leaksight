import asyncio
from pathlib import Path

from backend.app.tools.contract_structuring.extractors.excel_extractor import ExcelExtractor


def _get_tables(result):
    if hasattr(result, "tables"):
        return list(getattr(result, "tables") or [])
    if hasattr(result, "raw_tables"):
        return list(getattr(result, "raw_tables") or [])
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
    path = Path("data/demo_tool_a/CTR-TOOL-001_v1.xlsx")
    if not path.exists():
        print("Demo file not found, looking for any xlsx in data/")
        found = list(Path("data").rglob("*.xlsx"))
        print("Found:", found)
        return

    extractor = ExcelExtractor()
    result = extractor.extract(str(path))

    tables = _get_tables(result)
    confidence = getattr(result, "confidence", None)

    print("Tables found:", len(tables))
    print("Total rows across all tables:", sum(len(_get_rows(t)) for t in tables))
    print("Confidence:", confidence)
    for i, table in enumerate(tables):
        print(f"Table {i}: {len(_get_rows(table))} rows, headers: {_get_headers(table)}")


asyncio.run(run())
