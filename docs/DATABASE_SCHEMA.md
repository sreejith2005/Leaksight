# LeakSight V1 — Database Schema

## 1. Overview

The database uses a strict three-layer architecture:

| Layer | Purpose | Mutability | Tables |
|---|---|---|---|
| **RAW** | Immutable snapshots of parsed document data | Append-only (new versions, never update) | `documents`, `raw_parses` |
| **Canonical** | Normalized, deduplicated business entities | Mutable (normalization updates allowed) | `vendors`, `vendor_aliases`, `contracts`, `contract_versions`, `contract_line_items`, `invoices`, `invoice_line_items`, `purchase_orders`, `po_line_items`, `grns`, `grn_line_items`, `canonical_units`, `unit_conversion_factors`, `fx_rates`, `tenant_settings` |
| **Derived** | Computed results from rules engine | Conditionally immutable (leakage records immutable after acceptance) | `analysis_runs`, `leakage_records`, `document_hashes` |

### Key Principles

- **Every table with `tenant_id`** has Row-Level Security (RLS) enabled with `FORCE ROW LEVEL SECURITY`.
- **Every unique constraint** on tenant-scoped tables includes `tenant_id` as the first column.
- **All primary keys** are UUID v4 (via `uuid-ossp` extension) unless otherwise noted.
- **All timestamps** are `TIMESTAMPTZ` (timezone-aware), defaulting to `NOW()`.
- **All monetary amounts** are `NUMERIC(20, 6)` — 20 digits total, 6 decimal places. Never use `FLOAT` for money.
- **All confidence scores** are `FLOAT` in the range `[0.0, 1.0]`.

### Required PostgreSQL Extensions

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Trigram similarity for future fuzzy search
```

### Database Roles

| Role | Purpose | RLS Behavior |
|---|---|---|
| `app_admin` | Cross-tenant operations (migrations, seeding, backup) | Bypasses RLS |
| `app_tenant_user` | Application runtime queries | Subject to RLS — can only see rows where `tenant_id` matches `current_setting('app.current_tenant_id')` |

---

## 2. RAW Layer Tables

### 2.1 `documents`

Stores metadata about every uploaded file. One row per uploaded file.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Document identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `run_id` | `UUID` | NULLABLE, FK → `analysis_runs.id` | Associated analysis run (set when run is triggered) |
| `file_path` | `TEXT` | NOT NULL | Relative path on encrypted volume: `{tenant_id}/{document_id}/{filename}` |
| `original_filename` | `TEXT` | NOT NULL | Original uploaded filename |
| `sha256_hash` | `CHAR(64)` | NOT NULL | SHA-256 hash of file content |
| `doc_type` | `doc_type_enum` | NOT NULL | One of: `INVOICE`, `CONTRACT`, `PO`, `GRN` |
| `file_size` | `BIGINT` | NOT NULL | File size in bytes |
| `page_count` | `INTEGER` | NULLABLE | Number of pages (NULL for CSV/Excel) |
| `mime_type` | `TEXT` | NOT NULL | Detected MIME type |
| `parse_status` | `parse_status_enum` | NOT NULL, DEFAULT `'PENDING'` | One of: `PENDING`, `PARSING`, `PARSED`, `FAILED` |
| `low_confidence_flag` | `BOOLEAN` | NOT NULL, DEFAULT `FALSE` | Set when parse_confidence < manual_review_threshold |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Upload timestamp |

**Enums:**
```sql
CREATE TYPE doc_type_enum AS ENUM ('INVOICE', 'CONTRACT', 'PO', 'GRN');
CREATE TYPE parse_status_enum AS ENUM ('PENDING', 'PARSING', 'PARSED', 'FAILED');
```

**Indexes:**
```sql
CREATE INDEX idx_documents_tenant_id ON documents(tenant_id);
CREATE INDEX idx_documents_tenant_doc_type ON documents(tenant_id, doc_type);
CREATE INDEX idx_documents_sha256 ON documents(sha256_hash);
```

**RLS Policy:**
```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY documents_tenant_isolation ON documents
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
```

---

### 2.2 `raw_parses`

Stores the output of each parse attempt. **Append-only** — re-parsing creates a new row with incremented `raw_version`, never updates an existing row.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Parse record identifier |
| `document_id` | `UUID` | NOT NULL, FK → `documents.id` | Source document |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `raw_version` | `INTEGER` | NOT NULL | Monotonically increasing version number per document |
| `parser_used` | `TEXT` | NOT NULL | Parser identifier (e.g., `excel_parser_v1`, `pdf_digital_parser_v1`) |
| `parser_version` | `TEXT` | NOT NULL | Version string of the parser code |
| `structured_output_jsonb` | `JSONB` | NOT NULL | Normalized intermediate schema output |
| `parse_confidence` | `FLOAT` | NOT NULL, CHECK `(parse_confidence >= 0 AND parse_confidence <= 1)` | Parser's confidence in extraction accuracy |
| `failure_flags` | `JSONB` | NOT NULL, DEFAULT `'[]'` | Array of failure flag objects |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Parse timestamp |

**Constraints:**
```sql
ALTER TABLE raw_parses ADD CONSTRAINT uq_raw_parses_doc_version
    UNIQUE (document_id, raw_version);
```

**Indexes:**
```sql
CREATE INDEX idx_raw_parses_document_id ON raw_parses(document_id);
CREATE INDEX idx_raw_parses_tenant_id ON raw_parses(tenant_id);
```

**RLS Policy:**
```sql
ALTER TABLE raw_parses ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_parses FORCE ROW LEVEL SECURITY;
CREATE POLICY raw_parses_tenant_isolation ON raw_parses
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
```

**Application-Level Immutability:** No UPDATE or DELETE operations are permitted on this table by application code. In Phase 5 a database trigger will enforce this at the DB level.

---

## 3. Canonical Layer Tables

### 3.1 `tenants`

Top-level tenant table. Not scoped by RLS — used for cross-tenant admin operations.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Tenant identifier |
| `name` | `TEXT` | NOT NULL | Company name |
| `is_active` | `BOOLEAN` | NOT NULL, DEFAULT `TRUE` | Soft delete flag |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

---

### 3.2 `users`

Users within a tenant. Used for authentication and audit logging.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | User identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `email` | `TEXT` | NOT NULL | User email (login identifier) |
| `password_hash` | `TEXT` | NOT NULL | bcrypt hash |
| `role` | `user_role_enum` | NOT NULL, DEFAULT `'REVIEWER'` | One of: `ADMIN`, `REVIEWER` |
| `is_active` | `BOOLEAN` | NOT NULL, DEFAULT `TRUE` | Soft delete flag |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Enum:**
```sql
CREATE TYPE user_role_enum AS ENUM ('ADMIN', 'REVIEWER');
```

**Constraints:**
```sql
ALTER TABLE users ADD CONSTRAINT uq_users_tenant_email UNIQUE (tenant_id, email);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.3 `vendors`

Normalized vendor records. One vendor per tenant, even if the vendor appears under many different raw names.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Vendor identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `normalized_name` | `TEXT` | NOT NULL | Lowercased, stripped of legal suffixes |
| `raw_names_jsonb` | `JSONB` | NOT NULL, DEFAULT `'[]'` | Array of all raw name variants seen |
| `gst_id` | `TEXT` | NULLABLE | GST/Tax ID (if available) |
| `source_system_ref` | `TEXT` | NULLABLE | Reference in client's source system |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Last update timestamp |

**Constraints:**
```sql
ALTER TABLE vendors ADD CONSTRAINT uq_vendors_tenant_normalized_name
    UNIQUE (tenant_id, normalized_name);
```

**Indexes:**
```sql
CREATE INDEX idx_vendors_tenant_id ON vendors(tenant_id);
CREATE INDEX idx_vendors_gst_id ON vendors(gst_id);
CREATE INDEX idx_vendors_normalized_name_trgm ON vendors
    USING gin (normalized_name gin_trgm_ops);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.4 `vendor_aliases`

Manual and auto-accepted aliases that map variant names to a canonical vendor. A hit on this table during matching returns 100% confidence.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Alias identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `vendor_id` | `UUID` | NOT NULL, FK → `vendors.id` | Target vendor |
| `alias_name` | `TEXT` | NOT NULL | The variant name (lowercased) |
| `override_source` | `alias_source_enum` | NOT NULL | One of: `MANUAL_REVIEW`, `IMPORT`, `AUTO_ACCEPTED` |
| `applied_by_user_id` | `UUID` | NULLABLE, FK → `users.id` | User who created the alias (NULL for auto) |
| `is_active` | `BOOLEAN` | NOT NULL, DEFAULT `TRUE` | If FALSE, alias is ignored during matching |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Enum:**
```sql
CREATE TYPE alias_source_enum AS ENUM ('MANUAL_REVIEW', 'IMPORT', 'AUTO_ACCEPTED');
```

**Constraints:**
```sql
ALTER TABLE vendor_aliases ADD CONSTRAINT uq_vendor_aliases_tenant_alias
    UNIQUE (tenant_id, alias_name);
```

**Indexes:**
```sql
CREATE INDEX idx_vendor_aliases_tenant_id ON vendor_aliases(tenant_id);
CREATE INDEX idx_vendor_aliases_vendor_id ON vendor_aliases(vendor_id);
CREATE INDEX idx_vendor_aliases_alias_name ON vendor_aliases(alias_name);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.5 `canonical_units`

System-wide unit definitions. **Not tenant-scoped** — these are global reference data.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Unit identifier |
| `name` | `TEXT` | NOT NULL, UNIQUE | Full name (e.g., `metric_ton`, `kilogram`) |
| `symbol` | `TEXT` | NOT NULL, UNIQUE | Short symbol (e.g., `MT`, `KG`) |
| `dimension` | `unit_dimension_enum` | NOT NULL | One of: `WEIGHT`, `VOLUME`, `COUNT`, `AREA`, `LENGTH`, `TIME` |

**Enum:**
```sql
CREATE TYPE unit_dimension_enum AS ENUM ('WEIGHT', 'VOLUME', 'COUNT', 'AREA', 'LENGTH', 'TIME');
```

**V1 Seed Data:**

| Name | Symbol | Dimension |
|---|---|---|
| `metric_ton` | `MT` | WEIGHT |
| `kilogram` | `KG` | WEIGHT |
| `gram` | `G` | WEIGHT |
| `litre` | `L` | VOLUME |
| `millilitre` | `ML` | VOLUME |
| `nos` | `Nos` | COUNT |
| `box` | `Box` | COUNT |
| `set` | `Set` | COUNT |
| `square_foot` | `Sqft` | AREA |
| `square_metre` | `Sqm` | AREA |
| `running_metre` | `RMT` | LENGTH |

---

### 3.6 `unit_conversion_factors`

Conversion factors between units within the same dimension. Cross-dimension conversion is an error, never allowed.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Conversion record ID |
| `from_unit_id` | `UUID` | NOT NULL, FK → `canonical_units.id` | Source unit |
| `to_unit_id` | `UUID` | NOT NULL, FK → `canonical_units.id` | Target unit |
| `factor` | `NUMERIC(20, 10)` | NOT NULL | Multiply source value by this to get target value |
| `tenant_id` | `UUID` | NULLABLE, FK → `tenants.id` | NULL = system default; non-NULL = tenant override |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Constraints:**
```sql
ALTER TABLE unit_conversion_factors ADD CONSTRAINT uq_conversion_from_to_tenant
    UNIQUE (from_unit_id, to_unit_id, tenant_id);
```

**Lookup Logic:** When converting, first look for a tenant-specific override (`tenant_id = ?`). If none found, fall back to system default (`tenant_id IS NULL`).

**V1 Seed Conversions (system defaults, `tenant_id = NULL`):**

| From | To | Factor |
|---|---|---|
| MT | KG | 1000.0 |
| KG | MT | 0.001 |
| KG | G | 1000.0 |
| G | KG | 0.001 |
| MT | G | 1000000.0 |
| G | MT | 0.000001 |
| L | ML | 1000.0 |
| ML | L | 0.001 |
| Sqm | Sqft | 10.7639 |
| Sqft | Sqm | 0.092903 |

---

### 3.7 `fx_rates`

Foreign exchange rates for currency conversion. The system **never guesses** an FX rate. If no rate is found for an invoice's currency on its date, the leakage record is created with status `PENDING_FX_RATE`.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Rate record ID |
| `tenant_id` | `UUID` | NULLABLE, FK → `tenants.id` | NULL = system-wide rate; non-NULL = tenant-specific |
| `from_currency` | `CHAR(3)` | NOT NULL | ISO 4217 currency code (e.g., `USD`) |
| `to_currency` | `CHAR(3)` | NOT NULL | ISO 4217 currency code (e.g., `INR`) |
| `rate` | `NUMERIC(20, 10)` | NOT NULL | 1 unit of `from_currency` = `rate` units of `to_currency` |
| `rate_date` | `DATE` | NOT NULL | Date this rate is effective |
| `source` | `fx_source_enum` | NOT NULL | One of: `ECB`, `RBI`, `MANUAL_UPLOAD`, `ADMIN_IMPORT` |
| `uploaded_by_user_id` | `UUID` | NULLABLE, FK → `users.id` | User who uploaded (NULL for system imports) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Enum:**
```sql
CREATE TYPE fx_source_enum AS ENUM ('ECB', 'RBI', 'MANUAL_UPLOAD', 'ADMIN_IMPORT');
```

**Indexes:**
```sql
CREATE INDEX idx_fx_rates_currency_date ON fx_rates(from_currency, to_currency, rate_date);
```

**Lookup Logic:** `SELECT rate FROM fx_rates WHERE from_currency = ? AND to_currency = ? AND rate_date <= ? AND (tenant_id = ? OR tenant_id IS NULL) ORDER BY rate_date DESC, tenant_id DESC NULLS LAST LIMIT 1;` — Tenant-specific rates take precedence over system rates. Closest rate_date on or before invoice date is used. If no rate found at all → `PENDING_FX_RATE`.

---

### 3.8 `contracts`

Contract header records. One per vendor-contract relationship.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Contract identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `vendor_id` | `UUID` | NOT NULL, FK → `vendors.id` | Vendor this contract belongs to |
| `contract_ref` | `TEXT` | NULLABLE | Client's internal contract reference number |
| `source_document_id` | `UUID` | NULLABLE, FK → `documents.id` | Uploaded contract document |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Indexes:**
```sql
CREATE INDEX idx_contracts_tenant_vendor ON contracts(tenant_id, vendor_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.9 `contract_versions`

Versioned contract terms. A single contract may have multiple versions (amendments, renewals) with different validity periods.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Version identifier |
| `contract_id` | `UUID` | NOT NULL, FK → `contracts.id` | Parent contract |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `version_number` | `INTEGER` | NOT NULL | Monotonically increasing |
| `valid_from` | `DATE` | NOT NULL | Start of validity period (inclusive) |
| `valid_to` | `DATE` | NOT NULL | End of validity period (inclusive) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Constraints:**
```sql
ALTER TABLE contract_versions ADD CONSTRAINT uq_contract_versions_contract_version
    UNIQUE (contract_id, version_number);
```

**Indexes:**
```sql
CREATE INDEX idx_contract_versions_vendor_dates ON contract_versions(tenant_id, valid_from, valid_to);
```

**Contract Version Resolution Logic:**
```sql
-- Find the valid contract version for a vendor on a given invoice date
SELECT cv.* FROM contract_versions cv
JOIN contracts c ON cv.contract_id = c.id
WHERE c.vendor_id = :vendor_id
  AND cv.valid_from <= :invoice_date
  AND cv.valid_to >= :invoice_date
  AND c.tenant_id = :tenant_id;
```

If this returns:
- **Exactly 1 row** → clean match, proceed with Rule 1
- **0 rows** → no valid contract, skip Rule 1 for this invoice
- **>1 rows** → overlapping versions detected, flag for manual review

**RLS Policy:** Applied with tenant isolation.

---

### 3.10 `contract_line_items`

Individual pricing entries within a contract version. This is **Commercial Truth** — the agreed prices.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Line item identifier |
| `contract_version_id` | `UUID` | NOT NULL, FK → `contract_versions.id` | Parent version |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `item_desc` | `TEXT` | NOT NULL | Normalized item description |
| `raw_item_desc` | `TEXT` | NOT NULL | Original description before normalization |
| `unit` | `TEXT` | NOT NULL | Unit of measure (references canonical_units.symbol) |
| `unit_price` | `NUMERIC(20, 6)` | NOT NULL | Agreed unit price |
| `currency` | `CHAR(3)` | NOT NULL, DEFAULT `'INR'` | ISO 4217 currency code |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Indexes:**
```sql
CREATE INDEX idx_contract_line_items_version ON contract_line_items(contract_version_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.11 `invoices`

Invoice header records. This is the primary **Financial Truth** document.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Invoice identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `vendor_id` | `UUID` | NOT NULL, FK → `vendors.id` | Matched vendor |
| `invoice_no` | `TEXT` | NOT NULL | Invoice number from document |
| `invoice_date` | `DATE` | NOT NULL | Invoice date |
| `total_amount` | `NUMERIC(20, 6)` | NOT NULL | Total invoice amount |
| `currency` | `CHAR(3)` | NOT NULL, DEFAULT `'INR'` | ISO 4217 currency code |
| `source_document_id` | `UUID` | NOT NULL, FK → `documents.id` | Uploaded invoice document |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Constraints:**
```sql
ALTER TABLE invoices ADD CONSTRAINT uq_invoices_tenant_invoice_no
    UNIQUE (tenant_id, invoice_no);
```

**Indexes:**
```sql
CREATE INDEX idx_invoices_tenant_id ON invoices(tenant_id);
CREATE INDEX idx_invoices_vendor_id ON invoices(vendor_id);
-- CRITICAL: Composite index for Rule 2 near-duplicate scanning
-- Without this, near-duplicate queries degrade to full table scans at 10,000+ invoices
CREATE INDEX idx_invoices_tenant_vendor_date ON invoices(tenant_id, vendor_id, invoice_date);
```

**Why the composite index `(tenant_id, vendor_id, invoice_date)` exists:**

Rule 2 (Duplicate Invoice) near-duplicate detection queries invoices by the same vendor within a temporal window. The query pattern is:

```sql
SELECT * FROM invoices
WHERE tenant_id = :tenant_id
  AND vendor_id = :vendor_id
  AND invoice_date BETWEEN :date_start AND :date_end
  AND total_amount = :amount;
```

Without the composite index, PostgreSQL must scan all invoices for the tenant, filter by vendor, then filter by date range. At 10,000+ invoices per client, this degrades to unacceptable performance. The composite index allows PostgreSQL to seek directly to the relevant vendor's invoices within the date range, making the query O(log n) instead of O(n).

**RLS Policy:** Applied with tenant isolation.

---

### 3.12 `invoice_line_items`

Individual line items from an invoice. These are the atomic units of leakage detection.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Line item identifier |
| `invoice_id` | `UUID` | NOT NULL, FK → `invoices.id` | Parent invoice |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `item_desc` | `TEXT` | NOT NULL | Normalized item description |
| `raw_item_desc` | `TEXT` | NOT NULL | Original description before normalization |
| `quantity` | `NUMERIC(20, 6)` | NOT NULL | Quantity invoiced |
| `unit` | `TEXT` | NOT NULL | Unit of measure |
| `unit_price` | `NUMERIC(20, 6)` | NOT NULL | Unit price charged |
| `line_total` | `NUMERIC(20, 6)` | NOT NULL | `quantity × unit_price` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Indexes:**
```sql
CREATE INDEX idx_invoice_line_items_invoice ON invoice_line_items(invoice_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.13 `purchase_orders`

Purchase order header records. Part of **Operational Truth**.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | PO identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `vendor_id` | `UUID` | NOT NULL, FK → `vendors.id` | Matched vendor |
| `po_no` | `TEXT` | NOT NULL | PO number |
| `po_date` | `DATE` | NOT NULL | PO date |
| `source_document_id` | `UUID` | NULLABLE, FK → `documents.id` | Uploaded PO document |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Constraints:**
```sql
ALTER TABLE purchase_orders ADD CONSTRAINT uq_po_tenant_po_no
    UNIQUE (tenant_id, po_no);
```

**Indexes:**
```sql
CREATE INDEX idx_po_tenant_vendor ON purchase_orders(tenant_id, vendor_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.14 `po_line_items`

Individual PO line items.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Line item identifier |
| `po_id` | `UUID` | NOT NULL, FK → `purchase_orders.id` | Parent PO |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `item_desc` | `TEXT` | NOT NULL | Normalized item description |
| `raw_item_desc` | `TEXT` | NOT NULL | Original description |
| `unit` | `TEXT` | NOT NULL | Unit of measure |
| `ordered_qty` | `NUMERIC(20, 6)` | NOT NULL | Quantity ordered |
| `unit_price` | `NUMERIC(20, 6)` | NOT NULL | Unit price on PO |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Indexes:**
```sql
CREATE INDEX idx_po_line_items_po ON po_line_items(po_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.15 `grns`

Goods Received Note header records. **GRN overrides PO** for quantity truth.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | GRN identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `po_id` | `UUID` | NOT NULL, FK → `purchase_orders.id` | Associated PO |
| `grn_no` | `TEXT` | NOT NULL | GRN reference number |
| `grn_date` | `DATE` | NOT NULL | Receipt date |
| `source_document_id` | `UUID` | NULLABLE, FK → `documents.id` | Uploaded GRN document |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Constraints:**
```sql
ALTER TABLE grns ADD CONSTRAINT uq_grns_tenant_grn_no
    UNIQUE (tenant_id, grn_no);
```

**Indexes:**
```sql
CREATE INDEX idx_grns_tenant_po ON grns(tenant_id, po_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.16 `grn_line_items`

Individual GRN line items. Received quantities.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Line item identifier |
| `grn_id` | `UUID` | NOT NULL, FK → `grns.id` | Parent GRN |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `item_desc` | `TEXT` | NOT NULL | Normalized item description |
| `raw_item_desc` | `TEXT` | NOT NULL | Original description |
| `unit` | `TEXT` | NOT NULL | Unit of measure |
| `received_qty` | `NUMERIC(20, 6)` | NOT NULL | Quantity actually received |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Indexes:**
```sql
CREATE INDEX idx_grn_line_items_grn ON grn_line_items(grn_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 3.17 `tenant_settings`

Per-tenant configuration that controls system behavior.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `tenant_id` | `UUID` | PK, FK → `tenants.id` | Tenant this setting belongs to |
| `abbreviation_dictionary` | `JSONB` | NOT NULL, DEFAULT (see below) | Key-value map of abbreviation → normalized form |
| `fuzzy_threshold` | `FLOAT` | NOT NULL, DEFAULT `0.85` | Minimum RapidFuzz score for auto-match |
| `duplicate_window_days` | `INTEGER` | NOT NULL, DEFAULT `30` | Days window for near-duplicate detection |
| `manual_review_threshold` | `FLOAT` | NOT NULL, DEFAULT `0.70` | Parse confidence below this triggers low-confidence flag |
| `base_currency` | `CHAR(3)` | NOT NULL, DEFAULT `'INR'` | Tenant's base currency for reporting |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Last update timestamp |

**`abbreviation_dictionary` Structure:**

The `abbreviation_dictionary` is a flat JSON object. Each key is a raw abbreviation (case-insensitive match), each value is the normalized form.

**Default seed value:**
```json
{
  "MT": "metric_ton",
  "KG": "kilogram",
  "KGS": "kilogram",
  "GM": "gram",
  "GMS": "gram",
  "NOS": "nos",
  "NO": "nos",
  "PCS": "nos",
  "PC": "nos",
  "BOX": "box",
  "BX": "box",
  "SET": "set",
  "SQFT": "square_foot",
  "SFT": "square_foot",
  "SQM": "square_metre",
  "RMT": "running_metre",
  "RM": "running_metre",
  "LTR": "litre",
  "LT": "litre",
  "ML": "millilitre",
  "PKT": "packet",
  "PKG": "package",
  "DZ": "dozen",
  "PR": "pair"
}
```

**Behavior:**
- Tenants can **add** new entries to the dictionary (e.g., client-specific abbreviations).
- Tenants **cannot delete** system default entries — the API merges tenant additions on top of system defaults.
- The normalization service loads this dictionary at the start of each normalization task and uses it for item description normalization before any fuzzy matching occurs.

---

## 4. Derived Layer Tables

### 4.1 `analysis_runs`

Tracks each analysis run's lifecycle. One run processes all pending documents for a tenant.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Run identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `status` | `run_status_enum` | NOT NULL, DEFAULT `'QUEUED'` | Current run status |
| `total_documents` | `INTEGER` | NOT NULL, DEFAULT `0` | Total documents in this run |
| `processed_documents` | `INTEGER` | NOT NULL, DEFAULT `0` | Documents processed so far |
| `total_leakage_found` | `NUMERIC(20, 6)` | NOT NULL, DEFAULT `0` | Sum of all leakage amounts |
| `leakage_record_count` | `INTEGER` | NOT NULL, DEFAULT `0` | Number of leakage records generated |
| `error_summary` | `TEXT` | NULLABLE | Human-readable error description (for FAILED status) |
| `started_at` | `TIMESTAMPTZ` | NULLABLE | Processing start time |
| `completed_at` | `TIMESTAMPTZ` | NULLABLE | Processing end time |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Queued timestamp |

**Enum:**
```sql
CREATE TYPE run_status_enum AS ENUM ('QUEUED', 'PROCESSING', 'PARTIAL_SUCCESS', 'COMPLETE', 'FAILED');
```

**Run Status Logic:**
- `QUEUED` → initial state when run is created
- `PROCESSING` → set when analysis task begins
- `COMPLETE` → all documents parsed, all invoice line items processed cleanly
- `PARTIAL_SUCCESS` → one or more of: low-confidence parse, PENDING_FX_RATE records, partial failures that didn't halt the run
- `FAILED` → unhandled exception at run level, error_summary populated

**Indexes:**
```sql
CREATE INDEX idx_analysis_runs_tenant ON analysis_runs(tenant_id);
CREATE INDEX idx_analysis_runs_status ON analysis_runs(tenant_id, status);
```

**RLS Policy:** Applied with tenant isolation.

---

### 4.2 `leakage_records`

The most important data structure in the system. Each row represents one detected financial leakage finding.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Leakage record identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `run_id` | `UUID` | NOT NULL, FK → `analysis_runs.id` | Parent analysis run |
| `leakage_type` | `leakage_type_enum` | NOT NULL | Type of leakage detected |
| `invoice_id` | `UUID` | NOT NULL, FK → `invoices.id` | Source invoice |
| `invoice_line_item_id` | `UUID` | NULLABLE, FK → `invoice_line_items.id` | Specific line item (NULL for duplicate invoice rule) |
| `contract_line_item_id` | `UUID` | NULLABLE, FK → `contract_line_items.id` | Matched contract line (Rule 1 only) |
| `amount` | `NUMERIC(20, 6)` | NOT NULL | Leakage amount in base currency |
| `currency` | `CHAR(3)` | NOT NULL | Currency of the amount |
| `confidence` | `FLOAT` | NOT NULL, CHECK `(confidence >= 0 AND confidence <= 1)` | Detection confidence |
| `evidence_jsonb` | `JSONB` | NOT NULL | Full evidence payload (see schema below) |
| `rule_applied` | `TEXT` | NOT NULL | Rule identifier (e.g., `RULE_1_PRICE_MISMATCH`) |
| `explanation` | `TEXT` | NOT NULL | Human-readable explanation string |
| `status` | `leakage_status_enum` | NOT NULL, DEFAULT `'PENDING'` | Review status |
| `reviewed_by_user_id` | `UUID` | NULLABLE, FK → `users.id` | Reviewer who accepted/rejected |
| `reviewed_at` | `TIMESTAMPTZ` | NULLABLE | Review timestamp |
| `review_notes` | `TEXT` | NULLABLE | Reviewer's notes (required on rejection) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Detection timestamp |

**Enums:**
```sql
CREATE TYPE leakage_type_enum AS ENUM ('PRICE_MISMATCH', 'DUPLICATE_INVOICE', 'QUANTITY_MISMATCH');
CREATE TYPE leakage_status_enum AS ENUM ('PENDING', 'ACCEPTED', 'REJECTED', 'PENDING_FX_RATE');
```

**Indexes:**
```sql
CREATE INDEX idx_leakage_tenant ON leakage_records(tenant_id);
CREATE INDEX idx_leakage_run ON leakage_records(run_id);
CREATE INDEX idx_leakage_status ON leakage_records(tenant_id, status);
CREATE INDEX idx_leakage_type ON leakage_records(tenant_id, leakage_type);
```

**RLS Policy:** Applied with tenant isolation.

---

### 4.2.1 `evidence_jsonb` Fixed Internal Schema

The `evidence_jsonb` column is a JSONB object with a **fixed internal schema**. All rules must populate this structure. Fields that are not applicable for a given rule are set to `null`.

```json
{
  "rule": "RULE_1_PRICE_MISMATCH",
  "invoice_reference": {
    "invoice_id": "uuid",
    "invoice_no": "INV-2024-001",
    "invoice_date": "2024-06-15",
    "line_item_id": "uuid",
    "item_desc": "Cement OPC 53 Grade",
    "invoiced_unit_price": 350.00,
    "invoiced_quantity": 100,
    "invoiced_unit": "MT",
    "invoiced_line_total": 35000.00
  },
  "contract_reference": {
    "contract_id": "uuid",
    "contract_version_id": "uuid",
    "version_number": 2,
    "valid_from": "2024-01-01",
    "valid_to": "2024-12-31",
    "line_item_id": "uuid",
    "item_desc": "Cement OPC 53 Grade",
    "contract_unit_price": 320.00,
    "contract_unit": "MT",
    "currency": "INR"
  },
  "calculation": {
    "price_difference_per_unit": 30.00,
    "quantity": 100,
    "total_leakage": 3000.00,
    "currency": "INR"
  },
  "unit_conversion_details": {
    "conversion_applied": false,
    "from_unit": null,
    "to_unit": null,
    "factor": null,
    "factor_source": null
  },
  "fx_rate_applied": {
    "conversion_needed": false,
    "from_currency": null,
    "to_currency": null,
    "rate": null,
    "rate_date": null,
    "rate_source": null
  },
  "match_confidence_breakdown": {
    "vendor_match_method": "ALIAS",
    "vendor_match_confidence": 1.0,
    "item_match_method": "FUZZY",
    "item_match_confidence": 0.92,
    "overall_confidence": 0.92
  },
  "duplicate_reference": {
    "original_invoice_id": null,
    "original_invoice_no": null,
    "duplicate_type": null,
    "temporal_distance_days": null
  },
  "quantity_reference": {
    "po_id": null,
    "po_quantity": null,
    "grn_id": null,
    "grn_quantity": null,
    "invoiced_quantity": null,
    "authority_used": null,
    "quantity_difference": null
  },
  "source_documents": [
    {
      "document_id": "uuid",
      "doc_type": "INVOICE",
      "filename": "invoice_001.pdf",
      "sha256_hash": "abc123..."
    },
    {
      "document_id": "uuid",
      "doc_type": "CONTRACT",
      "filename": "contract_tata_2024.pdf",
      "sha256_hash": "def456..."
    }
  ]
}
```

**Rules for populating `evidence_jsonb`:**
- **Rule 1 (Price Mismatch):** Must populate `invoice_reference`, `contract_reference`, `calculation`, `unit_conversion_details`, `fx_rate_applied`, `match_confidence_breakdown`, `source_documents`. Set `duplicate_reference` and `quantity_reference` to null.
- **Rule 2 (Duplicate Invoice):** Must populate `invoice_reference`, `duplicate_reference`, `source_documents`. Set `contract_reference`, `calculation`, `unit_conversion_details`, `fx_rate_applied` to null.
- **Rule 3 (Quantity Mismatch):** Must populate `invoice_reference`, `quantity_reference`, `source_documents`. Set `contract_reference`, `unit_conversion_details`, `fx_rate_applied`, `duplicate_reference` to applicable nulls.

---

### 4.2.2 Immutability Trigger on `leakage_records`

Once a leakage record has `status = 'ACCEPTED'`, certain fields become immutable. This is enforced by a PostgreSQL trigger (created in Phase 5 via Alembic migration).

**Trigger Logic:**
```sql
CREATE OR REPLACE FUNCTION prevent_accepted_leakage_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'ACCEPTED' THEN
        IF NEW.amount IS DISTINCT FROM OLD.amount
           OR NEW.leakage_type IS DISTINCT FROM OLD.leakage_type
           OR NEW.confidence IS DISTINCT FROM OLD.confidence
           OR NEW.evidence_jsonb IS DISTINCT FROM OLD.evidence_jsonb
           OR NEW.rule_applied IS DISTINCT FROM OLD.rule_applied THEN
            RAISE EXCEPTION 'Cannot modify accepted leakage record fields: amount, leakage_type, confidence, evidence_jsonb, rule_applied';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_leakage_immutability
    BEFORE UPDATE ON leakage_records
    FOR EACH ROW
    EXECUTE FUNCTION prevent_accepted_leakage_modification();
```

**What remains mutable after acceptance:**
- `review_notes` — reviewer can add additional notes
- `status` — should not change from ACCEPTED in practice, but the trigger doesn't block status-to-status changes explicitly (application enforces this)

**What is blocked after acceptance:**
- `amount` — financial value cannot be altered
- `leakage_type` — classification cannot be changed
- `confidence` — score cannot be retroactively adjusted
- `evidence_jsonb` — evidentiary record cannot be tampered with
- `rule_applied` — rule identification cannot be changed

---

### 4.3 `document_hashes`

Stores hash fingerprints for document integrity tracking. Used by both the shared hashing layer and Tool B (Document Integrity).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Hash record identifier |
| `document_id` | `UUID` | NOT NULL, FK → `documents.id` | Source document |
| `tenant_id` | `UUID` | NOT NULL | Denormalized for RLS |
| `hash_sha256` | `CHAR(64)` | NOT NULL | SHA-256 hash of file content |
| `hash_type` | `hash_type_enum` | NOT NULL | Purpose of this hash record |
| `upload_sequence` | `INTEGER` | NOT NULL | Monotonically increasing per document |
| `comparison_status` | `comparison_status_enum` | NOT NULL, DEFAULT `'NEW'` | Result of hash comparison |
| `comparison_against_id` | `UUID` | NULLABLE, FK → `document_hashes.id` | Hash record this was compared against |
| `metadata_jsonb` | `JSONB` | NULLABLE | Extracted file metadata (creation date, author, etc.) |
| `risk_score` | `INTEGER` | NULLABLE, CHECK `(risk_score >= 0 AND risk_score <= 100)` | Integrity risk score (Tool B) |
| `flagged_anomalies_jsonb` | `JSONB` | NULLABLE | Array of detected anomaly objects |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Enums:**
```sql
CREATE TYPE hash_type_enum AS ENUM ('BASELINE', 'REUPLOAD', 'PERIODIC_CHECK');
CREATE TYPE comparison_status_enum AS ENUM ('NEW', 'UNCHANGED', 'MODIFIED', 'INCONCLUSIVE');
```

**Indexes:**
```sql
CREATE INDEX idx_doc_hashes_document ON document_hashes(document_id);
CREATE INDEX idx_doc_hashes_tenant ON document_hashes(tenant_id);
```

**RLS Policy:** Applied with tenant isolation.

---

### 4.4 `notifications`

In-app notification records for users.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Notification identifier |
| `tenant_id` | `UUID` | NOT NULL, FK → `tenants.id` | Tenant ownership |
| `user_id` | `UUID` | NOT NULL, FK → `users.id` | Recipient user |
| `message` | `TEXT` | NOT NULL | Notification message |
| `notification_type` | `TEXT` | NOT NULL | Type identifier (e.g., `RUN_COMPLETE`, `RUN_PARTIAL_SUCCESS`) |
| `run_id` | `UUID` | NULLABLE, FK → `analysis_runs.id` | Associated run |
| `read_at` | `TIMESTAMPTZ` | NULLABLE | When the user read the notification |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Creation timestamp |

**Indexes:**
```sql
CREATE INDEX idx_notifications_user_unread ON notifications(tenant_id, user_id, read_at)
    WHERE read_at IS NULL;
```

**RLS Policy:** Applied with tenant isolation.

---

### 4.5 `audit_logs`

Immutable audit trail for all significant actions.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | PK, DEFAULT `uuid_generate_v4()` | Log entry identifier |
| `tenant_id` | `UUID` | NOT NULL | Tenant context |
| `user_id` | `UUID` | NOT NULL | Acting user |
| `action` | `TEXT` | NOT NULL | Action type (e.g., `LEAKAGE_ACCEPTED`, `DOCUMENT_UPLOADED`, `SETTING_CHANGED`) |
| `resource_type` | `TEXT` | NOT NULL | Entity type affected (e.g., `leakage_record`, `document`, `tenant_settings`) |
| `resource_id` | `UUID` | NOT NULL | ID of the affected entity |
| `details_jsonb` | `JSONB` | NULLABLE | Additional context about the action |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | Action timestamp |

**Indexes:**
```sql
CREATE INDEX idx_audit_logs_tenant ON audit_logs(tenant_id);
CREATE INDEX idx_audit_logs_user ON audit_logs(tenant_id, user_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
```

**Immutability:** No UPDATE or DELETE operations are permitted on this table. Application code must enforce this. Audit logs cannot be deleted by regular tenant users — only by the `app_admin` role during tenant data deletion workflows.

**RLS Policy:** Applied with tenant isolation (regular users can only see their tenant's logs).

---

## 5. RLS Policy Template

Every table with `tenant_id` follows this pattern:

```sql
ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;

CREATE POLICY {table_name}_tenant_isolation ON {table_name}
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
```

The application sets the session variable at the start of every request/task:

```sql
SET LOCAL app.current_tenant_id = '{tenant_uuid}';
```

**Tables with RLS applied:** `documents`, `raw_parses`, `vendors`, `vendor_aliases`, `contracts`, `contract_versions`, `contract_line_items`, `invoices`, `invoice_line_items`, `purchase_orders`, `po_line_items`, `grns`, `grn_line_items`, `analysis_runs`, `leakage_records`, `document_hashes`, `notifications`, `audit_logs`, `users`, `tenant_settings`.

**Tables without RLS:** `tenants` (admin-only), `canonical_units` (system-wide reference data), `unit_conversion_factors` (system defaults have `tenant_id = NULL`; tenant overrides are protected by RLS on the non-NULL tenant_id rows).

---

## 6. Migration Strategy

All schema changes go through Alembic. Direct schema edits are **never allowed**.

```bash
# Generate migration
alembic revision --autogenerate -m "description"

# Apply migration
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Check current version
alembic current
```

Every migration must be tested against a clean database before being applied to production.
