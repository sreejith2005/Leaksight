"""Check leakage results - final summary."""
import requests
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("_doc_ids.txt") as f:
    content = f.read()

token = content.split("token=")[1].split("\n")[0]
run_id = content.split("run_id=")[1].split("\n")[0]
h = {"Authorization": f"Bearer {token}"}
BASE = "http://localhost:8000/api/v1"

# Summary (without run_id filter)
print("=== SUMMARY (no run_id filter) ===")
r = requests.get(f"{BASE}/leakage/summary", headers=h)
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Summary with run_id filter
print("\n=== SUMMARY (with run_id) ===")
r = requests.get(f"{BASE}/leakage/summary", headers=h, params={"run_id": run_id})
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Breakdown by type
print("\n=== BREAKDOWN BY LEAKAGE TYPE ===")
for lt in ["PRICE_MISMATCH", "QUANTITY_MISMATCH", "DUPLICATE_INVOICE"]:
    r = requests.get(f"{BASE}/leakage/records", headers=h, params={"leakage_type": lt, "page": 1, "page_size": 1})
    d = r.json()
    total = d.get("pagination", {}).get("total_records", 0)
    print(f"  {lt}: {total} records")

# Show 3 sample records
print("\n=== SAMPLE RECORDS ===")
r = requests.get(f"{BASE}/leakage/records", headers=h, params={"page": 1, "page_size": 5})
d = r.json()
for rec in d.get("data", []):
    print(f"\n  Type: {rec['leakage_type']}")
    print(f"  Amount: {rec['amount']}")
    print(f"  Confidence: {rec['confidence']}")
    print(f"  Vendor: {rec['vendor_name']}")
    print(f"  Invoice: {rec['invoice_no']}")
    print(f"  Rule: {rec['rule_applied']}")
    expl = rec.get('explanation', '')
    # Truncate and replace non-ASCII
    expl_safe = expl.encode('ascii', 'replace').decode('ascii')[:120]
    print(f"  Explanation: {expl_safe}")

# Show some duplicates
print("\n=== SAMPLE DUPLICATE RECORDS ===")
r = requests.get(f"{BASE}/leakage/records", headers=h, params={"leakage_type": "DUPLICATE_INVOICE", "page": 1, "page_size": 3})
d = r.json()
for rec in d.get("data", []):
    print(f"\n  Invoice: {rec['invoice_no']} | Amount: {rec['amount']} | Vendor: {rec['vendor_name']}")

print("\n=== COMPLETE ===")
print(f"Total leakage records in DB: {d.get('pagination', {}).get('total_records', 'N/A')}")
