"""Determinism test: run analysis twice, compare results byte-for-byte."""
import requests
import json
import time
import sys
import subprocess

BASE = "http://localhost:8000/api/v1"

# Get fresh token
def get_token():
    resp = requests.post(
        f"{BASE}/auth/token",
        json={"email": "admin@test.com", "password": "PZAD-QyiIWCBct2iRxvEkQ"},
    )
    if resp.status_code != 200:
        print(f"Auth failed: {resp.status_code} {resp.text[:300]}")
        sys.exit(1)
    return resp.json()["access_token"]

TOKEN = get_token()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
print(f"Token acquired: {TOKEN[:20]}...")

CONTRACT_DOC = "b6a49b44-a813-4c7f-9e6e-6c0882eb6615"
INVOICE_DOC = "8c9403f2-5290-40b3-a86a-6240443b8a62"
PO_DOC = "07033120-3ab8-4634-968f-75d1c9cb1e54"
DOC_IDS = [CONTRACT_DOC, INVOICE_DOC, PO_DOC]


def wipe():
    """Wipe leakage_records & analysis_runs, keep documents."""
    cmd = (
        'docker exec leaksightv1-1-postgres-1 psql -U leaksight_user -d leaksight_dev -c '
        '"DELETE FROM leakage_records; DELETE FROM notifications; '
        'UPDATE documents SET run_id = NULL WHERE run_id IS NOT NULL; '
        'DELETE FROM analysis_runs;"'
    )
    subprocess.run(cmd, shell=True, check=True, capture_output=True)
    print("  DB wiped")


def trigger_and_wait():
    """Trigger analysis run and wait for completion. Returns run_id."""
    resp = requests.post(
        f"{BASE}/ingest/trigger-run",
        headers=HEADERS,
        json={"document_ids": DOC_IDS, "run_label": "Determinism Test"},
    )
    if resp.status_code not in (200, 201, 202):
        print(f"  TRIGGER FAILED: {resp.status_code} {resp.text[:500]}")
        sys.exit(1)

    run_id = resp.json()["run_id"]
    print(f"  Run ID: {run_id}")

    for i in range(120):  # up to 10 minutes
        time.sleep(5)
        resp = requests.get(f"{BASE}/ingest/runs/{run_id}/status", headers=HEADERS)
        data = resp.json()
        st = data.get("status", "UNKNOWN")
        count = data.get("leakage_record_count", 0)
        sys.stdout.write(f"  [{i+1}] {st} -- {count} records        \r")
        sys.stdout.flush()
        if st in ("COMPLETE", "PARTIAL_SUCCESS", "FAILED"):
            print(f"\n  Final: {st} -- {count} records")
            return run_id
    print("\n  TIMEOUT")
    sys.exit(1)


def export_leakage(run_id, filename):
    """Export all leakage records for this run via API, sorted deterministically."""
    all_records = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE}/leakage/records",
            headers=HEADERS,
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

    # Remove fields that naturally differ between runs (id, run_id, timestamps)
    cleaned = []
    for r in all_records:
        cleaned.append({
            "leakage_type": r.get("leakage_type"),
            "amount": r.get("amount"),
            "currency": r.get("currency"),
            "confidence": r.get("confidence"),
            "status": r.get("status"),
            "rule_applied": r.get("rule_applied"),
            "explanation": r.get("explanation"),
            "vendor_name": r.get("vendor_name"),
            "invoice_no": r.get("invoice_no"),
            "invoice_date": r.get("invoice_date"),
        })

    # Sort by deterministic composite key
    cleaned.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))

    with open(filename, "w") as f:
        json.dump(cleaned, f, indent=2, sort_keys=True, default=str)

    print(f"  Exported {len(cleaned)} records to {filename}")
    return cleaned


# Also export via SQL for a more thorough comparison (includes evidence_jsonb)
def export_via_sql(run_id, filename):
    """Export leakage records via direct SQL for full evidence comparison."""
    cmd = (
        f'docker exec leaksightv1-1-postgres-1 psql -U leaksight_user -d leaksight_dev '
        f"-t -A -c \"SELECT leakage_type, amount, currency, confidence, status, "
        f"rule_applied, explanation, evidence_jsonb "
        f"FROM leakage_records WHERE run_id = '{run_id}' "
        f"ORDER BY leakage_type, amount, explanation, evidence_jsonb::text;\""
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    with open(filename, "w") as f:
        f.write(result.stdout)
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    print(f"  SQL exported {len(lines)} records to {filename}")
    return result.stdout


# ── Run 1 ──
print("=== RUN 1 ===")
wipe()
run1_id = trigger_and_wait()
run1_api = export_leakage(run1_id, "_run1_determinism.json")
run1_sql = export_via_sql(run1_id, "_run1_determinism_sql.txt")

# ── Run 2 ──
print("\n=== RUN 2 ===")
wipe()
run2_id = trigger_and_wait()
run2_api = export_leakage(run2_id, "_run2_determinism.json")
run2_sql = export_via_sql(run2_id, "_run2_determinism_sql.txt")

# ── Compare API export ──
print("\n=== API COMPARISON ===")
run1_json = json.dumps(run1_api, sort_keys=True, default=str)
run2_json = json.dumps(run2_api, sort_keys=True, default=str)

if run1_json == run2_json:
    print(f"  PASS -- API export identical ({len(run1_api)} records)")
else:
    print(f"  FAIL -- API export differs!")
    print(f"  Run 1: {len(run1_api)} records, Run 2: {len(run2_api)} records")
    for i, (r1, r2) in enumerate(zip(run1_api, run2_api)):
        if json.dumps(r1, sort_keys=True) != json.dumps(r2, sort_keys=True):
            print(f"\n  Record {i} differs:")
            for key in r1:
                if r1.get(key) != r2.get(key):
                    print(f"    {key}: {r1.get(key)} vs {r2.get(key)}")

# ── Compare SQL export ──
print("\n=== SQL COMPARISON ===")
if run1_sql == run2_sql:
    print(f"  PASS -- SQL export identical (byte-for-byte)")
else:
    print(f"  FAIL -- SQL export differs!")
    lines1 = run1_sql.strip().split("\n")
    lines2 = run2_sql.strip().split("\n")
    print(f"  Run 1: {len(lines1)} lines, Run 2: {len(lines2)} lines")
    diffs = 0
    for i, (l1, l2) in enumerate(zip(lines1, lines2)):
        if l1 != l2:
            diffs += 1
            if diffs <= 5:
                print(f"  Line {i}: DIFFER")
                print(f"    R1: {l1[:200]}")
                print(f"    R2: {l2[:200]}")
    if diffs > 5:
        print(f"  ... and {diffs - 5} more differences")
    if len(lines1) != len(lines2):
        print(f"  Line count mismatch: {len(lines1)} vs {len(lines2)}")

print("\n=== DONE ===")
