"""Quick upload test script for LeakSight V1."""
import requests
import sys
import json

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
print(f"Tenant: {data['user']['tenant_name']}")

headers = {"Authorization": f"Bearer {token}"}

# Step 2: Upload Contracts
print("\n=== UPLOAD CONTRACTS ===")
contracts_path = r"C:\Users\LENOVO\Downloads\Sample Contracts - LeakSight MVP Testing.xlsx"
with open(contracts_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/ingest/upload",
        headers=headers,
        files={"file": ("Sample Contracts - LeakSight MVP Testing.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "CONTRACT"},
    )
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")
if resp.status_code not in (200, 201):
    print("CONTRACT UPLOAD FAILED")
    sys.exit(1)
contract_doc_id = resp.json().get("document_id")
print(f"Contract document_id: {contract_doc_id}")

# Step 3: Upload Invoices
print("\n=== UPLOAD INVOICES ===")
invoices_path = r"C:\Users\LENOVO\Downloads\Sample Invoices - LeakSight MVP Testing.xlsx"
with open(invoices_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/ingest/upload",
        headers=headers,
        files={"file": ("Sample Invoices - LeakSight MVP Testing.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "INVOICE"},
    )
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")
if resp.status_code not in (200, 201):
    print("INVOICE UPLOAD FAILED")
    sys.exit(1)
invoice_doc_id = resp.json().get("document_id")
print(f"Invoice document_id: {invoice_doc_id}")

# Save document IDs for later
print(f"\n=== DONE ===")
print(f"Contract doc_id: {contract_doc_id}")
print(f"Invoice doc_id: {invoice_doc_id}")
print(f"\nParse tasks are now queued in Celery. Watch the Celery terminal for progress.")
print(f"Once both parse tasks complete, run _trigger_analysis.py to start the analysis.")

# Save IDs to a file
with open("_doc_ids.txt", "w") as f:
    f.write(f"contract_doc_id={contract_doc_id}\n")
    f.write(f"invoice_doc_id={invoice_doc_id}\n")
    f.write(f"token={token}\n")
print("Document IDs saved to _doc_ids.txt")
