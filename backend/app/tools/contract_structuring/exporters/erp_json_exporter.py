"""ERP JSON/CSV exporters for Tool A."""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def export_erp_json(
    output_path: str | Path,
    run_id: str,
    tenant_id: str,
    contracts_payload: list[dict[str, Any]],
) -> str:
    payload = {
        "export_metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "tenant_id": tenant_id,
            "format_version": "1.0",
            "tool": "LeakSight Tool A",
        },
        "contracts": contracts_payload,
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(out)


def export_erp_csv(output_path: str | Path, rows: list[dict[str, Any]]) -> str:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "vendor_name",
        "contract_reference",
        "effective_date",
        "expiry_date",
        "version",
        "source_document",
        "item_description",
        "unit",
        "unit_price",
        "currency",
        "source_page",
        "confidence",
    ]
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(out)
