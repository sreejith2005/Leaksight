"""End-to-end Tool A demo verifier for Phase 7."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests


BASE = "http://localhost:8000/api/v1"
DEMO_DIR = Path(__file__).resolve().parent / "data" / "demo_tool_a"

AUTH_EMAIL = "admin@test.com"
AUTH_PASSWORD = "PZAD-QyiIWCBct2iRxvEkQ"

EXPECTED_PRICE_MAP = {
    "Steel Pipe 20mm": {850.0, 920.0},
    "Steel Pipe 40mm": {1200.0},
    "Gate Valve": {3500.0, 3800.0},
    "Ball Valve": {4200.0},
    "Safety Helmet": {650.0, 720.0},
    "Safety Harness": {2800.0},
    "Pipe Fitting Elbow": {320.0},
    "Pipe Fitting Tee": {280.0},
}


def _print_json_block(title: str, payload: object) -> None:
    print(f"{title}: {json.dumps(payload, default=str)}")


def _must_exist(path: Path) -> None:
    if not path.exists():
        print(f"Missing demo file: {path}")
        print("Run _generate_tool_a_demo_data.py first.")
        raise SystemExit(1)


def _post_upload(headers: dict[str, str], file_path: Path) -> str:
    with file_path.open("rb") as handle:
        response = requests.post(
            f"{BASE}/ingest/upload",
            headers=headers,
            files={
                "file": (
                    file_path.name,
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"doc_type": "CONTRACT"},
            timeout=120,
        )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed for {file_path.name}: {response.status_code} {response.text[:400]}")
    return str(response.json().get("document_id"))


def main() -> int:
    file_v1 = DEMO_DIR / "CTR-TOOL-001_v1.xlsx"
    file_v2 = DEMO_DIR / "CTR-TOOL-001_v2_amendment.xlsx"
    _must_exist(file_v1)
    _must_exist(file_v2)

    extracted_total = 0
    confirmed_total = 0
    written_total = 0
    overall_pass = True

    print("STEP 1: LOGIN")
    auth_response = requests.post(
        f"{BASE}/auth/token",
        json={"email": AUTH_EMAIL, "password": AUTH_PASSWORD},
        timeout=60,
    )
    if auth_response.status_code != 200:
        print(f"  Auth failed: {auth_response.status_code} {auth_response.text[:300]}")
        return 1
    token = auth_response.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    print("  Token acquired")

    print("\nSTEP 2: UPLOAD CONTRACT V1")
    doc_v1 = _post_upload(headers, file_v1)
    print(f"  doc_id: {doc_v1}")

    print("\nSTEP 3: UPLOAD CONTRACT V2 AMENDMENT")
    doc_v2 = _post_upload(headers, file_v2)
    print(f"  doc_id: {doc_v2}")

    print("\nSTEP 4: CREATE STRUCTURING RUN")
    run_response = requests.post(
        f"{BASE}/structuring/runs",
        headers=headers,
        json={
            "document_ids": [doc_v1, doc_v2],
            "run_label": "Acme Supplies Demo Run",
        },
        timeout=60,
    )
    if run_response.status_code not in (200, 201):
        print(f"  Failed to create run: {run_response.status_code} {run_response.text[:300]}")
        return 1
    run_id = run_response.json().get("id")
    print(f"  run_id: {run_id}")

    print("\nSTEP 5: POLL RUN STATUS")
    terminal_statuses = {"COMPLETE", "PARTIAL_SUCCESS", "FAILED"}
    start_time = time.time()
    status_payload = {}
    while True:
        if time.time() - start_time > 300:
            print("  Timeout after 5 minutes")
            return 1
        status_response = requests.get(
            f"{BASE}/structuring/runs/{run_id}/status",
            headers=headers,
            timeout=30,
        )
        status_payload = status_response.json() if status_response.ok else {}
        run_status = str(status_payload.get("status", "UNKNOWN"))
        print(
            "  "
            f"status={run_status} "
            f"processed={status_payload.get('processed_documents', 0)}/{status_payload.get('total_documents', 0)} "
            f"line_items={status_payload.get('total_line_items_found', 0)}"
        )
        if run_status in terminal_statuses:
            break
        time.sleep(3)

    if str(status_payload.get("status")) == "FAILED":
        print("  Run failed")
        _print_json_block("  status_payload", status_payload)
        return 1

    print("\nSTEP 6: VERIFY EXTRACTION RESULTS")
    results_response = requests.get(
        f"{BASE}/structuring/runs/{run_id}/results",
        headers=headers,
        timeout=60,
    )
    if results_response.status_code != 200:
        print(f"  Failed to fetch results: {results_response.status_code} {results_response.text[:300]}")
        return 1

    results_payload = results_response.json()
    documents = results_payload.get("documents", [])

    by_doc_count: dict[str, int] = {}
    all_items: list[dict] = []
    for document in documents:
        document_id = str(document.get("document_id"))
        line_items = document.get("line_items", [])
        by_doc_count[document_id] = len(line_items)
        all_items.extend(line_items)

    extracted_total = len(all_items)
    v1_count = by_doc_count.get(doc_v1, 0)
    v2_count = by_doc_count.get(doc_v2, 0)
    print(f"  Extracted counts: v1={v1_count}, v2={v2_count}, total={extracted_total}")
    if v1_count < 8 or v2_count < 3:
        overall_pass = False
        print("  FAIL: expected at least 8 line items from v1 and 3 from v2")

    for item in all_items:
        contract_id = item.get("contract_id") or "-"
        desc = (item.get("item_description") or "").strip()
        unit = item.get("unit_raw") or "-"
        price_raw = item.get("unit_price")
        confidence = min(
            float(item.get("item_confidence", 0.0)),
            float(item.get("price_confidence", 0.0)),
            float(item.get("unit_confidence", 0.0)),
        )

        try:
            price = float(price_raw) if price_raw is not None else None
        except Exception:
            price = None

        expected_prices = EXPECTED_PRICE_MAP.get(desc)
        pass_fail = "PASS" if (expected_prices and price in expected_prices and unit == "Nos") else "FAIL"
        if pass_fail == "FAIL":
            overall_pass = False

        print(
            "  "
            f"Contract_ID={contract_id} | Item={desc or '-'} | Unit={unit} | "
            f"Price={price if price is not None else '-'} | Confidence={confidence:.2f} | {pass_fail}"
        )

    print("\nSTEP 7: CONFIRM ALL HIGH-CONFIDENCE ITEMS")
    confirm_candidates = [
        item for item in all_items
        if min(
            float(item.get("item_confidence", 0.0)),
            float(item.get("price_confidence", 0.0)),
            float(item.get("unit_confidence", 0.0)),
        ) >= 0.85
    ]

    for item in confirm_candidates:
        item_id = item.get("id")
        confirm_response = requests.post(
            f"{BASE}/structuring/line-items/{item_id}/confirm",
            headers=headers,
            timeout=30,
        )
        if confirm_response.status_code == 200:
            confirmed_total += 1
        else:
            overall_pass = False
            print(f"  confirm failed for {item_id}: {confirm_response.status_code} {confirm_response.text[:200]}")

    print(f"  confirmed {confirmed_total} items")

    print("\nSTEP 8: TRIGGER LEAKSIGHT IMPORT")
    export_trigger_response = requests.post(
        f"{BASE}/structuring/runs/{run_id}/export/leaksight-import",
        headers=headers,
        timeout=30,
    )
    print(f"  triggered, response status: {export_trigger_response.status_code}")
    if export_trigger_response.status_code not in (200, 202):
        overall_pass = False

    print("\nSTEP 9: WAIT FOR IMPORT TO COMPLETE")
    for _ in range(10):
        time.sleep(3)
    exports_response = requests.get(
        f"{BASE}/structuring/runs/{run_id}/exports",
        headers=headers,
        timeout=30,
    )
    if exports_response.status_code != 200:
        overall_pass = False
        print(f"  failed to list exports: {exports_response.status_code} {exports_response.text[:200]}")
        exports_payload = []
    else:
        exports_payload = exports_response.json()
    print(f"  exports list: {json.dumps(exports_payload, default=str)}")

    print("\nSTEP 10: VERIFY CANONICAL CONTRACTS")
    contracts_response = requests.get(f"{BASE}/contracts/", headers=headers, timeout=60)
    if contracts_response.status_code != 200:
        print(f"  FAIL: contracts endpoint failed: {contracts_response.status_code}")
        return 1
    contracts_payload = contracts_response.json().get("data", [])

    matched_contracts = [
        contract
        for contract in contracts_payload
        if "CTR-TOOL-001" in str(contract.get("contract_ref") or "")
    ]
    if matched_contracts:
        print("  PASS: CTR-TOOL-001 found in /api/v1/contracts/")
        for contract in matched_contracts:
            print(f"  matching contract: {json.dumps(contract, default=str)}")
    else:
        overall_pass = False
        print("  FAIL: CTR-TOOL-001 not found in /api/v1/contracts/")

    for contract in matched_contracts:
        contract_id = contract.get("id")
        if not contract_id:
            continue
        versions_response = requests.get(f"{BASE}/contracts/{contract_id}/versions", headers=headers, timeout=60)
        if versions_response.status_code != 200:
            continue
        versions = versions_response.json().get("versions", [])
        for version in versions:
            written_total += len(version.get("line_items", []))

    print("\nSTEP 11: FINAL SUMMARY")
    print(f"  Items extracted:  {extracted_total}")
    print(f"  Items confirmed:  {confirmed_total}")
    print(f"  Written to canonical contracts: {written_total}")
    print(f"  CTR-TOOL-001 in /api/v1/contracts/: {'YES' if matched_contracts else 'NO'}")

    if extracted_total >= 11 and confirmed_total >= 8 and written_total >= 8 and matched_contracts and overall_pass:
        print("RESULT: PASS")
        return 0

    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.RequestException as exc:
        print(f"Network/request error: {exc}")
        sys.exit(1)
