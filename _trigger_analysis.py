"""Trigger analysis run for LeakSight V1."""
import requests
import sys
import json
import time

BASE = "http://localhost:8000/api/v1"

# Read saved doc IDs and token
with open("_doc_ids.txt") as f:
    lines = f.read().strip().split("\n")
    doc_ids = {}
    for line in lines:
        key, val = line.split("=", 1)
        doc_ids[key] = val

token = doc_ids["token"]
contract_doc_id = doc_ids["contract_doc_id"]
invoice_doc_id = doc_ids["invoice_doc_id"]

headers = {"Authorization": f"Bearer {token}"}

# Step 1: Trigger analysis run
print("=== TRIGGER ANALYSIS RUN ===")
resp = requests.post(
    f"{BASE}/ingest/trigger-run",
    headers=headers,
    json={
        "document_ids": [contract_doc_id, invoice_doc_id],
        "run_label": "Initial MVP Test Run"
    }
)
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")

if resp.status_code not in (200, 201, 202):
    print("TRIGGER FAILED")
    sys.exit(1)

run_id = resp.json()["run_id"]
print(f"\nRun ID: {run_id}")

# Step 2: Poll for completion
print("\n=== POLLING RUN STATUS ===")
max_polls = 60  # max 5 minutes
for i in range(max_polls):
    time.sleep(5)
    resp = requests.get(f"{BASE}/ingest/runs/{run_id}/status", headers=headers)
    status_data = resp.json()
    status = status_data.get("status", "UNKNOWN")
    progress = status_data.get("progress_percentage", 0)
    leakage_count = status_data.get("leakage_record_count", 0)
    total_leakage = status_data.get("total_leakage_found", 0)
    
    print(f"  [{i+1}] Status: {status} | Progress: {progress}% | Leakage records: {leakage_count} | Total leakage: {total_leakage}")
    
    if status in ("COMPLETE", "PARTIAL_SUCCESS", "FAILED"):
        print(f"\n=== RUN FINISHED: {status} ===")
        print(json.dumps(status_data, indent=2))
        break
else:
    print("Timeout waiting for analysis to complete")

# Step 3: Fetch leakage summary
print("\n=== LEAKAGE SUMMARY ===")
resp = requests.get(f"{BASE}/leakage/summary", headers=headers, params={"run_id": run_id})
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print(json.dumps(resp.json(), indent=2))
else:
    print(f"Error: {resp.text}")

# Step 4: Fetch first page of leakage records
print("\n=== LEAKAGE RECORDS (page 1) ===")
resp = requests.get(
    f"{BASE}/leakage/records",
    headers=headers,
    params={"run_id": run_id, "page": 1, "page_size": 20}
)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    records = data.get("records", data.get("items", data if isinstance(data, list) else []))
    if isinstance(records, list):
        print(f"Total records on this page: {len(records)}")
        for rec in records[:5]:
            print(f"  - Type: {rec.get('leakage_type', 'N/A')} | Amount: {rec.get('leakage_amount', 'N/A')} | Status: {rec.get('review_status', 'N/A')}")
    else:
        print(json.dumps(data, indent=2)[:2000])
else:
    print(f"Error: {resp.text}")

# Save run_id
with open("_doc_ids.txt", "a") as f:
    f.write(f"run_id={run_id}\n")
print(f"\nRun ID saved to _doc_ids.txt")
