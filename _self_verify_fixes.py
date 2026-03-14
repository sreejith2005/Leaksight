from datetime import date

import requests

BASE = "http://localhost:8000/api/v1"


def main() -> int:
    print("=== Health ===")
    h = requests.get(f"{BASE}/health", timeout=5)
    print(h.status_code, h.text[:200])
    if h.status_code != 200:
        return 1

    print("=== Auth ===")
    auth = requests.post(
        f"{BASE}/auth/token",
        json={"email": "admin@demo.leaksight.io", "password": "AdminPass123!"},
        timeout=10,
    )
    print("AUTH", auth.status_code)
    if auth.status_code != 200:
        print(auth.text)
        return 1

    token = auth.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    print("=== Pick run ===")
    runs = requests.get(f"{BASE}/ingest/runs?page=1&page_size=20", headers=headers, timeout=10)
    print("RUNS", runs.status_code)
    if runs.status_code != 200:
        print(runs.text)
        return 1

    run_data = runs.json().get("data", [])
    completed = [r for r in run_data if r.get("status") in ("COMPLETE", "PARTIAL_SUCCESS")]

    if completed:
        run_id = completed[0]["run_id"]
        print("Using run:", run_id)

        pdf = requests.get(f"{BASE}/reports/runs/{run_id}/evidence-pack", headers=headers, timeout=20)
        print("PDF", pdf.status_code)
        try:
            print("PDF body", pdf.json())
        except Exception:
            print("PDF bytes", len(pdf.content))

        xls = requests.get(f"{BASE}/reports/runs/{run_id}/export-excel", headers=headers, timeout=20)
        print("XLS", xls.status_code, xls.headers.get("content-type"), len(xls.content))
    else:
        print("No completed runs available; skipping report checks")

    print("=== FX tests ===")
    today = str(date.today())

    payload_ok = {
        "rates": [
            {
                "from_currency": "AUD",
                "to_currency": "CAD",
                "rate": 0.91,
                "rate_date": today,
                "source": "MANUAL_UPLOAD",
            }
        ]
    }

    r1 = requests.post(f"{BASE}/admin/fx-rates/upload", headers=headers, json=payload_ok, timeout=10)
    print("FX create", r1.status_code, r1.text[:300])

    r2 = requests.post(f"{BASE}/admin/fx-rates/upload", headers=headers, json=payload_ok, timeout=10)
    print("FX duplicate", r2.status_code, r2.text[:300])

    payload_neg = {
        "rates": [
            {
                "from_currency": "GBP",
                "to_currency": "EUR",
                "rate": -1,
                "rate_date": today,
                "source": "MANUAL_UPLOAD",
            }
        ]
    }

    r3 = requests.post(f"{BASE}/admin/fx-rates/upload", headers=headers, json=payload_neg, timeout=10)
    print("FX negative", r3.status_code, r3.text[:300])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
