"""Upload demo data to LeakSight V1 and trigger analysis.

Steps:
1. Authenticate
2. Upload Contracts_Demo.xlsx (doc_type=CONTRACT)
3. Upload Invoices_Demo.xlsx (doc_type=INVOICE) — single file, 20 invoices
4. Upload PO_Demo.xlsx (doc_type=PO)
5. Wait for parsing + normalization to complete
6. Trigger analysis run
7. Poll until complete
8. Fetch and display leakage results
9. Compare against expected output (6 findings)
10. Save demo run ID
"""
import requests
import json
import time
import sys
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
DEMO_DIR = Path(__file__).resolve().parent / "data" / "demo"

# ── Step 1: Login ──
print("=== STEP 1: LOGIN ===")
resp = requests.post(f"{BASE}/auth/token", json={
    "email": "admin@test.com",
    "password": "PZAD-QyiIWCBct2iRxvEkQ",
})
if resp.status_code != 200:
    print(f"Auth FAILED: {resp.status_code} {resp.text[:300]}")
    sys.exit(1)
token = resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"Token acquired: {token[:20]}...")

# ── Step 2: Upload Contracts ──
print("\n=== STEP 2: UPLOAD CONTRACTS ===")
contract_path = DEMO_DIR / "Contracts_Demo.xlsx"
with open(contract_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/ingest/upload",
        headers=headers,
        files={"file": ("Contracts_Demo.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "CONTRACT"},
    )
print(f"Status: {resp.status_code}")
if resp.status_code not in (200, 201):
    print(f"FAILED: {resp.text[:500]}")
    sys.exit(1)
contract_doc_id = resp.json().get("document_id")
print(f"Contract doc_id: {contract_doc_id}")

# ── Step 3: Upload Invoices (single file, 20 invoices) ──
print("\n=== STEP 3: UPLOAD INVOICES ===")
invoice_path = DEMO_DIR / "Invoices_Demo.xlsx"
with open(invoice_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/ingest/upload",
        headers=headers,
        files={"file": ("Invoices_Demo.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "INVOICE"},
    )
print(f"Status: {resp.status_code}")
if resp.status_code not in (200, 201):
    print(f"FAILED: {resp.text[:500]}")
    sys.exit(1)
invoice_doc_id = resp.json().get("document_id")
print(f"Invoice doc_id: {invoice_doc_id}")

# ── Step 4: Upload POs ──
print("\n=== STEP 4: UPLOAD POs ===")
po_path = DEMO_DIR / "PO_Demo.xlsx"
with open(po_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/ingest/upload",
        headers=headers,
        files={"file": ("PO_Demo.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "PO"},
    )
print(f"Status: {resp.status_code}")
if resp.status_code not in (200, 201):
    print(f"FAILED: {resp.text[:500]}")
    sys.exit(1)
po_doc_id = resp.json().get("document_id")
print(f"PO doc_id: {po_doc_id}")

# ── Step 5: Wait for parsing + normalization ──
print("\n=== STEP 5: WAITING FOR PARSE + NORMALIZATION (45s) ===")
for i in range(9):
    time.sleep(5)
    sys.stdout.write(f"  [{(i+1)*5}s]...")
    sys.stdout.flush()
print(" Done")

# ── Step 6: Trigger analysis ──
print("\n=== STEP 6: TRIGGER ANALYSIS RUN ===")
doc_ids = [d for d in [contract_doc_id, invoice_doc_id, po_doc_id] if d]
resp = requests.post(
    f"{BASE}/ingest/trigger-run",
    headers=headers,
    json={"document_ids": doc_ids, "run_label": "Demo Dataset Analysis"},
)
print(f"Status: {resp.status_code}")
if resp.status_code not in (200, 201, 202):
    print(f"FAILED: {resp.text[:500]}")
    sys.exit(1)
run_id = resp.json()["run_id"]
print(f"Run ID: {run_id}")

# ── Step 7: Poll for completion ──
print("\n=== STEP 7: POLLING RUN STATUS ===")
for i in range(120):
    time.sleep(5)
    resp = requests.get(f"{BASE}/ingest/runs/{run_id}/status", headers=headers)
    data = resp.json()
    status = data.get("status", "UNKNOWN")
    count = data.get("leakage_record_count", 0)
    progress = data.get("progress_percentage", 0)
    sys.stdout.write(f"  [{i+1}] {status} | Progress: {progress}% | Records: {count}        \r")
    sys.stdout.flush()
    if status in ("COMPLETE", "PARTIAL_SUCCESS", "FAILED"):
        print(f"\n  Final: {status} — {count} leakage records found")
        break
else:
    print("\n  TIMEOUT after 10 minutes!")
    sys.exit(1)

if status == "FAILED":
    print(f"  Run details: {json.dumps(data, indent=2, default=str)}")
    sys.exit(1)

# ── Step 8: Fetch results ──
print("\n=== STEP 8: LEAKAGE RESULTS ===")
all_records = []
page = 1
while True:
    resp = requests.get(
        f"{BASE}/leakage/records",
        headers=headers,
        params={"run_id": run_id, "page": page, "page_size": 200},
    )
    data = resp.json()
    records = data.get("data", [])
    if not records:
        break
    all_records.extend(records)
    if len(records) < 200:
        break
    page += 1

print(f"Total leakage records: {len(all_records)}\n")

# Group by type
by_type = {}
for r in all_records:
    lt = r.get("leakage_type", "UNKNOWN")
    by_type.setdefault(lt, []).append(r)

for lt in sorted(by_type.keys()):
    recs = by_type[lt]
    total = sum(float(r.get("amount", 0)) for r in recs)
    print(f"{lt}: {len(recs)} records, total ₹{total:,.2f}")
    for r in recs:
        inv = r.get("invoice_no", "?")
        vendor = r.get("vendor_name", "?")
        amt = float(r.get("amount", 0))
        conf = r.get("confidence", 0)
        print(f"  {inv} | {vendor} | ₹{amt:,.2f} | conf={conf}")

# ── Step 9: Compare against expected ──
print("\n=== STEP 9: COMPARISON WITH EXPECTED OUTPUT ===")

# For PRICE/QTY mismatches, match on exact invoice_no.
# For DUPLICATE_INVOICE (near-dupes), match on rule + vendor_contains + amount
# because the flagged invoice could be either member of the pair.
expected = [
    {"rule": "PRICE_MISMATCH", "match": "invoice", "invoice": "INV-DEMO-004", "amount": 7000.00, "label": "PM INV-DEMO-004 TechServ 7,000"},
    {"rule": "PRICE_MISMATCH", "match": "invoice", "invoice": "INV-DEMO-012", "amount": 13000.00, "label": "PM INV-DEMO-012 BuildRight 13,000"},
    {"rule": "PRICE_MISMATCH", "match": "invoice", "invoice": "INV-DEMO-015", "amount": 7500.00, "label": "PM INV-DEMO-015 Acme 7,500"},
    {"rule": "DUPLICATE_INVOICE", "match": "vendor_amount", "vendor_contains": "acme", "amount": 56000.00, "invoices": ["INV-DEMO-003", "INV-DEMO-007"], "label": "DUP Acme pair 56,000"},
    {"rule": "DUPLICATE_INVOICE", "match": "vendor_amount", "vendor_contains": "buildright", "amount": 76000.00, "invoices": ["INV-DEMO-011", "INV-DEMO-018"], "label": "DUP BuildRight pair 76,000"},
    {"rule": "QUANTITY_MISMATCH", "match": "invoice", "invoice": "INV-DEMO-019", "amount": 20000.00, "label": "QM INV-DEMO-019 BuildRight 20,000"},
]

matched = 0
issues = []
used_record_ids = set()

for exp in expected:
    found = False
    for r in all_records:
        rid = r.get("id", "")
        if rid in used_record_ids:
            continue
        inv = r.get("invoice_no", "")
        lt = r.get("leakage_type", "")
        amt = float(r.get("amount", 0))
        vendor = (r.get("vendor_name") or "").lower()

        if lt != exp["rule"]:
            continue

        if exp["match"] == "invoice":
            if inv != exp["invoice"]:
                continue
        elif exp["match"] == "vendor_amount":
            if exp["vendor_contains"] not in vendor:
                continue
            if inv not in exp.get("invoices", []):
                continue

        if abs(amt - exp["amount"]) < 1.0:
            print(f"  MATCH: {exp['label']} -> found on {inv}")
            matched += 1
            used_record_ids.add(rid)
            found = True
            break
        else:
            msg = f"  AMOUNT DIFF: {exp['label']}: expected {exp['amount']:,.2f}, got {amt:,.2f}"
            print(msg)
            issues.append(msg)
            found = True
            break

    if not found:
        msg = f"  MISSING: {exp['label']}"
        print(msg)
        issues.append(msg)

# Check for unexpected extras
extra = [r for r in all_records if r.get("id", "") not in used_record_ids]

print(f"\nMatched: {matched}/{len(expected)}")
if extra:
    print(f"Extra records (unexpected): {len(extra)}")
    for r in extra:
        inv = r.get("invoice_no", "?")
        lt = r.get("leakage_type", "?")
        amt = float(r.get("amount", 0))
        print(f"  EXTRA: {lt} {inv} {amt:,.2f}")

if matched == len(expected) and not extra:
    print("\nRESULT: PASS — System output matches expected demo leakage exactly")
elif matched == len(expected):
    print(f"\nRESULT: PARTIAL PASS — All {len(expected)} expected matched, but {len(extra)} extra record(s)")
else:
    print(f"\nRESULT: ISSUES FOUND — {len(issues)} discrepancies")

# ── Step 10: Save demo run ID ──
print(f"\n=== STEP 10: SAVING DEMO RUN ID ===")
run_id_file = Path(__file__).resolve().parent / "DEMO_RUN_ID.txt"
with open(run_id_file, "w") as f:
    f.write(f"demo_run_id={run_id}\n")
    f.write(f"demo_date=2026-03-04\n")
    f.write(f"contract_doc_id={contract_doc_id}\n")
    f.write(f"invoice_doc_id={invoice_doc_id}\n")
    f.write(f"po_doc_id={po_doc_id}\n")
    f.write(f"expected_records={len(expected)}\n")
    f.write(f"actual_records={len(all_records)}\n")
    f.write(f"matched={matched}\n")
    f.write(f"extras={len(extra)}\n")
    f.write(f"result={'PASS' if matched == len(expected) and not extra else 'ISSUES'}\n")
print(f"Saved to {run_id_file}")
print(f"Demo Run ID: {run_id}")
