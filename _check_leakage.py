"""Quick check of leakage records."""
import requests
import json

with open("_doc_ids.txt") as f:
    content = f.read()

token = content.split("token=")[1].split("\n")[0]
run_id = content.split("run_id=")[1].split("\n")[0]
h = {"Authorization": f"Bearer {token}"}
BASE = "http://localhost:8000/api/v1"

# Summary
print("=== SUMMARY ===")
r = requests.get(f"{BASE}/leakage/summary", headers=h)
print(json.dumps(r.json(), indent=2))

# Records page 1
print("\n=== RECORDS (page 1 of 10) ===")
r = requests.get(f"{BASE}/leakage/records", headers=h, params={"run_id": run_id, "page": 1, "page_size": 10})
d = r.json()
print(f"Pagination: {json.dumps(d.get('pagination', {}))}")
print()
for rec in d.get("data", []):
    lt = rec["leakage_type"]
    amt = rec["amount"]
    conf = rec["confidence"]
    vendor = rec["vendor_name"]
    inv = rec["invoice_no"]
    expl = rec.get("explanation", "")[:80]
    print(f"  {lt:20s} | Amount: {amt:>12.2f} | Conf: {conf:.2f} | {vendor} | {inv}")
    print(f"    {expl}")

# Breakdown by type
print("\n=== BY LEAKAGE TYPE ===")
for lt in ["PRICE_MISMATCH", "QUANTITY_MISMATCH", "DUPLICATE_INVOICE"]:
    r = requests.get(f"{BASE}/leakage/records", headers=h, params={"leakage_type": lt, "page": 1, "page_size": 1})
    d = r.json()
    total = d.get("pagination", {}).get("total_records", 0)
    print(f"  {lt}: {total} records")
