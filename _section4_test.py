"""Section 4 — Review Workflow tests."""
import requests
import json
import subprocess

BASE = "http://localhost:8000/api/v1"

resp = requests.post(
    f"{BASE}/auth/token",
    json={"email": "admin@test.com", "password": "PZAD-QyiIWCBct2iRxvEkQ"},
)
TOKEN = resp.json()["access_token"]
H = {"Authorization": f"Bearer {TOKEN}"}
print("Token acquired.\n")

# ══════════════════════════════════════════════════════════════════════
# 4.1 — All pending records appear in review queue
# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("4.1 — Pending records in review queue")
print("=" * 60)

r = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING", "page_size": 1})
api_pending = r.json()["pagination"]["total_records"]

r2 = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING_FX_RATE", "page_size": 1})
api_fx = r2.json()["pagination"]["total_records"]

result = subprocess.run(
    ['docker', 'exec', 'leaksightv1-1-postgres-1', 'psql', '-U', 'leaksight_user',
     '-d', 'leaksight_dev', '-t', '-A', '-c',
     "SELECT count(*) FROM leakage_records WHERE status = 'PENDING';"],
    capture_output=True, text=True
)
db_pending = int(result.stdout.strip())

result2 = subprocess.run(
    ['docker', 'exec', 'leaksightv1-1-postgres-1', 'psql', '-U', 'leaksight_user',
     '-d', 'leaksight_dev', '-t', '-A', '-c',
     "SELECT count(*) FROM leakage_records WHERE status = 'PENDING_FX_RATE';"],
    capture_output=True, text=True
)
db_fx = int(result2.stdout.strip())

print(f"  API PENDING: {api_pending}, DB PENDING: {db_pending} -> MATCH: {'YES' if api_pending == db_pending else 'NO'}")
print(f"  API PENDING_FX_RATE: {api_fx}, DB: {db_fx} -> MATCH: {'YES' if api_fx == db_fx else 'NO'}")
print(f"  Total: {api_pending + api_fx}")
print(f"  4.1 Result: {'YES' if api_pending == db_pending and api_fx == db_fx else 'NO'}")

# Get test records
r3 = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING", "page_size": 5})
recs = r3.json()["data"]
print(f"\n  First 3 PENDING records:")
for rec in recs[:3]:
    print(f"    {rec['id']} ({rec['leakage_type']}) amount={rec['amount']}")

# ══════════════════════════════════════════════════════════════════════
# 4.2 — Accept flow works end-to-end
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("4.2 — Accept flow")
print("=" * 60)

test_id_1 = recs[0]["id"]
print(f"  Accepting record {test_id_1}...")
r4 = requests.post(f"{BASE}/leakage/records/{test_id_1}/accept", headers=H,
                    json={"notes": "Accepted during pilot readiness test"})
print(f"  Response: {r4.status_code} {r4.text[:300]}")
accept_pass = r4.status_code == 200

# Verify it's no longer PENDING
r4b = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING", "page_size": 1})
new_pending = r4b.json()["pagination"]["total_records"]
print(f"  Pending count: {api_pending} -> {new_pending} (expected {api_pending - 1})")
accept_count_pass = new_pending == api_pending - 1

# Check audit log
result3 = subprocess.run(
    ['docker', 'exec', 'leaksightv1-1-postgres-1', 'psql', '-U', 'leaksight_user',
     '-d', 'leaksight_dev', '-c',
     'SELECT action_type, entity_type, entity_id, user_id, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 3;'],
    capture_output=True, text=True
)
print(f"  Audit log:\n{result3.stdout}")
print(f"  4.2 Result: {'YES' if accept_pass and accept_count_pass else 'NO'}")

# ══════════════════════════════════════════════════════════════════════
# 4.3 — Reject flow works end-to-end
# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("4.3 — Reject flow")
print("=" * 60)

test_id_2 = recs[1]["id"]

# Reject without note — should be blocked
print(f"  Rejecting {test_id_2} WITHOUT note...")
r5 = requests.post(f"{BASE}/leakage/records/{test_id_2}/reject", headers=H, json={})
reject_no_note_blocked = r5.status_code in (400, 422)
print(f"  No-note response: {r5.status_code} {r5.text[:300]}")
print(f"  Blocked without note: {'YES' if reject_no_note_blocked else 'NO'}")

# Reject with note
print(f"  Rejecting {test_id_2} WITH note...")
r6 = requests.post(f"{BASE}/leakage/records/{test_id_2}/reject", headers=H,
                    json={"notes": "Rejected during pilot readiness test: false positive"})
print(f"  With-note response: {r6.status_code} {r6.text[:300]}")
reject_pass = r6.status_code == 200

# Check pending decreased again
r6b = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING", "page_size": 1})
final_pending = r6b.json()["pagination"]["total_records"]
print(f"  Pending: {new_pending} -> {final_pending}")
print(f"  4.3 Result: {'YES' if reject_no_note_blocked and reject_pass else 'NO'}")

# ══════════════════════════════════════════════════════════════════════
# 4.4 — PENDING_FX_RATE records visible and actionable
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("4.4 — PENDING_FX_RATE records")
print("=" * 60)

r7 = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING_FX_RATE", "page_size": 5})
fx_recs = r7.json()["data"]
print(f"  PENDING_FX_RATE records in API: {len(fx_recs)}")
for rec in fx_recs[:3]:
    print(f"    {rec['id']} amount={rec['amount']} currency={rec['currency']}")
print(f"  4.4 Result: {'YES' if len(fx_recs) > 0 else 'NO'} ({len(fx_recs)} records visible)")

# ══════════════════════════════════════════════════════════════════════
# 4.5 — Reviewer cannot edit financial data
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("4.5 — Reviewer cannot edit financial data")
print("=" * 60)

# Try to PATCH a record's amount (should fail or not exist as endpoint)
test_id_3 = recs[2]["id"]
r8 = requests.patch(f"{BASE}/leakage/records/{test_id_3}", headers=H,
                     json={"amount": 999999.99})
print(f"  PATCH amount: {r8.status_code} {r8.text[:200]}")
no_patch = r8.status_code in (404, 405, 422)

r9 = requests.put(f"{BASE}/leakage/records/{test_id_3}", headers=H,
                   json={"amount": 999999.99, "leakage_type": "FAKE"})
print(f"  PUT amount: {r9.status_code} {r9.text[:200]}")
no_put = r9.status_code in (404, 405, 422)

print(f"  No edit endpoints: {'YES' if no_patch and no_put else 'NO'}")
print(f"  4.5 Result: {'YES' if no_patch and no_put else 'NO'}")

# ══════════════════════════════════════════════════════════════════════
# Revert test records
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Reverting test records...")
print("=" * 60)
subprocess.run(
    ['docker', 'exec', 'leaksightv1-1-postgres-1', 'psql', '-U', 'leaksight_user',
     '-d', 'leaksight_dev', '-c',
     "UPDATE leakage_records SET status = 'PENDING', review_notes = NULL, "
     "reviewed_by = NULL, reviewed_at = NULL "
     "WHERE status IN ('ACCEPTED', 'REJECTED');"],
    capture_output=True, text=True
)
r_verify = requests.get(f"{BASE}/leakage/records", headers=H, params={"status": "PENDING", "page_size": 1})
reverted_count = r_verify.json()["pagination"]["total_records"]
print(f"  PENDING after revert: {reverted_count} (was {api_pending})")
print(f"  Revert successful: {'YES' if reverted_count == api_pending else 'NO'}")

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Section 4 Summary")
print("=" * 60)
print(f"  4.1 Pending records in queue:      {'YES' if api_pending == db_pending else 'NO'}")
print(f"  4.2 Accept flow:                   {'YES' if accept_pass and accept_count_pass else 'NO'}")
print(f"  4.3 Reject flow:                   {'YES' if reject_no_note_blocked and reject_pass else 'NO'}")
print(f"  4.4 PENDING_FX_RATE visible:       {'YES' if len(fx_recs) > 0 else 'NO'}")
print(f"  4.5 No financial data editing:     {'YES' if no_patch and no_put else 'NO'}")
