"""Generate deterministic Tool A demo dataset for Phase 7."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


HEADERS = [
    "Contract_ID",
    "Vendor_Name",
    "Item_Description",
    "Unit",
    "Unit_Price",
    "Currency",
    "Effective_Start_Date",
    "Effective_End_Date",
]


def _write_workbook(path: Path, sheet_name: str, rows: list[tuple]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name

    worksheet.append(HEADERS)
    for row in rows:
        worksheet.append(list(row))

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def main() -> int:
    out_dir = Path(__file__).resolve().parent / "data" / "demo_tool_a"

    file_v1 = out_dir / "CTR-TOOL-001_v1.xlsx"
    file_v2 = out_dir / "CTR-TOOL-001_v2_amendment.xlsx"

    rows_v1 = [
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Steel Pipe 20mm", "Nos", 850.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Steel Pipe 40mm", "Nos", 1200.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Gate Valve", "Nos", 3500.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Ball Valve", "Nos", 4200.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Safety Helmet", "Nos", 650.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Safety Harness", "Nos", 2800.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Pipe Fitting Elbow", "Nos", 320.00, "INR", "2024-04-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Pipe Fitting Tee", "Nos", 280.00, "INR", "2024-04-01", "2026-03-31"),
    ]

    rows_v2 = [
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Steel Pipe 20mm", "Nos", 920.00, "INR", "2024-10-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Gate Valve", "Nos", 3800.00, "INR", "2024-10-01", "2026-03-31"),
        ("CTR-TOOL-001", "Acme Supplies Ltd", "Safety Helmet", "Nos", 720.00, "INR", "2024-10-01", "2026-03-31"),
    ]

    _write_workbook(file_v1, "Contracts", rows_v1)
    _write_workbook(file_v2, "Amendment", rows_v2)

    rel_v1 = file_v1.relative_to(Path(__file__).resolve().parent).as_posix()
    rel_v2 = file_v2.relative_to(Path(__file__).resolve().parent).as_posix()

    print(f"Generated: {rel_v1} ({len(rows_v1)} rows)")
    print(f"Generated: {rel_v2} ({len(rows_v2)} rows)")
    print("Demo data ready in data/demo_tool_a/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
