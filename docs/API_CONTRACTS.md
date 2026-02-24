# LeakSight V1 — API Contracts

## 1. Overview

All API endpoints are served under `/api/v1/`. All requests require JWT authentication (except `/api/v1/auth/login`). All responses use JSON. All timestamps are ISO 8601 with timezone (UTC).

### Base URL

```
https://yourdomain.com/api/v1
```

### Authentication

All protected endpoints require the `Authorization` header:

```
Authorization: Bearer <jwt_token>
```

**JWT Payload:**
```json
{
  "sub": "user-uuid",
  "tenant_id": "tenant-uuid",
  "role": "ADMIN",
  "exp": 1719500000
}
```

### Standard Error Response Format

All errors follow this structure:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable error description",
    "details": [
      {
        "field": "file_size",
        "message": "File size exceeds 200MB limit"
      }
    ]
  }
}
```

### Standard Error Codes

| HTTP Status | Error Code | When |
|---|---|---|
| `400` | `VALIDATION_ERROR` | Request body or parameters invalid |
| `400` | `UNSUPPORTED_FORMAT` | Uploaded file format not supported |
| `400` | `FILE_TOO_LARGE` | File exceeds 200MB limit |
| `401` | `UNAUTHORIZED` | Missing or invalid JWT token |
| `403` | `FORBIDDEN` | User lacks required role or tenant access |
| `403` | `IMMUTABLE_RECORD` | Attempt to modify an accepted leakage record |
| `404` | `NOT_FOUND` | Requested resource does not exist |
| `409` | `DUPLICATE_RESOURCE` | Resource already exists (e.g., duplicate invoice_no) |
| `422` | `UNPROCESSABLE_ENTITY` | Request understood but cannot be processed |
| `500` | `INTERNAL_ERROR` | Unexpected server error |

### Pagination Contract

All list endpoints support cursor-based pagination:

**Request Parameters:**
```
?page=1&page_size=50&sort_by=created_at&sort_order=desc
```

| Parameter | Type | Default | Max | Description |
|---|---|---|---|---|
| `page` | integer | 1 | — | Page number (1-indexed) |
| `page_size` | integer | 50 | 200 | Items per page |
| `sort_by` | string | `created_at` | — | Column to sort by |
| `sort_order` | string | `desc` | — | `asc` or `desc` |

**Response Wrapper:**
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_items": 1234,
    "total_pages": 25,
    "has_next": true,
    "has_previous": false
  }
}
```

---

## 2. Authentication Endpoints

### 2.1 POST `/api/v1/auth/login`

**Purpose:** Authenticate user and return JWT token.

**Request:**
```json
{
  "email": "user@company.com",
  "password": "password123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "uuid",
    "email": "user@company.com",
    "role": "ADMIN",
    "tenant_id": "uuid",
    "tenant_name": "Acme Corp"
  }
}
```

**Errors:** `401 UNAUTHORIZED` (invalid credentials)

---

## 3. File Ingestion Endpoints

### 3.1 POST `/api/v1/ingest/upload`

**Purpose:** Upload a document for processing.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The document file |
| `doc_type` | string | Yes | One of: `INVOICE`, `CONTRACT`, `PO`, `GRN` |

**Response (201):**
```json
{
  "document_id": "uuid",
  "filename": "invoice_001.pdf",
  "doc_type": "INVOICE",
  "sha256_hash": "abc123...",
  "file_size": 524288,
  "parse_status": "PENDING",
  "created_at": "2026-02-21T10:00:00Z"
}
```

**Errors:**
- `400 FILE_TOO_LARGE` — file exceeds 200MB
- `400 UNSUPPORTED_FORMAT` — file extension not in supported list
- `400 VALIDATION_ERROR` — missing `doc_type` or invalid value
- `401 UNAUTHORIZED`

**Behavior:**
- Computes SHA-256 hash on upload
- Stores file to encrypted volume
- Creates `documents` row
- Creates `document_hashes` BASELINE record
- If SHA-256 matches existing document: returns existing `document_id` with a note

---

### 3.2 POST `/api/v1/ingest/upload-batch`

**Purpose:** Upload multiple documents in a single request.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | file[] | Yes | Multiple document files |
| `doc_type` | string | Yes | Document type (applied to all files in batch) |

**Response (201):**
```json
{
  "uploaded": [
    {
      "document_id": "uuid",
      "filename": "invoice_001.pdf",
      "status": "PENDING"
    },
    {
      "document_id": "uuid",
      "filename": "invoice_002.xlsx",
      "status": "PENDING"
    }
  ],
  "failed": [
    {
      "filename": "invoice_003.zip",
      "error": "Unsupported file format"
    }
  ],
  "total_uploaded": 2,
  "total_failed": 1
}
```

**Behavior:** Partial uploads allowed. Successfully uploaded files are processed; failed files are reported in the response. The batch does not fail entirely due to one bad file.

---

### 3.3 POST `/api/v1/ingest/trigger-run`

**Purpose:** Trigger an analysis run on all pending documents.

**Request:**
```json
{
  "document_ids": ["uuid1", "uuid2"]
}
```

If `document_ids` is omitted or empty, all unprocessed documents for the tenant are included.

**Response (202):**
```json
{
  "run_id": "uuid",
  "status": "QUEUED",
  "total_documents": 15,
  "created_at": "2026-02-21T10:05:00Z"
}
```

**Errors:**
- `400 VALIDATION_ERROR` — no documents to process
- `409 DUPLICATE_RESOURCE` — a run is already in progress for this tenant
- `401 UNAUTHORIZED`

---

### 3.4 GET `/api/v1/ingest/runs/{run_id}/status`

**Purpose:** Get the current status and progress of an analysis run.

**Response (200):**
```json
{
  "run_id": "uuid",
  "status": "PROCESSING",
  "total_documents": 15,
  "processed_documents": 8,
  "progress_percentage": 53.3,
  "total_leakage_found": 0,
  "leakage_record_count": 0,
  "error_summary": null,
  "started_at": "2026-02-21T10:05:30Z",
  "completed_at": null,
  "created_at": "2026-02-21T10:05:00Z"
}
```

**Status values:** `QUEUED`, `PROCESSING`, `PARTIAL_SUCCESS`, `COMPLETE`, `FAILED`

**Errors:** `404 NOT_FOUND`

---

### 3.5 GET `/api/v1/ingest/runs`

**Purpose:** List all analysis runs for the tenant.

**Query Parameters:** Standard pagination + optional `status` filter.

**Response (200):**
```json
{
  "data": [
    {
      "run_id": "uuid",
      "status": "COMPLETE",
      "total_documents": 15,
      "total_leakage_found": 150000.00,
      "leakage_record_count": 23,
      "started_at": "2026-02-21T10:05:30Z",
      "completed_at": "2026-02-21T12:30:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

## 4. Leakage Record Endpoints

### 4.1 GET `/api/v1/leakage/records`

**Purpose:** List leakage records with filtering and pagination.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `status` | string | Filter by status: `PENDING`, `ACCEPTED`, `REJECTED`, `PENDING_FX_RATE` |
| `leakage_type` | string | Filter by type: `PRICE_MISMATCH`, `DUPLICATE_INVOICE`, `QUANTITY_MISMATCH` |
| `vendor_id` | uuid | Filter by vendor |
| `run_id` | uuid | Filter by analysis run |
| `min_amount` | decimal | Minimum leakage amount |
| `max_amount` | decimal | Maximum leakage amount |
| `min_confidence` | float | Minimum confidence score |
| `date_from` | date | Invoice date range start |
| `date_to` | date | Invoice date range end |

Plus standard pagination parameters.

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "leakage_type": "PRICE_MISMATCH",
      "amount": 3000.00,
      "currency": "INR",
      "confidence": 0.92,
      "rule_applied": "RULE_1_PRICE_MISMATCH",
      "explanation": "Invoice INV-2024-001 from Tata Steel charges ₹350/MT...",
      "status": "PENDING",
      "vendor_name": "Tata Steel",
      "invoice_no": "INV-2024-001",
      "invoice_date": "2024-06-15",
      "created_at": "2026-02-21T12:30:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### 4.2 GET `/api/v1/leakage/records/{id}`

**Purpose:** Get a single leakage record with full evidence.

**Response (200):**
```json
{
  "id": "uuid",
  "leakage_type": "PRICE_MISMATCH",
  "amount": 3000.00,
  "currency": "INR",
  "confidence": 0.92,
  "rule_applied": "RULE_1_PRICE_MISMATCH",
  "explanation": "Invoice INV-2024-001 from Tata Steel charges ₹350/MT for 'Cement OPC 53 Grade' but the contract (version 2, valid 2024-01-01 to 2024-12-31) specifies ₹320/MT. Overcharge of ₹30/MT × 100 MT = ₹3,000 total.",
  "status": "PENDING",
  "evidence": {
    "invoice_reference": { ... },
    "contract_reference": { ... },
    "calculation": { ... },
    "unit_conversion_details": { ... },
    "fx_rate_applied": { ... },
    "match_confidence_breakdown": { ... },
    "duplicate_reference": null,
    "quantity_reference": null,
    "source_documents": [ ... ]
  },
  "reviewed_by": null,
  "reviewed_at": null,
  "review_notes": null,
  "created_at": "2026-02-21T12:30:00Z"
}
```

**Errors:** `404 NOT_FOUND`

---

### 4.3 POST `/api/v1/leakage/records/{id}/accept`

**Purpose:** Accept a leakage record. Once accepted, core financial fields become immutable.

**Request:**
```json
{
  "notes": "Verified against physical contract copy. Leakage confirmed."
}
```

`notes` is optional on acceptance.

**Response (200):**
```json
{
  "id": "uuid",
  "status": "ACCEPTED",
  "reviewed_by": "user-uuid",
  "reviewed_at": "2026-02-21T14:00:00Z",
  "review_notes": "Verified against physical contract copy. Leakage confirmed."
}
```

**Errors:**
- `404 NOT_FOUND`
- `400 VALIDATION_ERROR` — record is not in `PENDING` or `PENDING_FX_RATE` status
- `403 IMMUTABLE_RECORD` — record already accepted (cannot re-accept)

---

### 4.4 POST `/api/v1/leakage/records/{id}/reject`

**Purpose:** Reject a leakage record. **Notes are required** on rejection — a reviewer must explain why.

**Request:**
```json
{
  "notes": "Checked with vendor — this is a previously agreed amendment not captured in the system."
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "status": "REJECTED",
  "reviewed_by": "user-uuid",
  "reviewed_at": "2026-02-21T14:05:00Z",
  "review_notes": "Checked with vendor — this is a previously agreed amendment not captured in the system."
}
```

**Errors:**
- `404 NOT_FOUND`
- `400 VALIDATION_ERROR` — missing `notes` field (required for rejection)
- `400 VALIDATION_ERROR` — record is not in `PENDING` status
- `403 IMMUTABLE_RECORD` — record already accepted

---

### 4.5 GET `/api/v1/leakage/summary`

**Purpose:** Get aggregate leakage summary for the tenant.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `run_id` | uuid | Filter to a specific run |
| `status` | string | Filter by record status |

**Response (200):**
```json
{
  "total_leakage_amount": 1500000.00,
  "currency": "INR",
  "by_type": {
    "PRICE_MISMATCH": {
      "count": 45,
      "total_amount": 1200000.00
    },
    "DUPLICATE_INVOICE": {
      "count": 5,
      "total_amount": 200000.00
    },
    "QUANTITY_MISMATCH": {
      "count": 8,
      "total_amount": 100000.00
    }
  },
  "by_status": {
    "PENDING": 30,
    "ACCEPTED": 20,
    "REJECTED": 5,
    "PENDING_FX_RATE": 3
  },
  "by_vendor": [
    {
      "vendor_id": "uuid",
      "vendor_name": "Tata Steel",
      "total_amount": 500000.00,
      "record_count": 12
    },
    {
      "vendor_id": "uuid",
      "vendor_name": "JSW Steel",
      "total_amount": 350000.00,
      "record_count": 8
    }
  ],
  "average_confidence": 0.89
}
```

---

## 5. Vendor Endpoints

### 5.1 GET `/api/v1/vendors`

**Purpose:** List all vendors for the tenant.

**Query Parameters:** Standard pagination + optional `search` (fuzzy name search).

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "normalized_name": "tata steel",
      "raw_names": ["Tata Steel Pvt Ltd", "TATA STEEL LIMITED", "Tata Steel Ltd."],
      "gst_id": "27AAACT2727Q1ZX",
      "alias_count": 3,
      "created_at": "2026-02-21T10:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### 5.2 GET `/api/v1/vendors/{id}`

**Purpose:** Get a single vendor with all aliases.

**Response (200):**
```json
{
  "id": "uuid",
  "normalized_name": "tata steel",
  "raw_names": ["Tata Steel Pvt Ltd", "TATA STEEL LIMITED"],
  "gst_id": "27AAACT2727Q1ZX",
  "aliases": [
    {
      "id": "uuid",
      "alias_name": "tata steel pvt ltd",
      "override_source": "MANUAL_REVIEW",
      "applied_by": "user@company.com",
      "is_active": true,
      "created_at": "2026-02-21T10:00:00Z"
    }
  ],
  "created_at": "2026-02-21T10:00:00Z"
}
```

---

### 5.3 POST `/api/v1/vendors/{id}/aliases`

**Purpose:** Add a manual alias for a vendor.

**Request:**
```json
{
  "alias_name": "T.S. Limited"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "vendor_id": "uuid",
  "alias_name": "t.s. limited",
  "override_source": "MANUAL_REVIEW",
  "applied_by": "user-uuid",
  "is_active": true,
  "created_at": "2026-02-21T14:00:00Z"
}
```

**Errors:**
- `409 DUPLICATE_RESOURCE` — alias already exists for this tenant
- `404 NOT_FOUND` — vendor not found

---

### 5.4 PUT `/api/v1/vendors/{id}/aliases/{alias_id}/deactivate`

**Purpose:** Deactivate a vendor alias. Does not delete — sets `is_active = false`.

**Response (200):**
```json
{
  "id": "uuid",
  "alias_name": "t.s. limited",
  "is_active": false,
  "deactivated_at": "2026-02-21T14:10:00Z"
}
```

---

## 6. Contract Endpoints

### 6.1 GET `/api/v1/contracts`

**Purpose:** List all contracts with their current active versions.

**Query Parameters:** Standard pagination + optional `vendor_id` filter.

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "vendor_id": "uuid",
      "vendor_name": "Tata Steel",
      "contract_ref": "TS-2024-001",
      "active_version": {
        "version_number": 2,
        "valid_from": "2024-01-01",
        "valid_to": "2024-12-31",
        "line_item_count": 15
      },
      "total_versions": 2,
      "created_at": "2026-02-21T10:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### 6.2 GET `/api/v1/contracts/{id}/versions`

**Purpose:** List all versions of a contract.

**Response (200):**
```json
{
  "contract_id": "uuid",
  "vendor_name": "Tata Steel",
  "contract_ref": "TS-2024-001",
  "versions": [
    {
      "id": "uuid",
      "version_number": 1,
      "valid_from": "2023-01-01",
      "valid_to": "2023-12-31",
      "line_items": [
        {
          "id": "uuid",
          "item_desc": "Cement OPC 53 Grade",
          "unit": "MT",
          "unit_price": 300.00,
          "currency": "INR"
        }
      ]
    },
    {
      "id": "uuid",
      "version_number": 2,
      "valid_from": "2024-01-01",
      "valid_to": "2024-12-31",
      "line_items": [
        {
          "id": "uuid",
          "item_desc": "Cement OPC 53 Grade",
          "unit": "MT",
          "unit_price": 320.00,
          "currency": "INR"
        }
      ]
    }
  ]
}
```

---

### 6.3 POST `/api/v1/contracts`

**Purpose:** Create a new contract with its first version and line items.

**Request:**
```json
{
  "vendor_id": "uuid",
  "contract_ref": "TS-2024-001",
  "source_document_id": "uuid",
  "version": {
    "valid_from": "2024-01-01",
    "valid_to": "2024-12-31",
    "line_items": [
      {
        "item_desc": "Cement OPC 53 Grade",
        "unit": "MT",
        "unit_price": 320.00,
        "currency": "INR"
      },
      {
        "item_desc": "Steel TMT 12mm",
        "unit": "KG",
        "unit_price": 65.00,
        "currency": "INR"
      }
    ]
  }
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "vendor_id": "uuid",
  "contract_ref": "TS-2024-001",
  "version": {
    "id": "uuid",
    "version_number": 1,
    "valid_from": "2024-01-01",
    "valid_to": "2024-12-31",
    "line_item_count": 2
  },
  "created_at": "2026-02-21T10:00:00Z"
}
```

**Errors:**
- `404 NOT_FOUND` — vendor_id not found
- `400 VALIDATION_ERROR` — missing required fields, invalid dates

---

## 7. Report Endpoints

### 7.1 GET `/api/v1/reports/runs/{run_id}/summary`

**Purpose:** Get the CFO summary data for a completed run.

**Response (200):**
```json
{
  "run_id": "uuid",
  "run_status": "COMPLETE",
  "summary": {
    "total_leakage": 1500000.00,
    "currency": "INR",
    "total_records": 58,
    "accepted_records": 45,
    "rejected_records": 5,
    "pending_records": 8,
    "top_vendors": [
      {
        "vendor_name": "Tata Steel",
        "leakage_amount": 500000.00,
        "record_count": 12
      }
    ],
    "by_rule": {
      "PRICE_MISMATCH": { "count": 40, "amount": 1200000.00 },
      "DUPLICATE_INVOICE": { "count": 10, "amount": 200000.00 },
      "QUANTITY_MISMATCH": { "count": 8, "amount": 100000.00 }
    },
    "average_confidence": 0.89
  },
  "generated_at": "2026-02-21T14:00:00Z"
}
```

---

### 7.2 GET `/api/v1/reports/runs/{run_id}/evidence-pack`

**Purpose:** Generate and download the evidence pack as a PDF.

**Response (200):** Binary PDF file

**Headers:**
```
Content-Type: application/pdf
Content-Disposition: attachment; filename="leaksight_evidence_pack_run_{run_id}.pdf"
```

**Behavior:** Generates PDF on demand using WeasyPrint. Includes all accepted leakage records with full evidence. If run has no accepted records, generates a "No confirmed leakage findings" report.

---

### 7.3 GET `/api/v1/reports/runs/{run_id}/export-excel`

**Purpose:** Generate and download the Excel export for a run.

**Response (200):** Binary Excel file

**Headers:**
```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="leaksight_export_run_{run_id}.xlsx"
```

**Excel Sheets:**
1. **Summary** — Total leakage, by vendor, by rule, by status
2. **Price Mismatch** — All Rule 1 findings with details
3. **Duplicate Invoices** — All Rule 2 findings with details
4. **Quantity Mismatch** — All Rule 3 findings with details

**Behavior:**
- Numbers formatted as numbers (not text)
- No merged cells that hide data
- Vendor names consistent across sheets
- Summary totals match sum of line items
- Only includes ACCEPTED records in financial totals
- Rejected records are either excluded or clearly marked

---

## 8. Admin Endpoints

### 8.1 POST `/api/v1/admin/fx-rates/upload`

**Purpose:** Bulk upload FX rates.

**Requires role:** `ADMIN`

**Request:**
```json
{
  "rates": [
    {
      "from_currency": "USD",
      "to_currency": "INR",
      "rate": 83.50,
      "rate_date": "2024-06-15",
      "source": "MANUAL_UPLOAD"
    },
    {
      "from_currency": "EUR",
      "to_currency": "INR",
      "rate": 90.20,
      "rate_date": "2024-06-15",
      "source": "MANUAL_UPLOAD"
    }
  ]
}
```

**Response (201):**
```json
{
  "uploaded_count": 2,
  "rates": [
    {
      "id": "uuid",
      "from_currency": "USD",
      "to_currency": "INR",
      "rate": 83.50,
      "rate_date": "2024-06-15"
    }
  ]
}
```

**Behavior:** After uploading FX rates, any `PENDING_FX_RATE` leakage records that now have rates available can be resolved on the next analysis run.

---

### 8.2 GET `/api/v1/admin/fx-rates`

**Purpose:** List current FX rates.

**Query Parameters:** Optional `from_currency`, `to_currency`, `date_from`, `date_to` filters. Standard pagination.

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "from_currency": "USD",
      "to_currency": "INR",
      "rate": 83.50,
      "rate_date": "2024-06-15",
      "source": "MANUAL_UPLOAD",
      "uploaded_by": "admin@company.com",
      "created_at": "2026-02-21T10:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### 8.3 PUT `/api/v1/admin/tenant-settings`

**Purpose:** Update tenant-specific settings.

**Requires role:** `ADMIN`

**Request:**
```json
{
  "fuzzy_threshold": 0.85,
  "duplicate_window_days": 30,
  "manual_review_threshold": 0.70,
  "base_currency": "INR",
  "abbreviation_dictionary_additions": {
    "CMNT": "cement",
    "STL": "steel"
  }
}
```

**Response (200):**
```json
{
  "tenant_id": "uuid",
  "fuzzy_threshold": 0.85,
  "duplicate_window_days": 30,
  "manual_review_threshold": 0.70,
  "base_currency": "INR",
  "abbreviation_dictionary": {
    "MT": "metric_ton",
    "KG": "kilogram",
    "CMNT": "cement",
    "STL": "steel"
  },
  "updated_at": "2026-02-21T14:00:00Z"
}
```

**Behavior:**
- `abbreviation_dictionary_additions` are **merged** into the existing dictionary (system defaults + any previous tenant additions).
- System defaults cannot be removed — if the request tries to remove a default key, it is ignored.
- Other settings are directly overwritten.

---

### 8.4 GET `/api/v1/admin/tenant-settings`

**Purpose:** Get current tenant settings.

**Response (200):**
```json
{
  "tenant_id": "uuid",
  "fuzzy_threshold": 0.85,
  "duplicate_window_days": 30,
  "manual_review_threshold": 0.70,
  "base_currency": "INR",
  "abbreviation_dictionary": {
    "MT": "metric_ton",
    "KG": "kilogram",
    "KGS": "kilogram",
    "NOS": "nos",
    "PCS": "nos"
  },
  "updated_at": "2026-02-21T10:00:00Z"
}
```

---

## 9. Dashboard Endpoints

### 9.1 GET `/api/v1/dashboard/summary`

**Purpose:** Get the main dashboard summary metrics.

**Response (200):**
```json
{
  "total_leakage_amount": 1500000.00,
  "currency": "INR",
  "pending_review_count": 30,
  "pending_fx_rate_count": 3,
  "accepted_count": 45,
  "rejected_count": 5,
  "recent_runs": [
    {
      "run_id": "uuid",
      "status": "COMPLETE",
      "total_leakage_found": 500000.00,
      "completed_at": "2026-02-21T12:30:00Z"
    },
    {
      "run_id": "uuid",
      "status": "PARTIAL_SUCCESS",
      "total_leakage_found": 200000.00,
      "completed_at": "2026-02-20T15:00:00Z"
    }
  ],
  "top_vendors_by_leakage": [
    {
      "vendor_name": "Tata Steel",
      "total_amount": 500000.00
    }
  ]
}
```

---

## 10. Notification Endpoints

### 10.1 GET `/api/v1/notifications`

**Purpose:** List notifications for the current user.

**Query Parameters:**
- `unread_only` (boolean, default: false)
- Standard pagination

**Response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "message": "Analysis run completed. Total leakage found: ₹5,00,000 across 23 records. 23 records require review.",
      "notification_type": "RUN_COMPLETE",
      "run_id": "uuid",
      "read_at": null,
      "created_at": "2026-02-21T12:30:00Z"
    }
  ],
  "pagination": { ... },
  "unread_count": 3
}
```

---

### 10.2 PUT `/api/v1/notifications/{id}/read`

**Purpose:** Mark a notification as read.

**Response (200):**
```json
{
  "id": "uuid",
  "read_at": "2026-02-21T14:00:00Z"
}
```

---

## 11. Health Check

### 11.1 GET `/api/v1/health`

**Purpose:** System health check. No authentication required.

**Response (200):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "redis": "connected",
  "timestamp": "2026-02-21T10:00:00Z"
}
```

**Response (503):**
```json
{
  "status": "unhealthy",
  "version": "1.0.0",
  "database": "disconnected",
  "redis": "connected",
  "timestamp": "2026-02-21T10:00:00Z"
}
```
