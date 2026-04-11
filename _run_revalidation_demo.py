import sys
import time
from datetime import date, timedelta

import requests


AUTH_URL = 'http://localhost:8000/api/v1/auth/token'
BASE_URL = 'http://localhost:8000/api/v1/revalidation'
AUTH_EMAIL = 'admin@test.com'
AUTH_PASSWORD = 'PZAD-QyiIWCBct2iRxvEkQ'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def auth():
    r = requests.post(
        AUTH_URL,
        json={'email': AUTH_EMAIL, 'password': AUTH_PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    return {'Authorization': f'Bearer {r.json()["access_token"]}'}


def fail(message: str) -> int:
    print(f'Assertion failed: {message}')
    print('Demo FAILED')
    return 1


def expect_response(response: requests.Response, expected_status: int | tuple[int, ...], label: str) -> dict:
    allowed = expected_status if isinstance(expected_status, tuple) else (expected_status,)
    if response.status_code not in allowed:
        raise RuntimeError(f'{label} failed: expected {allowed}, got {response.status_code}: {response.text[:400]}')
    return response.json()


def create_subject(headers: dict[str, str], subject_type: str, index: int, run_token: int) -> dict:
    identifier_prefix = 'EMP' if subject_type == 'EMPLOYEE' else 'VEN'
    identifier = f'{identifier_prefix}-{run_token}-{index}'
    payload = {
        'subject_type': subject_type,
        'name': f'{subject_type.title()} Demo {index}',
        'identifier': identifier,
        'email': f'{identifier.lower()}@example.com',
    }
    if subject_type == 'EMPLOYEE':
        payload['department'] = 'Compliance'

    response = requests.post(f'{BASE_URL}/subjects', headers=headers, json=payload, timeout=30)
    return expect_response(response, 201, f'Create {subject_type} subject')


def get_catalog(headers: dict[str, str], subject_type: str | None = None) -> list[dict]:
    params = {'subject_type': subject_type} if subject_type else None
    response = requests.get(f'{BASE_URL}/catalog', headers=headers, params=params, timeout=30)
    return expect_response(response, 200, 'Fetch catalog')


def create_document_slot(headers: dict[str, str], subject_id: str, catalog_item: dict) -> dict:
    payload = {
        'subject_id': subject_id,
        'category': catalog_item['category'],
        'display_name': catalog_item['display_name'],
        'has_expiry': catalog_item['has_expiry'],
        'alert_days_before': catalog_item['alert_days_before'],
    }
    response = requests.post(
        f'{BASE_URL}/subjects/{subject_id}/documents',
        headers=headers,
        json=payload,
        timeout=30,
    )
    return expect_response(response, 201, 'Create revalidation document')


def set_manual_dates(headers: dict[str, str], reval_doc_id: str, slot_index: int) -> dict:
    today = date.today()
    issue_date = (today - timedelta(days=(slot_index + 1) * 30)).isoformat()
    payload = {
        'issue_date': issue_date,
        'has_expiry': True,
        'notes': f'Demo manual update slot {slot_index}',
    }

    if slot_index == 0:
        payload['expiry_date'] = (today + timedelta(days=180)).isoformat()
    elif slot_index == 1:
        payload['expiry_date'] = (today + timedelta(days=15)).isoformat()
    elif slot_index == 2:
        payload['expiry_date'] = (today - timedelta(days=10)).isoformat()
    else:
        payload['has_expiry'] = False
        payload['expiry_date'] = None

    response = requests.put(
        f'{BASE_URL}/documents/{reval_doc_id}/dates',
        headers=headers,
        json=payload,
        timeout=30,
    )
    return expect_response(response, 200, 'Manual date update')


def get_subject_documents(headers: dict[str, str], subject_id: str) -> list[dict]:
    response = requests.get(f'{BASE_URL}/subjects/{subject_id}/documents', headers=headers, timeout=30)
    return expect_response(response, 200, 'List subject documents')


def main() -> int:
    try:
        headers = auth()
    except Exception as exc:
        return fail(f'Authentication failed: {exc}')

    run_token = int(time.time())
    created_subjects: list[dict] = []
    status_counts = {'VALID': 0, 'EXPIRING_SOON': 0, 'EXPIRED': 0, 'NO_EXPIRY': 0}

    try:
        full_catalog = get_catalog(headers)
    except Exception as exc:
        return fail(f'Catalog request failed: {exc}')

    if len(full_catalog) != 10:
        return fail(f'/catalog expected 10 entries, got {len(full_catalog)}')

    try:
        for subject_type in ('EMPLOYEE', 'EMPLOYEE', 'VENDOR', 'VENDOR'):
            index = len(created_subjects) + 1
            subject = create_subject(headers, subject_type, index, run_token)
            created_subjects.append(subject)
            subject_catalog = get_catalog(headers, subject_type)

            for slot_index, catalog_item in enumerate(subject_catalog):
                slot = create_document_slot(headers, subject['id'], catalog_item)
                updated_doc = set_manual_dates(headers, slot['id'], slot_index)
                status = updated_doc['status']
                if status in status_counts:
                    status_counts[status] += 1
    except Exception as exc:
        return fail(str(exc))

    if len(created_subjects) != 4:
        return fail(f'Expected 4 subjects, created {len(created_subjects)}')

    if status_counts['VALID'] < 1 or status_counts['EXPIRING_SOON'] < 1 or status_counts['EXPIRED'] < 1:
        return fail(f'Status coverage missing: {status_counts}')

    dashboard_response = requests.get(f'{BASE_URL}/dashboard', headers=headers, timeout=30)
    try:
        dashboard = expect_response(dashboard_response, 200, 'Dashboard request')
    except Exception as exc:
        return fail(str(exc))

    dashboard_keys = [
        'employees_total',
        'vendors_total',
        'docs_valid',
        'docs_expiring_soon',
        'docs_expired',
        'docs_missing',
        'docs_pending_upload',
    ]
    if any(dashboard.get(key) is None for key in dashboard_keys):
        return fail(f'Dashboard returned null counts: {dashboard}')

    print('Dashboard counts:')
    for key in dashboard_keys:
        print(f'  {key}: {dashboard[key]}')

    expiry_check_response = requests.post(f'{BASE_URL}/admin/check-expiry', headers=headers, timeout=30)
    try:
        expiry_result = expect_response(expiry_check_response, (200, 202), 'Trigger expiry check')
    except Exception as exc:
        return fail(str(exc))
    print(f"Expiry check: {expiry_result['message']} for tenant {expiry_result['tenant_id']}")
    time.sleep(5)

    alerts_response = requests.get(f'{BASE_URL}/alerts', headers=headers, params={'page': 1, 'page_size': 20}, timeout=30)
    try:
        alerts = expect_response(alerts_response, 200, 'List alerts')
    except Exception as exc:
        return fail(str(exc))
    print(f"Alerts fetched: {alerts['total']}")

    print('Compliance summary per subject:')
    for subject in created_subjects:
        documents = get_subject_documents(headers, subject['id'])
        summary: dict[str, int] = {}
        for document in documents:
            summary[document['status']] = summary.get(document['status'], 0) + 1
        print(f"  {subject['name']} ({subject['subject_type']}): {summary}")

    print('Demo PASSED ✓')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Assertion failed: {exc}')
        print('Demo FAILED')
        raise SystemExit(1)
