from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import requests


AUTH_URL = 'http://localhost:8000/api/v1/auth/token'
BASE_URL = 'http://localhost:8000/api/v1/revalidation'
AUTH_EMAIL = 'admin@test.com'
AUTH_PASSWORD = 'PZAD-QyiIWCBct2iRxvEkQ'
DATA_DIR = Path(__file__).resolve().parent / 'data' / 'demo_revalidation'

EMPLOYEE_NAME_KEYS = ('name', 'full_name', 'employee_name', 'employee_full_name')
EMPLOYEE_ID_KEYS = ('identifier', 'employee_id', 'emp_id', 'staff_code', 'employee_code')
EMPLOYEE_DEPARTMENT_KEYS = ('department', 'dept', 'division', 'function_name')
EMPLOYEE_EMAIL_KEYS = ('email', 'mail', 'work_email', 'employee_email')

VENDOR_NAME_KEYS = ('name', 'vendor_name', 'legal_name', 'supplier_name', 'company_name')
VENDOR_ID_KEYS = ('identifier', 'vendor_code', 'gst', 'gstin', 'gst_number', 'supplier_code')
VENDOR_EMAIL_KEYS = ('email', 'mail', 'contact_email', 'vendor_email')


def auth() -> dict[str, str]:
    response = requests.post(
        AUTH_URL,
        json={'email': AUTH_EMAIL, 'password': AUTH_PASSWORD},
        timeout=30,
    )
    response.raise_for_status()
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


def pick(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    normalized = {key.strip().lower(): (value or '').strip() for key, value in row.items()}
    for key in keys:
        value = normalized.get(key)
        if value:
            return value
    return None


def create_subject(headers: dict[str, str], payload: dict[str, str | None]) -> dict | None:
    response = requests.post(f'{BASE_URL}/subjects', headers=headers, json=payload, timeout=30)
    if response.status_code == 409:
        print(f"SKIP duplicate subject: {payload['subject_type']} / {payload['identifier']}")
        return None
    response.raise_for_status()
    return response.json()


def get_catalog(headers: dict[str, str], subject_type: str) -> list[dict]:
    response = requests.get(
        f'{BASE_URL}/catalog',
        headers=headers,
        params={'subject_type': subject_type},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


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
    response.raise_for_status()
    return response.json()


def set_dates(headers: dict[str, str], reval_doc_id: str, slot_index: int, subject_index: int) -> None:
    today = time.strftime('%Y-%m-%d')
    response = requests.put(
        f'{BASE_URL}/documents/{reval_doc_id}/dates',
        headers=headers,
        json=_date_payload(today, slot_index, subject_index),
        timeout=30,
    )
    response.raise_for_status()


def _date_payload(today_iso: str, slot_index: int, subject_index: int) -> dict[str, str | bool | None]:
    today = time.strptime(today_iso, '%Y-%m-%d')
    base_epoch = time.mktime(today)
    issue_epoch = base_epoch - (subject_index + slot_index + 1) * 86400 * 20
    payload: dict[str, str | bool | None] = {
        'issue_date': time.strftime('%Y-%m-%d', time.localtime(issue_epoch)),
        'has_expiry': True,
        'notes': f'Stress loader slot {slot_index}',
    }

    if slot_index % 4 == 0:
        payload['expiry_date'] = time.strftime('%Y-%m-%d', time.localtime(base_epoch + 86400 * 180))
    elif slot_index % 4 == 1:
        payload['expiry_date'] = time.strftime('%Y-%m-%d', time.localtime(base_epoch + 86400 * 12))
    elif slot_index % 4 == 2:
        payload['expiry_date'] = time.strftime('%Y-%m-%d', time.localtime(base_epoch - 86400 * 9))
    else:
        payload['has_expiry'] = False
        payload['expiry_date'] = None

    return payload


def normalize_employee(row: dict[str, str]) -> dict[str, str | None]:
    return {
        'subject_type': 'EMPLOYEE',
        'name': pick(row, EMPLOYEE_NAME_KEYS),
        'identifier': pick(row, EMPLOYEE_ID_KEYS),
        'department': pick(row, EMPLOYEE_DEPARTMENT_KEYS),
        'email': pick(row, EMPLOYEE_EMAIL_KEYS),
    }


def normalize_vendor(row: dict[str, str]) -> dict[str, str | None]:
    return {
        'subject_type': 'VENDOR',
        'name': pick(row, VENDOR_NAME_KEYS),
        'identifier': pick(row, VENDOR_ID_KEYS),
        'department': None,
        'email': pick(row, VENDOR_EMAIL_KEYS),
    }


def load_csv(path: Path, kind: str) -> list[dict[str, str | None]]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    if kind == 'EMPLOYEE':
        return [normalize_employee(row) for row in rows]
    return [normalize_vendor(row) for row in rows]


def validate_payload(payload: dict[str, str | None], source_name: str, row_number: int) -> None:
    if not payload['name'] or not payload['identifier']:
        raise ValueError(
            f'{source_name} row {row_number} is missing required mapped fields. '
            f'Mapped payload: {payload}'
        )


def main() -> int:
    headers = auth()

    files = [
        (DATA_DIR / 'employees_standard.csv', 'EMPLOYEE'),
        (DATA_DIR / 'employees_alias_columns.csv', 'EMPLOYEE'),
        (DATA_DIR / 'vendors_standard.csv', 'VENDOR'),
        (DATA_DIR / 'vendors_alias_columns.csv', 'VENDOR'),
    ]

    created = 0
    slot_count = 0

    for csv_path, kind in files:
        if not csv_path.exists():
            print(f'Missing file: {csv_path}')
            return 1

        rows = load_csv(csv_path, kind)
        catalog = get_catalog(headers, kind)

        for index, payload in enumerate(rows, start=1):
            validate_payload(payload, csv_path.name, index)
            subject = create_subject(headers, payload)
            if subject is None:
                continue

            created += 1
            for slot_index, catalog_item in enumerate(catalog):
                slot = create_document_slot(headers, subject['id'], catalog_item)
                set_dates(headers, slot['id'], slot_index, created)
                slot_count += 1

    print(f'Created subjects: {created}')
    print(f'Created document slots with manual dates: {slot_count}')
    print('Stress data load complete')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Loader failed: {exc}')
        raise SystemExit(1)
