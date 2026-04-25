# AGENTS.md — LeakSight Enterprise Commercial Intelligence Suite

## Project Overview

LeakSight is an enterprise financial control system that detects vendor overcharging by comparing invoices against contracts and purchase orders. It is NOT an ERP, payment processor, or predictive analytics tool. It is a post-facto verification engine that produces audit-grade evidence.

## Context Files — Read These First

These files live in the LeakSight Claude project space. Read all of them before writing any code. They contain the complete product requirements, architecture decisions, and business rules.

```
leaksight_MASTER_PROJECT_CONTEXT_FILE.docx  → Core product philosophy, three-truth model, non-negotiable rulesLeakSight_v1_1__PRD.pdf  → PRIMARY: All three module requirements (Core, Tool A, Tool B), inputs, outputs, constraintsLeakSight_v1__PRD.pdf  → Core module original requirements — do not break anything defined hereLeakSight_V1_build_order_checklist.docx  → Complete phase-by-phase build record, existing patterns to followleaksight_master_plan_1.docx  → Final tech stack decisions, data model layers, library choices, locked decisionsDEPLOYMENT_RUNBOOK.md  → Production deployment steps, Docker setup, backup/restore, Tool A worker notesLeakSight_Infra_Guide_V2.md  → Infrastructure constraints, server sizing, nginx config, PaddleOCR memory managementHOW_TO_START.md  → Exact commands to start all services locallyFINAL_SESSION_REPORT.md  → Current system state, what's built, test counts, known issuesKNOWN_UX_ISSUES.md  → All documented UX limitations across Core Module, Tool A — P1/P2/P3 priorityDEMO_WALKTHROUGH.md  → Step-by-step demo guide for both core module (Steps 1-11) and Tool A (Steps 12-19)TOOL_A_README.md  → Tool A user and developer guide, supported formats, limitations, integration notesTOOL_A_BUILD_ORDER.md  → Completed Tool A build record, all files created, all endpoints added
```

---

## Environment

-   Project root: `C:\Users\user\Leaksight_recovered_git`
-   Python binary: `.\.venv\Scripts\python.exe` — use the project venv for all backend commands
-   PostgreSQL: Docker, port **5434** (NOT 5432), database `leaksight_dev`, user `leaksight_user`, password `testpass123`
-   Redis: Docker, port 6379
-   Backend: FastAPI on port 8000
-   Frontend: React/Vite on port 5173
-   Auth: create a local admin with `.\.venv\Scripts\python.exe -m backend.app.scripts.create_tenant --name "Local Dev" --email "admin@test.com"` after migrations; do not store passwords in docs
-   Known pilot tenant ID: `edeb6d4c-6b06-4909-9bf2-f97ef0a149c8`
-   Known admin user ID: `131e5f66-fa37-4383-a020-ae29d5ab683e`
-   Alembic config lives in `backend/` folder — always `cd backend` before running alembic commands

---

## How to Start the System

Three terminals required, always from project root:

**Terminal 1 — Backend:**

```
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — Celery Worker:**

```
.\.venv\Scripts\python.exe -m celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo -Q default,parse,analysis,structuring,revalidation
```

`--pool=solo` is mandatory on Windows. All five queues must be included.
The `-Q default,parse,analysis,structuring,revalidation` list is unchanged for the security hardening work. No new queues were added.
Verify `document_integrity.run_analysis` appears in `celery inspect registered`; if it is missing, Tool B analyze requests will queue but never persist results.

**Terminal 3 — Frontend:**

```
cd frontend && npm.cmd run dev
```
Use npm.cmd instead of npm in PowerShell on this machine

Docker Desktop must be running before any of the above. Verify with `docker ps` — you should see the local Postgres and Redis services from `docker-compose.dev.yml`.
Docker command is docker compose -f docker-compose.dev.yml up -d on this machine — not docker compose up -d

---

## Architecture

-   Monolithic FastAPI backend — not microservices
-   Three-layer database: RAW (immutable snapshots) → Canonical (normalized data) → Derived (analysis results)
-   Async processing via Celery — documents are never processed synchronously
-   PostgreSQL Row-Level Security (RLS) enforced on all tenant tables via `SET LOCAL app.current_tenant_id`
-   All workers have NO outbound internet access — all processing is local and offline
-   No external AI/LLM APIs — all extraction is rule-based

---

## Product Structure

Four modules, all in the same monolith:

**Core Module** — Vendor Price Leakage Detection Engine (COMPLETE)Detects three types of financial leakage:

-   Rule 1: Invoice price exceeds contract price (PRICE_MISMATCH)
-   Rule 2: Same invoice submitted twice (DUPLICATE_INVOICE)
-   Rule 3: Invoice quantity exceeds PO/GRN quantity (QUANTITY_MISMATCH)

**Tool A** — Contract Structuring & ERP Mapping Engine (COMPLETE)Extracts pricing tables and commercial clauses from contract documents. Exports to Excel, ERP JSON, or directly into the core module's canonical contract tables via LeakSight Import.

**Tool B** — Document Integrity & Tamper Detection Engine (IN PROGRESS)Priority 3 per PRD v1.1 — build after Tool A is in production. SHA-256 hashing foundation already exists in `document_hashes` table. Version comparison must treat same-tenant uploads with the same `original_filename` and `doc_type` as prior versions even when they create a new `document_id`.

**Tool C** — Company & Employee Document Revalidation Engine (COMPLETE)
Tracks expiry and validity of employee and vendor compliance documents.
Classifies documents, extracts dates via regex and NLP, alerts on expiry,
supports manual date entry, and tracks compliance per subject.

---

## Project Structure

```
backend/  app/    api/              # Core module API routers    core/             # Celery, config, DB session, security, middleware    db/               # Alembic migrations    models/           # SQLAlchemy ORM models (core module)    parsers/          # Document parsers (PDF, Excel, Word, OCR)    matching/         # Vendor normalization, fuzzy matching    rules/            # Leakage detection rules engine    reporting/        # WeasyPrint PDF reports, Excel export    services/         # Business logic layer    tasks/            # Celery task definitions (default, parse, analysis queues)    tools/      contract_structuring/    # ALL Tool A code lives here        extractors/            # pdf_extractor, docx_extractor, excel_extractor                               # table_normalizer, clause_extractor                               # multi_page_stitcher, version_detector        exporters/             # excel_exporter, erp_json_exporter        models.py              # Tool A SQLAlchemy models        schemas.py             # Pydantic request/response schemas        router.py              # FastAPI router mounted at /api/v1/structuring        service.py             # create_structuring_run()        tasks.py               # Celery tasks on structuring queue  tests/    tools/            # Tool A unit and API tests    test_*.py         # Core module testsfrontend/  src/    api/              # All API calls (leakage.ts, structuring.ts, contracts.ts, etc.)    components/      layout/         # Sidebar, TopBar, Layout      structuring/    # Tool A: LineItemTable, ClausePanel, ConfidenceFlag,                      #         ColumnRoleMapper, StructuringRunCard      ui/             # Shared: DataTable, StatusBadge, GiltDivider, MetricDisplay,                      #         ConfidenceBar, SectionHeader, FormField etc.    pages/      structuring/    # Tool A pages: Runs, NewRun, RunDetail, ContractReview, Export      *.tsx           # Core module pages: Dashboard, Upload, LeakageReview,                      #                   Vendors, Contracts, Reports, Admindata/  demo/               # Core module demo files (Contracts_Demo.xlsx etc.)  demo_tool_a/        # Tool A demo files (CTR-TOOL-001_v1.xlsx etc.)
```

Tool C backend code lives under `backend/app/tools/document_revalidation/`. Its API router is mounted at `/api/v1/revalidation`, and its Celery tasks run on the `revalidation` queue.

Under `tools/`, Tool C structure is:

```
document_revalidation/  # ALL Tool C code lives here
  date_extractor.py     # spaCy + regex date extraction from raw_parses
  models.py             # 4 SQLAlchemy models
  schemas.py            # Pydantic V2 schemas
  service.py            # Business logic, _compute_status, expiry check
  tasks.py              # Celery tasks on revalidation queue
  router.py             # FastAPI router at /api/v1/revalidation
```

---

## Database

### Current Tables (34 total)

**Core Module tables:** `tenants`, `users`, `documents`, `raw_parses`, `vendors`, `vendor_aliases`, `canonical_units`, `unit_conversion_factors`, `fx_rates`, `contracts`, `contract_versions`, `contract_line_items`, `invoices`, `invoice_line_items`, `purchase_orders`, `po_line_items`, `grns`, `grn_line_items`, `analysis_runs`, `leakage_records`, `document_hashes`, `tenant_settings`, `notifications`

**Tool A tables:** `contract_structuring_runs`, `contract_structuring_run_documents`, `raw_contract_tables`, `extracted_line_items`, `extracted_clauses`, `contract_structuring_exports`

**Tool C tables:** `revalidation_subjects`, `revalidation_doc_catalog`, `revalidation_documents`, `revalidation_alerts`

### Database Rules

-   Every new table: UUID primary key, `tenant_id UUID NOT NULL`, RLS policy, `created_at` timestamp
-   All composite unique constraints must include `tenant_id`
-   Never modify existing migrations — only ADD new migration files
-   Run alembic from `backend/` directory
-   Always review autogenerated migration before applying — confirm it only changes what you intended
-   Apply from `backend/` with: `..\.venv\Scripts\python.exe -m alembic upgrade head`

---

## Non-Negotiable Business Rules

These come directly from the PRD and must never be violated:

-   **NEVER guess or fabricate financial values** — if a price cannot be extracted with evidence, store NULL with `needs_review = true`
-   **NEVER fill missing contract prices** — missing data stays NULL, never inferred
-   **NEVER make pricing assumptions** — this applies to extraction, normalization, and reporting
-   **Accepted/Confirmed records are immutable** — once a leakage record is ACCEPTED or a line item is CONFIRMED, financial fields cannot be edited. Enforced by DB trigger AND API (returns 409)
-   **Tenant isolation is absolute** — return 404 (not 403) for cross-tenant resource requests
-   **Deterministic processing** — same input must always produce identical output
-   **No outbound internet in workers** — no API calls from Celery tasks
-   **No trailing slashes on FastAPI route definitions** — causes Authorization header to be stripped on redirect
-   **All processing runs locally** — no external AI/LLM APIs for document processing

---

## Currency and Locale

-   Default `base_currency` is **INR** — this is a **tenant-level setting**, not a hardcoded system requirement
-   Each tenant can have their own `base_currency` configured in `tenant_settings`
-   The `fx_rates` table handles multi-currency — rates are pre-loaded, never fetched live
-   If an invoice has a currency with no FX rate available, leakage record is created with status `PENDING_FX_RATE` — never calculated with a guessed rate
-   Date parsing uses `python-dateutil` with `dayfirst=True` — appropriate for the date format conventions in the demo data, but not hardcoded as an India-only rule

---

## Tech Stack

**Backend parsing libraries (all already installed):**

-   `pdfplumber` — digital PDF text and table extraction
-   `camelot-py` + `ghostscript` — complex table extraction from PDFs
-   `PaddleOCR + PP-Structure` — scanned PDF OCR (memory-intensive: 6–10 GB on large files)
-   `pandas + openpyxl` — Excel/CSV
-   `python-docx` — Word documents
-   `spaCy en_core_web_sm` — NLP for clause extraction — load ONCE at module level, never per-document
-   `python-dateutil` — robust date parsing
-   `RapidFuzz` — fuzzy vendor name matching, no vector embeddings
-   `WeasyPrint` — HTML to PDF reports — works in Docker, fails on Windows native (auto-fallback to Excel)

**Frontend stack:**

-   React + TypeScript (strict)
-   TanStack Query — all data fetching and cache management
-   TanStack Table — all data tables
-   Ledger Noir design system
-   No new npm packages without explicit need

---

## Design System (Ledger Noir)

Dark mode is default. Light mode available via toggle in TopBar.

**Dark mode tokens:**

-   Background: `#08090D`
-   Surface 1: `#0F1117`
-   Accent: `#C9A84C` (aged gold)
-   Text primary: `#E8E9ED`

**Semantic colours (both modes):**

-   Success/green: `#2DA66B` — COMPLETE, ACCEPTED, CONFIRMED
-   Danger/red: `#D94848` — FAILED, REJECTED
-   Warning/amber: `#D4A72C` — PARTIAL_SUCCESS, PENDING, PENDING_FX_RATE

**Fonts:**

-   Display/KPI: Newsreader (Google Fonts)
-   Body/UI: Plus Jakarta Sans (Google Fonts)
-   Monospace: JetBrains Mono

**Rules:**

-   Always use CSS variables — never hardcode hex values in components
-   No new CSS frameworks — design system only
-   All new pages must work in both light and dark mode

---

## API Patterns

-   All core module endpoints under `/api/v1/`
-   Tool A endpoints under `/api/v1/structuring/`
-   Tool C endpoints under `/api/v1/revalidation/`
-   Auth: JWT Bearer token from `POST /api/v1/auth/token` with `{email, password}`
-   Pagination: `page` (default 1), `page_size` (default 20, max 100)
-   Error format: `{"detail": "message"}`
    -   401 — missing/invalid token
    -   404 — not found or belongs to different tenant (do not reveal existence)
    -   409 — attempt to edit immutable record
    -   422 — validation failure
-   No trailing slashes on any endpoint path

---

## Testing

## Security

Six security measures implemented:

1. Brute force protection: 10 failed attempts in 15 min → 429 lockout
2. JWT expiry (60 min) + logout blacklist via `revoked_tokens` table
3. File upload validation: magic bytes, filename sanitisation, ZIP bomb checks
4. Security headers on all API responses via middleware
5. Authentication audit trail: `LOGIN_FAILED` and `LOGIN_SUCCESS` in `audit_logs`
6. Security runbook at `docs/SECURITY_RUNBOOK.md`

Run from project root:

```
.\.venv\Scripts\python.exe -m pytest backend/tests/ --tb=short -q
```

**Current baseline: 719 passed, 17 skipped, 14 errors**

The 14 errors are pre-existing — `test_phase2_models.py` attempts PostgreSQL connection on port 5599 which does not exist. These are NOT regressions. Ignore them.

A real regression = passed count drops below 719 OR a previously passing test now fails.

Tool A tests only:

```
.\.venv\Scripts\python.exe -m pytest backend/tests/tools/ -v --tb=short
```

TypeScript check (must be zero errors before any frontend change is complete):

```
cd frontend && npm.cmd exec -- tsc --noEmit
```

Tool B verification notes:

- `GET /api/v1/integrity/documents/{id}` must preserve `risk_score = null` until Celery writes the analysis result. Do not coerce pending analysis to `0`.
- The integrity detail page polls the report endpoint every 3 seconds while `risk_score` is `null` and stops when a non-null score is returned.

---

## Demo Data

**Core module demo:**

```
.\.venv\Scripts\python.exe _upload_demo_data.py
```

Always produces exactly 6 findings totalling ₹1,79,500 across 3 vendors. Run ID saved to `DEMO_RUN_ID.txt`.

**Tool A demo:**

```
.\.venv\Scripts\python.exe _generate_tool_a_demo_data.py   # creates Excel files
.\.venv\Scripts\python.exe _run_tool_a_demo.py              # full end-to-end verification
```

Produces 8 confirmed line items for CTR-TOOL-001 (Acme Supplies Ltd) written to canonical contracts.

**Important:** After uploading documents manually via the UI, wait 15–45 seconds for Celery to finish parsing before triggering an analysis run. If a run completes in 2–3 seconds with zero findings, the worker was not running or parsing was not yet complete — do not investigate the rules engine.

---

## Key Management Scripts

```
_upload_demo_data.py              # Core module demo upload + verification_run_tool_a_demo.py               # Tool A end-to-end verification_generate_tool_a_demo_data.py     # Generate Tool A demo Excel files_run_tool_a_structuring.py        # Manual Tool A pipeline test
_run_revalidation_demo.py         # Tool C end-to-end verification
```

---

## Known Issues — Do Not Investigate

These are documented, intentional limitations:

-   `test_phase2_models.py` 14 errors on port 5599 — environment issue, not a bug
-   WeasyPrint PDF export returns 503 on Windows native — auto-falls back to Excel — works in Docker
-   Progress percentage can show >100% — cosmetic only, no functional impact
-   Export listing may appear empty immediately after triggering — refresh after 3–5 seconds (Celery timing)
-   Dashboard KPIs show latest run only — by design for V1

Tool A extraction pipeline: Format-agnostic as of this fix.
- TableNormalizer handles any table structure via fuzzy role matching
  and positional fallback. Never rejects tables for having unusual headers.
- Currency resolved via 4-level priority chain: column header >
  cell symbol > document default > None. Never defaults to INR.
- Multiple price columns produce multiple line items (one per currency column).
- MULTI_CURRENCY_CONFLICT only fires on genuinely ambiguous single columns.
- PDF: tiered strategy (pdfplumber default → text mode → camelot lattice →
  camelot stream → text regex → OCR). Never returns zero without trying all.
- DOCX: table extraction with paragraph fallback.
- Excel: all sheets processed, dynamic header detection.

Full list in `KNOWN_UX_ISSUES.md`.

---

## Agent Behaviour Rules

-   Never modify existing Alembic migrations — only add new ones
-   Never change existing Celery queue names — only add to them
-   Never modify leakage engine logic when working on Tool A or Tool B
-   Never add backward compatibility — system is pre-launch with no real data
-   The 719 test baseline must be maintained after every change
-   When adding a DB column, always check if it also needs updating in: SQLAlchemy model, Pydantic schema, API response mapping, TypeScript interface, and frontend component
-   spaCy model loaded once at module level — never inside a loop or per-document function
-   All Tool A code stays under `backend/app/tools/contract_structuring/`
-   All Tool C code stays under `backend/app/tools/document_revalidation/`
-   Do not scatter new files outside their designated module directory
