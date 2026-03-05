"""Determinism Run 2 — trigger analysis on existing data and compare with Run 1."""
import requests, time, json, sys

BASE = "http://localhost:8000/api/v1"

# Login
auth_resp = requests.post(f"{BASE}/auth/token", json={
    "email": "admin@test.com",
    "password": "PZAD-QyiIWCBct2iRxvEkQ"
}).json()
token = auth_resp.get("access_token") or auth_resp.get("token")
print(f"Auth OK: token starts with {token[:20]}...")
h = {"Authorization": f"Bearer {token}"}

# Get existing document IDs (from the demo data upload)
print("\n=== Using existing document IDs ===")
doc_ids = [
    "cf8c4b83-711e-4c12-9ce1-57dfc80ba89c",  # CONTRACT
    "94091f44-3029-4a2c-a890-cefca7c72377",  # INVOICE
    "4d9ba15f-09bd-4ba3-aa11-79ca60491d67",  # PO
]
print(f"Using {len(doc_ids)} document IDs")

# Trigger run 2
print("\n=== Triggering Run 2 ===")
r = requests.post(
    f"{BASE}/ingest/trigger-run",
    headers=h,
    json={"document_ids": doc_ids, "run_label": "Determinism Run 2"},
)
print(f"Run 2 trigger: {r.status_code}")
if r.status_code not in (200, 201, 202):
    print(f"FAILED: {r.text[:500]}")
    sys.exit(1)
run2_id = r.json()["run_id"]
print(f"Run 2 ID: {run2_id}")

# Poll
status = "PENDING"
for i in range(60):
    time.sleep(5)
    st = requests.get(f"{BASE}/ingest/runs/{run2_id}/status", headers=h).json()
    status = st.get("status", "?")
    recs = st.get("leakage_record_count", 0)
    progress = st.get("progress_percentage", 0)
    sys.stdout.write(f"  [{i+1}] {status} -- progress: {progress}% -- records: {recs}        \r")
    sys.stdout.flush()
    if status in ("COMPLETE", "PARTIAL_SUCCESS", "FAILED"):
        print(f"\n  Final: {status} — {recs} leakage records found")
        break
else:
    print("\n  TIMEOUT!")
    sys.exit(1)

print(f"\nRun 2 final status: {status}")

# Get leakage records
all_records = []
page = 1
while True:
    resp = requests.get(
        f"{BASE}/leakage/records",
        headers=h,
        params={"run_id": run2_id, "page": page, "page_size": 200},
    )
    data = resp.json()
    records = data.get("data", [])
    if not records:
        break
    all_records.extend(records)
    if len(records) < 200:
        break
    page += 1

items = all_records
print(f"Run 2 leakage count: {len(items)}")

# Sort and display
run2_records = []
for rec in sorted(items, key=lambda x: (x.get("leakage_type", ""), x.get("invoice_no", ""))):
    entry = {
        "leakage_type": rec.get("leakage_type"),
        "invoice_no": rec.get("invoice_no"),
        "amount": float(rec.get("amount", 0)),
        "confidence": float(rec.get("confidence", 0)),
    }
    run2_records.append(entry)
    print(f"  {entry['leakage_type']:20s} {entry['invoice_no']:15s} {entry['amount']:>12,.2f}  conf={entry['confidence']}")

# Run 1 expected results (captured from DB)
run1_records = [
    {"leakage_type": "DUPLICATE_INVOICE", "invoice_no": "INV-DEMO-007", "amount": 56000.0, "confidence": 0.85},
    {"leakage_type": "DUPLICATE_INVOICE", "invoice_no": "INV-DEMO-018", "amount": 76000.0, "confidence": 0.85},
    {"leakage_type": "PRICE_MISMATCH", "invoice_no": "INV-DEMO-004", "amount": 7000.0, "confidence": 1.0},
    {"leakage_type": "PRICE_MISMATCH", "invoice_no": "INV-DEMO-012", "amount": 13000.0, "confidence": 1.0},
    {"leakage_type": "PRICE_MISMATCH", "invoice_no": "INV-DEMO-015", "amount": 7500.0, "confidence": 1.0},
    {"leakage_type": "QUANTITY_MISMATCH", "invoice_no": "INV-DEMO-019", "amount": 20000.0, "confidence": 0.9},
]

# Compare
print("\n=== DETERMINISM COMPARISON ===")
run1_sorted = sorted(run1_records, key=lambda x: (x["leakage_type"], x["invoice_no"]))
run2_sorted = sorted(run2_records, key=lambda x: (x["leakage_type"], x["invoice_no"]))

if len(run1_sorted) != len(run2_sorted):
    print(f"FAIL: Record count differs — Run 1: {len(run1_sorted)}, Run 2: {len(run2_sorted)}")
else:
    all_match = True
    for r1, r2 in zip(run1_sorted, run2_sorted):
        type_ok = r1["leakage_type"] == r2["leakage_type"]
        inv_ok = r1["invoice_no"] == r2["invoice_no"]
        amt_ok = abs(r1["amount"] - r2["amount"]) < 0.01
        conf_ok = abs(r1["confidence"] - r2["confidence"]) < 0.01
        ok = type_ok and inv_ok and amt_ok and conf_ok
        symbol = "MATCH" if ok else "DIFF"
        if not ok:
            all_match = False
        print(f"  {symbol}: {r1['leakage_type']:20s} {r1['invoice_no']:15s} Run1={r1['amount']:>10,.2f} Run2={r2['amount']:>10,.2f}")

    if all_match:
        print(f"\nDETERMINISM: PASS — Both runs produced identical 6 records with matching amounts and confidence scores")
    else:
        print(f"\nDETERMINISM: FAIL — Records differ between runs")
