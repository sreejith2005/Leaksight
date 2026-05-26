"""
Self-contained test script for FX rate endpoint.
Tests: create, duplicate detection, negative rate validation.
"""

import requests
import sys
from datetime import date, timedelta

BASE = "http://localhost:8000/api/v1"

# --- Authenticate ---
print("=== Authenticating ===")
auth_resp = requests.post(
    f"{BASE}/auth/token",
    json={"email": "admin@demo.leaksight.io", "password": "AdminPass123!"},
)
if auth_resp.status_code != 200:
    print(f"Auth failed: {auth_resp.status_code} {auth_resp.text}")
    sys.exit(1)
token = auth_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"Token obtained: {token[:20]}...")

# --- Test 1: Create FX rate (USD→EUR) ---
print("\n=== Test 1: POST new FX rate (USD→EUR, 0.92) ===")
test_date = date.today()
payload = {
    "rates": [
        {
            "from_currency": "USD",
            "to_currency": "EUR",
            "rate": 0.92,
            "rate_date": str(test_date),
            "source": "MANUAL_UPLOAD",
        }
    ]
}
resp = requests.post(f"{BASE}/admin/fx-rates/upload", json=payload, headers=headers)
print(f"Status: {resp.status_code}")
print(f"Body: {resp.json()}")
if resp.status_code == 409:
    # If today's USD/EUR already exists from prior UI/manual testing, shift one day.
    test_date = date.today() + timedelta(days=1)
    payload["rates"][0]["rate_date"] = str(test_date)
    resp = requests.post(f"{BASE}/admin/fx-rates/upload", json=payload, headers=headers)
    print(f"Retried with date {test_date} -> Status: {resp.status_code}")
    print(f"Body: {resp.json()}")

assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

# --- Test 2: Duplicate rate (same pair + date) ---
print("\n=== Test 2: POST duplicate FX rate (should be 409) ===")
resp2 = requests.post(f"{BASE}/admin/fx-rates/upload", json=payload, headers=headers)
print(f"Status: {resp2.status_code}")
print(f"Body: {resp2.json()}")
assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}"

# --- Test 3: Negative rate ---
print("\n=== Test 3: POST negative rate (should be 422) ===")
payload_neg = {
    "rates": [
        {
            "from_currency": "GBP",
            "to_currency": "EUR",
            "rate": -1,
            "rate_date": str(test_date),
            "source": "MANUAL_UPLOAD",
        }
    ]
}
resp3 = requests.post(f"{BASE}/admin/fx-rates/upload", json=payload_neg, headers=headers)
print(f"Status: {resp3.status_code}")
print(f"Body: {resp3.json()}")
assert resp3.status_code == 422, f"Expected 422, got {resp3.status_code}"

# --- Test 4: Same currency ---
print("\n=== Test 4: POST same from/to currency (should be 422) ===")
payload_same = {
    "rates": [
        {
            "from_currency": "USD",
            "to_currency": "USD",
            "rate": 1.0,
            "rate_date": str(test_date),
            "source": "MANUAL_UPLOAD",
        }
    ]
}
resp4 = requests.post(f"{BASE}/admin/fx-rates/upload", json=payload_same, headers=headers)
print(f"Status: {resp4.status_code}")
print(f"Body: {resp4.json()}")
assert resp4.status_code == 422, f"Expected 422, got {resp4.status_code}"

# --- Test 5: Invalid source value ---
print("\n=== Test 5: POST invalid source (should be 422) ===")
payload_bad_source = {
    "rates": [
        {
            "from_currency": "GBP",
            "to_currency": "INR",
            "rate": 105.5,
            "rate_date": str(test_date),
            "source": "manual",
        }
    ]
}
resp5 = requests.post(f"{BASE}/admin/fx-rates/upload", json=payload_bad_source, headers=headers)
print(f"Status: {resp5.status_code}")
print(f"Body: {resp5.json()}")
assert resp5.status_code == 422, f"Expected 422, got {resp5.status_code}"

print("\n=== ALL TESTS PASSED ===")
