import sys
from pathlib import Path


def _load_items(result, normalizer):
    tables = list(getattr(result, "tables", []) or [])
    line_items = list(getattr(result, "line_items", []) or [])
    if line_items:
        return line_items
    return normalizer.normalize(tables, document_text=getattr(result, "text", "") or "")


def _assert_price_retention(items, label: str, threshold: float) -> None:
    assert len(items) > 0, f"{label}: zero items extracted"
    items_with_price = [item for item in items if item.get("unit_price") is not None]
    assert len(items_with_price) > 0, f"{label}: all extracted items have null unit_price"
    price_retention = len(items_with_price) / len(items)
    assert price_retention >= threshold, (
        f"{label}: only {price_retention:.0%} of items have a price"
        f" - expected >= {threshold:.0%}"
    )


def verify_docx(path: str) -> None:
    from backend.app.tools.contract_structuring.extractors.docx_extractor import DOCXExtractor
    from backend.app.tools.contract_structuring.extractors.table_normalizer import TableNormalizer

    result = DOCXExtractor().extract(path)
    items = _load_items(result, TableNormalizer())

    _assert_price_retention(items, f"DOCX:{path}", 0.70)
    priced = [item for item in items if item.get("unit_price") is not None]
    currencies = sorted({item.get("currency") for item in priced if item.get("currency")})
    print(f"DOCX PASS: {len(items)} items, {len(priced)} with prices")
    print(f"  Currencies found: {currencies}")
    for item in items[:4]:
        print(f"  {item.get('item_description')} | {item.get('unit_price')} | {item.get('currency')}")


def verify_excel(path: str) -> None:
    from backend.app.tools.contract_structuring.extractors.excel_extractor import ExcelExtractor
    from backend.app.tools.contract_structuring.extractors.table_normalizer import TableNormalizer

    result = ExcelExtractor().extract(path)
    items = _load_items(result, TableNormalizer())

    _assert_price_retention(items, f"EXCEL:{path}", 0.80)
    priced = [item for item in items if item.get("unit_price") is not None]
    print(f"Excel PASS: {len(items)} items, {len(priced)} with prices")


def verify_pdf(path: str) -> None:
    from backend.app.tools.contract_structuring.extractors.pdf_extractor import PDFExtractor
    from backend.app.tools.contract_structuring.extractors.table_normalizer import TableNormalizer

    result = PDFExtractor().extract(path)
    items = _load_items(result, TableNormalizer())

    assert len(items) > 0, f"PDF:{path}: zero items extracted"
    priced = [item for item in items if item.get("unit_price") is not None]
    assert len(priced) > 0, f"PDF:{path}: extracted items exist but all prices are null"
    print(f"PDF PASS: {len(items)} items, {len(priced)} with prices")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: .venv\\Scripts\\python.exe _verify_extraction_universal.py <docx|dummy> [xlsx|dummy] [pdf|dummy]")
        return 0

    slots = (args + ["dummy", "dummy", "dummy"])[:3]
    results: dict[str, str] = {}

    if slots[0] != "dummy" and slots[0].lower().endswith(".docx"):
        verify_docx(slots[0])
        results["docx"] = "PASS"
    if slots[1] != "dummy" and slots[1].lower().endswith((".xlsx", ".xls", ".csv")):
        verify_excel(slots[1])
        results["excel"] = "PASS"
    if slots[2] != "dummy" and slots[2].lower().endswith(".pdf"):
        verify_pdf(slots[2])
        results["pdf"] = "PASS"

    print("\n=== RESULTS ===")
    for key, value in results.items():
        print(f"  {key}: {value}")

    if results and all(value == "PASS" for value in results.values()):
        print("\nAll format verifications PASSED")
        return 0

    if not results:
        print("\nNo matching input documents were provided")
        return 0

    print("\nSome verifications FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
