# LeakSight V1 — System Architecture

## 1. System Overview

LeakSight is a post-facto financial verification engine that detects commercial leakage in vendor transactions. It is **not** an ERP, a payment processor, a procurement workflow, or a predictive analytics platform. It is a deterministic, explainable, audit-grade evidence generator.

The system operates on three truth layers:

| Truth Layer | Source Documents | Role |
|---|---|---|
| **Commercial Truth** | Contracts, Rate Cards | What was contractually agreed |
| **Operational Truth** | Purchase Orders, GRNs | What was ordered / received |
| **Financial Truth** | Invoices | What was invoiced and paid |

**Leakage exists when Financial Truth exceeds Commercial or Operational Truth.**

---

## 2. End-to-End Data Flow

```
Upload → Parse → RAW Snapshot → Normalize → Canonical Store → Match → Apply Rules → Generate Leakage → Review → Report
```

### 2.1 Stage-by-Stage Breakdown

| Stage | Description | Input | Output | Service |
|---|---|---|---|---|
| **Upload** | User uploads documents (PDF, Excel, CSV, DOCX) via web UI or API. SHA-256 hash computed on receipt. | Raw file bytes | `documents` row + `document_hashes` BASELINE record + file stored on encrypted volume | `api/endpoints/ingest.py` |
| **Parse** | Document routed to appropriate parser based on format. Structured data extracted. | File path + doc_type | `raw_parses` row with `structured_output_jsonb` + `parse_confidence` | `parsers/parser_router.py` → specific parser |
| **RAW Snapshot** | Parse result stored immutably with version tracking. Re-parse creates new `raw_version` row, never overwrites. | ParseResult | `raw_parses` row (new version) | `services/parse_storage_service.py` |
| **Normalize** | Vendor names normalized (strip legal suffixes, lowercase). Item descriptions normalized via `abbreviation_dictionary`. Units standardized. | `raw_parses.structured_output_jsonb` | Canonical layer records (vendors, contracts, invoices, POs, GRNs) | `services/normalization_service.py` |
| **Canonical Store** | Normalized records written to canonical tables. Vendor matching applied (GST → Alias → Fuzzy). | Normalized intermediate data | Rows in canonical tables with vendor linkage | `matching/vendor_matcher.py` + `services/normalization_service.py` |
| **Match** | Invoice line items matched against contracts (by vendor + item + date validity + unit compatibility). PO/GRN matched against invoices. | Canonical invoice + contract + PO/GRN records | Match results with confidence scores | `matching/vendor_matcher.py` + `core/contract_resolver.py` |
| **Apply Rules** | Three deterministic rules applied to each matched invoice line item. | Match results + canonical data | LeakageRecord objects (or None if no leakage) | `rules/rule_engine.py` → `rule1`, `rule2`, `rule3` |
| **Generate Leakage** | Leakage records written to DB with full evidence, confidence, and human-readable explanation. | LeakageRecord objects | `leakage_records` rows with status PENDING | `services/leakage_service.py` |
| **Review** | Human reviewer accepts or rejects each finding. Accepted records become immutable (DB trigger enforced). | Reviewer action (accept/reject + notes) | Updated `leakage_records.status` + audit log entries | `api/endpoints/leakage.py` + `services/leakage_service.py` |
| **Report** | CFO summary, evidence pack (PDF), and Excel export generated from accepted/pending records. | Run ID + tenant context | PDF report, Excel export | `reporting/report_assembler.py` + `reporting/pdf_renderer.py` + `reporting/excel_exporter.py` |

---

## 3. Why Monolithic Backend for V1

LeakSight V1 uses a **single monolithic Python backend** (FastAPI). This is a deliberate architectural decision, not a shortcut.

### Reasons:

1. **Simplicity** — One deployable unit means one build, one deploy, one log stream. For a 1–3 client pilot, microservices add complexity with zero benefit.
2. **Debuggability** — When a leakage record has a wrong amount, the entire trace from upload to rule execution lives in one process. Cross-service debugging over the network is unnecessary overhead for V1.
3. **Speed of development** — A two-person team (founder + technical co-founder) cannot maintain service boundaries, API contracts between services, distributed tracing, and service mesh for V1. Monolith ships faster.
4. **Infrastructure fit** — The deployment target is a single Hetzner CX41 server (4 vCPU, 16GB RAM). There is no Kubernetes, no service mesh, no container orchestrator. Docker Compose runs all containers on one host. A monolith is the natural fit.
5. **Cost** — ₹1,600/month total hosting. Microservices would require more memory, more containers, and more operational overhead for no user-facing benefit.

### What "monolithic" means here:

- **One Docker image** runs both the API server (uvicorn) and the background worker (Celery). Same codebase, different entry points.
- **Internal modularity** is enforced through Python package structure — `/parsers`, `/rules`, `/matching`, `/reporting`, `/services` are separate packages with clear interfaces. Modules can be extracted into services in V2/V3 if needed.
- **Shared database** — One PostgreSQL instance, one schema, with Row-Level Security (RLS) enforcing tenant isolation at the database layer.

---

## 4. Shared Layers

All three product modules (Core Leakage Engine, Tool A, Tool B) share three infrastructure layers. These are **not duplicated** between modules.

### 4.1 Shared Ingestion Layer

All document uploads — regardless of which module will process them — go through a single ingestion pipeline:

```
POST /api/v1/ingest/upload
  → Validate file (size ≤ 200MB, supported format)
  → Compute SHA-256 hash
  → Store file to encrypted volume at /app/data/documents/{tenant_id}/{document_id}/{filename}
  → Create `documents` row in DB
  → Create `document_hashes` BASELINE record
  → Return document_id
```

**Why shared:** A single contract PDF may be used by the Leakage Engine (for price comparison), Tool A (for structuring), and Tool B (for integrity checking). Uploading it once and referencing it by `document_id` avoids duplication and ensures consistent hashing.

### 4.2 Shared Document Storage Layer

All uploaded documents are stored on a single encrypted volume:

```
/opt/leaksight/data/documents/
  └── {tenant_id}/
      └── {document_id}/
          └── {original_filename}
```

- **Encryption at rest**: Hetzner volume encryption (AES-256) covers all stored documents and database data.
- **Access control**: Documents are **never** served directly. All access goes through authenticated API endpoints that enforce tenant isolation.
- **No public URLs**: The `/data/` path is blocked at the Nginx level (`deny all; return 403`).

### 4.3 Shared Hashing & Metadata Extraction Layer

Every uploaded document receives:

1. **SHA-256 hash** — computed on upload, stored in `document_hashes` with `hash_type = BASELINE`.
2. **Metadata extraction** — creation date, last modified date, author, editing software (where available from file metadata).
3. **Re-upload detection** — if the same file is uploaded again, the hash comparison reveals whether the document is `UNCHANGED`, `MODIFIED`, or a new document entirely.

Tool B (Document Integrity) extends this with structural anomaly detection and risk scoring, but the base hashing and metadata layer is shared.

---

## 5. Modular Business Logic

Despite sharing infrastructure layers, each module has **independent business logic** that operates in its own package namespace. No module depends on another module's business logic.

### 5.1 Core Module — Leakage Detection Engine

**Package:** `app/rules/`, `app/matching/`, `app/services/leakage_service.py`, `app/services/analysis_run_service.py`

**Responsibility:** Detect financial leakage by comparing invoices against contracts (Rule 1), detecting duplicates (Rule 2), and flagging quantity mismatches (Rule 3).

**Data dependencies:** Reads from `invoices`, `invoice_line_items`, `contracts`, `contract_versions`, `contract_line_items`, `purchase_orders`, `po_line_items`, `grns`, `grn_line_items`, `vendors`, `vendor_aliases`, `unit_conversion_factors`, `fx_rates`. Writes to `leakage_records`, `analysis_runs`.

### 5.2 Tool A — Contract Structuring Engine

**Package:** `app/structuring/` (future)

**Responsibility:** Convert unstructured contract documents into structured commercial data suitable for ERP import. Extract pricing tables, key clauses (effective date, expiry, amendments). Output structured Excel and ERP-ready JSON/CSV.

**Data dependencies:** Reads from `documents`, `raw_parses`. Writes to `contracts`, `contract_versions`, `contract_line_items` (same canonical tables used by the Leakage Engine).

**Integration point:** When Tool A structures a contract, the Leakage Engine can immediately use that structured data for price comparison. No explicit integration API — they share the canonical data layer.

### 5.3 Tool B — Document Integrity Engine

**Package:** `app/integrity/` (future)

**Responsibility:** Detect potential tampering or integrity risks. SHA-256 comparison, metadata analysis, structural anomaly detection, version comparison, risk scoring (0–100).

**Data dependencies:** Reads from `documents`, `document_hashes`. Writes additional `document_hashes` rows (REUPLOAD, PERIODIC_CHECK types), updates `risk_score` and `flagged_anomalies_jsonb`.

**Isolation:** Tool B never modifies financial data. It flags risk — it does not make financial assertions.

---

## 6. Service Boundaries

### 6.1 API Layer (`app/api/`)

| Service | Responsibility | External Access |
|---|---|---|
| `api/endpoints/ingest.py` | File upload, trigger analysis run, run status | Yes (authenticated) |
| `api/endpoints/leakage.py` | CRUD for leakage records, accept/reject workflow | Yes (authenticated) |
| `api/endpoints/vendors.py` | Vendor list, alias management | Yes (authenticated) |
| `api/endpoints/contracts.py` | Contract list, version management | Yes (authenticated) |
| `api/endpoints/reports.py` | Report generation (PDF, Excel) | Yes (authenticated) |
| `api/endpoints/admin.py` | FX rate upload, tenant settings | Yes (authenticated, admin role) |

### 6.2 Core Services (`app/core/`)

| Service | Responsibility | Called By |
|---|---|---|
| `core/config.py` | Environment variable loading via Pydantic Settings | All services |
| `core/database.py` | SQLAlchemy async engine, session factory | All services |
| `core/security.py` | JWT decode, tenant_id extraction | API middleware |
| `core/middleware.py` | Request logging, tenant context setting | FastAPI middleware chain |
| `core/tenant_context.py` | Sets PostgreSQL session-level `app.current_tenant_id` for RLS | Every request + every Celery task |
| `core/celery_app.py` | Celery initialization with Redis broker | Worker entry point |
| `core/logging.py` | Structured logging with PII/financial data prohibition | All services |
| `core/unit_converter.py` | Unit conversion with factor lookup | Rules engine |
| `core/fx_service.py` | FX rate lookup with PENDING_FX_RATE sentinel | Rules engine |
| `core/contract_resolver.py` | Contract version resolution by vendor + date | Rules engine |

### 6.3 Business Logic Services (`app/services/`)

| Service | Responsibility | Called By |
|---|---|---|
| `services/parse_storage_service.py` | Store parse results, enforce confidence threshold, manage raw versions | Parse task |
| `services/normalization_service.py` | Vendor/item/unit normalization, canonical layer writes | Normalize task |
| `services/leakage_service.py` | Create/accept/reject leakage records, enforce immutability | Analysis run task, API endpoints |
| `services/analysis_run_service.py` | Create/update/query analysis runs | API endpoints, analysis run task |
| `services/notification_service.py` | In-app + email notifications on run completion | Analysis run task |

### 6.4 Matching Layer (`app/matching/`)

| Service | Responsibility | Called By |
|---|---|---|
| `matching/vendor_normalizer.py` | Name normalization (lowercase, strip legal suffixes/punctuation) | Normalization service |
| `matching/vendor_matcher.py` | GST exact → Alias → Blocking key → RapidFuzz matching | Normalization service |
| `matching/item_normalizer.py` | Item description normalization via abbreviation_dictionary | Normalization service |

### 6.5 Rules Layer (`app/rules/`)

| Service | Responsibility | Called By |
|---|---|---|
| `rules/rule_engine.py` | Orchestrator — runs applicable rules for each invoice line item | Analysis run task |
| `rules/rule1_price_mismatch.py` | Contract validity → unit conversion → price comparison | Rule engine |
| `rules/rule2_duplicate_invoice.py` | Exact + near-duplicate detection | Rule engine |
| `rules/rule3_quantity_mismatch.py` | GRN override → PO fallback quantity comparison | Rule engine |

### 6.6 Parsing Layer (`app/parsers/`)

| Service | Responsibility | Called By |
|---|---|---|
| `parsers/base_parser.py` | Abstract base class defining ParseResult contract | All parsers |
| `parsers/parser_router.py` | Format detection and parser routing | Parse task |
| `parsers/excel_parser.py` | Excel/CSV parsing (pandas + openpyxl) | Parser router |
| `parsers/pdf_digital_parser.py` | Digital PDF parsing (pdfplumber + camelot) | Parser router |
| `parsers/pdf_scanned_parser.py` | Scanned PDF OCR (PaddleOCR + PP-Structure) | Parser router |
| `parsers/word_parser.py` | Word document parsing (python-docx) | Parser router |

### 6.7 Reporting Layer (`app/reporting/`)

| Service | Responsibility | Called By |
|---|---|---|
| `reporting/report_assembler.py` | Assemble CFO summary and evidence pack data | Report API |
| `reporting/pdf_renderer.py` | HTML → PDF via WeasyPrint | Report API |
| `reporting/excel_exporter.py` | Excel export via openpyxl | Report API |
| `reporting/templates/` | Jinja2 HTML templates for reports | PDF renderer |

### 6.8 Task Layer (`app/tasks/`)

| Service | Responsibility | Called By |
|---|---|---|
| `tasks/parse_task.py` | Celery task: parse a document | Ingest API trigger |
| `tasks/normalize_task.py` | Celery task: normalize a parsed document | Chained from parse task |
| `tasks/analysis_run_task.py` | Celery task: run full analysis pipeline | Ingest API trigger |

---

## 7. Infrastructure Architecture

### 7.1 Docker Compose Services

```
┌──────────────────────────────────────────────────────────────┐
│                        EXTERNAL NETWORK                      │
│  ┌──────────┐                                                │
│  │  Nginx   │ ← HTTPS (443) / HTTP→HTTPS redirect (80)      │
│  │  (proxy) │                                                │
│  └────┬─────┘                                                │
│       │ proxy_pass → backend:8000                            │
│  ┌────▼─────┐                                                │
│  │ Backend  │ ← FastAPI (uvicorn, 2 workers)                 │
│  │  (API)   │   Memory: 1–2 GB                               │
│  └──────────┘                                                │
└──────────────────────────────────────────────────────────────┘
                          │
                          │ (internal bridge network)
                          │
┌──────────────────────────────────────────────────────────────┐
│                       INTERNAL NETWORK                       │
│  (no outbound internet — bridge with internal: true)         │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                 │
│  │  Worker  │   │ Postgres │   │  Redis   │                  │
│  │ (Celery) │   │   15     │   │    7     │                  │
│  │ 4–10 GB  │   │          │   │  512 MB  │                  │
│  └──────────┘   └──────────┘   └──────────┘                  │
│                                                              │
│  Worker: --concurrency=2, --max-tasks-per-child=50           │
│  Worker: shm_size=2g (PaddleOCR shared memory)               │
│  Postgres: shared_buffers=4GB, work_mem=32MB                 │
│  Redis: appendonly=yes, maxmemory=512mb                      │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 Network Isolation

- **External network**: Nginx and Backend only. User-facing traffic.
- **Internal network** (`internal: true`): Worker, PostgreSQL, Redis. **No outbound internet access.** This is a security and data sovereignty requirement — no client data can leave the server via worker processes.
- Backend is on **both** networks — it serves API requests (external) and communicates with DB/Redis/Worker (internal).

### 7.3 Storage Volumes

| Volume | Mount Point | Purpose | Encryption |
|---|---|---|---|
| Hetzner encrypted volume | `/opt/leaksight/data/` | All persistent data | AES-256 at rest (Hetzner-managed) |
| Postgres data | `/opt/leaksight/data/postgres` | Database files | Covered by volume encryption |
| Redis data | `/opt/leaksight/data/redis` | AOF persistence | Covered by volume encryption |
| Document storage | `/opt/leaksight/data/documents` | Uploaded client files | Covered by volume encryption |
| Backup storage | `/opt/leaksight/data/backups` | pg_dump archives | Covered by volume encryption |

### 7.4 Security Boundaries

1. **TLS termination** at Nginx — all client traffic encrypted in transit.
2. **JWT authentication** on all API endpoints — no unauthenticated access.
3. **PostgreSQL RLS** — tenant isolation enforced at the database query level. Every table with `tenant_id` has `FORCE ROW LEVEL SECURITY` enabled.
4. **No public document URLs** — documents served only via authenticated API. Nginx blocks `/data/` path.
5. **No outbound internet for workers** — internal Docker network only.
6. **No PII/financial data in logs** — enforced at the logging middleware level (Phase 1.3).
7. **UFW firewall** — only ports 22 (SSH), 80 (HTTP redirect), 443 (HTTPS) exposed.
8. **fail2ban** — brute-force SSH protection.

---

## 8. Technology Stack

| Layer | Technology | Version | Why |
|---|---|---|---|
| Backend Framework | FastAPI | 0.110.x | Async, auto-docs, Pydantic validation |
| Task Queue | Celery | 5.3.x | Industry-standard Python task queue |
| Message Broker | Redis | 7.x | Lightweight, sufficient for V1 volume |
| Database | PostgreSQL | 15 | RLS, JSONB, battle-tested for financial data |
| ORM | SQLAlchemy | 2.0.x | Async support, mature ecosystem |
| Migrations | Alembic | 1.13.x | Schema version control |
| PDF Parsing (digital) | pdfplumber | 0.11.x | Best for structured text extraction |
| PDF Parsing (tables) | camelot-py | 1.0.x | Handles complex multi-column tables |
| PDF Parsing (scanned) | PaddleOCR | 2.9.x | Superior to Tesseract for table/layout detection |
| Excel/CSV Parsing | pandas + openpyxl | 2.2.x / 3.1.x | Standard data processing |
| Word Parsing | python-docx | 1.1.x | Standard Word file processing |
| Fuzzy Matching | RapidFuzz | 3.6.x | Deterministic, fast (C++ core), no GPU |
| PDF Report Generation | WeasyPrint | 62.x | HTML-to-PDF with full CSS control |
| Frontend | React + TypeScript | 18.x / 5.x | Component-based, type-safe |
| Frontend Data | TanStack Query + Table | 5.x / 8.x | Server state management + data grids |
| Reverse Proxy | Nginx | alpine | TLS, upload limits, static file serving |
| Containerization | Docker + Compose | latest | Standard deployment packaging |

---

## 9. Explicitly Out of Scope for V1

The following are **not** included in the V1 architecture. This is deliberate, not a shortcut:

- **Kubernetes** — Single-server deployment. Docker Compose is sufficient.
- **Managed cloud services** (RDS, ElastiCache, S3) — Hetzner single server only.
- **Microservices** — Monolith chosen for simplicity and debuggability.
- **Vector embeddings / ML models** for matching — RapidFuzz is deterministic and explainable.
- **Real-time processing** — Batch/quarterly usage model. No websockets, no streaming.
- **Outbound internet from workers** — Data sovereignty requirement.
- **External AI APIs** (OpenAI, Claude, etc.) for document processing — All processing local.
- **Multi-region deployment** — Single server, single region.
- **Autoscaling** — Fixed concurrency, manual server upgrade if needed.
- **SOC2 / ISO / PCI compliance** — Not required for V1 pilot.
- **Direct ERP API integration** — File export only (Excel, CSV, JSON).
- **OAuth / SSO** — Simple JWT authentication for V1.
