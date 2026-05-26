"""Upload PO test data and trigger analysis for LeakSight V1."""
import requests
import sys
import json
import time

BASE = "http://localhost:8000/api/v1"

# Step 1: Login
print("=== LOGIN ===")
resp = requests.post(f"{BASE}/auth/token", json={
    "email": "admin@test.com",
    "password": "PZAD-QyiIWCBct2iRxvEkQ",
    "tenant_name": "Test Client",
})
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"Error: {resp.text}")
    sys.exit(1)
data = resp.json()
token = data["access_token"]
print(f"Token: {token[:30]}...")

headers = {"Authorization": f"Bearer {token}"}

# Step 2: Upload PO file
print("\n=== UPLOAD PO DATA ===")
po_path = r"C:\Users\LENOVO\Downloads\PO_Test_Data.xlsx"
with open(po_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/ingest/upload",
        headers=headers,
        files={"file": ("PO_Test_Data.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "PO"},
    )
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")
if resp.status_code not in (200, 201):
    print("PO UPLOAD FAILED")
    sys.exit(1)
po_doc_id = resp.json().get("document_id")
print(f"PO document_id: {po_doc_id}")

# Step 3: Wait for parse + normalization to complete
print("\n=== WAITING FOR PARSE + NORMALIZATION (30s) ===")
time.sleep(30)
print("Done waiting")

# Verify PO data was created
print("\n=== VERIFY PO DATA ===")
import subprocess
result = subprocess.run(
    ['docker', 'exec', 'leaksightv1-1-postgres-1', 'psql', '-U', 'leaksight_user', '-d', 'leaksight_dev', '-t', '-c',
     "SELECT (SELECT count(*) FROM purchase_orders) as pos, (SELECT count(*) FROM po_line_items) as po_lines;"],
    capture_output=True, text=True
)
print(f"PO counts: {result.stdout.strip()}")

# Step 4: Read existing doc_ids to get contract and invoice doc IDs
print("\n=== READING EXISTING DOC IDS ===")
with open("_doc_ids.txt") as f:
    lines = f.read().strip().split("\n")
    doc_ids = {}
    for line in lines:
        if "=" in line:
            key, val = line.split("=", 1)
            doc_ids[key] = val

contract_doc_id = doc_ids.get("contract_doc_id")
invoice_doc_id = doc_ids.get("invoice_doc_id")
print(f"Contract doc: {contract_doc_id}")
print(f"Invoice doc: {invoice_doc_id}")
print(f"PO doc: {po_doc_id}")

# Step 5: Trigger analysis run with all three document types
print("\n=== TRIGGER ANALYSIS RUN ===")
doc_list = [d for d in [contract_doc_id, invoice_doc_id, po_doc_id] if d]
resp = requests.post(
    f"{BASE}/ingest/trigger-run",
    headers=headers,
    json={
        "document_ids": doc_list,
        "run_label": "Full Test Run with PO Data"
    }
)
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")

if resp.status_code not in (200, 201, 202):
    print("TRIGGER FAILED")
    sys.exit(1)

run_id = resp.json()["run_id"]
print(f"\nRun ID: {run_id}")

# Step 6: Poll for completion
print("\n=== POLLING RUN STATUS ===")
max_polls = 120  # max 10 minutes
for i in range(max_polls):
    time.sleep(5)
    resp = requests.get(f"{BASE}/ingest/runs/{run_id}/status", headers=headers)
    status_data = resp.json()
    status = status_data.get("status", "UNKNOWN")
    progress = status_data.get("progress_percentage", 0)
    leakage_count = status_data.get("leakage_record_count", 0)
    total_leakage = status_data.get("total_leakage_found", 0)
    
    print(f"  [{i+1}] Status: {status} | Progress: {progress}% | Leakage: {leakage_count} | Amount: {total_leakage}")
    
    if status in ("COMPLETE", "PARTIAL_SUCCESS", "FAILED"):
        print(f"\n=== RUN FINISHED: {status} ===")
        print(json.dumps(status_data, indent=2))
        break
else:
    print("Timeout waiting for analysis to complete")

# Step 7: Fetch leakage summary
print("\n=== LEAKAGE SUMMARY ===")
resp = requests.get(f"{BASE}/leakage/summary", headers=headers, params={"run_id": run_id})
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print(json.dumps(resp.json(), indent=2))
else:
    print(f"Error: {resp.text}")

# Step 8: Count by type
print("\n=== LEAKAGE BY TYPE ===")
for ltype in ["PRICE_MISMATCH", "DUPLICATE_INVOICE", "QUANTITY_MISMATCH"]:
    resp = requests.get(
        f"{BASE}/leakage/records",
        headers=headers,
        params={"run_id": run_id, "leakage_type": ltype, "page": 1, "page_size": 1}
    )
    if resp.status_code == 200:
        data = resp.json()
        total = data.get("total", data.get("total_count", "?"))
        print(f"  {ltype}: {total}")

# Save
with open("_doc_ids.txt", "a") as f:
    f.write(f"\npo_doc_id={po_doc_id}\n")
    f.write(f"run_id={run_id}\n")
print(f"\nIDs saved to _doc_ids.txt")
