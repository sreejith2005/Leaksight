# DECISIONS.md — LeakSight V1 Architectural Decision Log

This document records all significant architectural decisions made for LeakSight V1. Each entry is immutable once recorded. New decisions are appended at the bottom. Decisions are never deleted — if a decision is superseded, a new entry is added referencing the original.

---

## ADR-001: Monolithic Backend Over Microservices

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** LeakSight V1 is a pilot product targeting 1–3 tenants. The deployment target is a single Hetzner CX41 server (4 vCPU, 16GB RAM). The team is small and speed-to-market matters.
**Decision:** Build a monolithic Python backend with internal modularity via Python packages. Single Docker image, two entry points (API server + Celery worker).
**Rejected Alternatives:**
- **Microservices** — Overhead of inter-service communication, deployment complexity, debugging difficulty, and operational cost are unjustified for a pilot with 1–3 tenants.
- **Serverless (Lambda/Cloud Functions)** — Cold starts unacceptable for batch processing. Vendor lock-in conflicts with Hetzner deployment strategy. Cost unpredictable.
**Consequences:**
- Simpler deployment and debugging
- Shared in-process state reduces serialization overhead
- Must enforce internal boundaries via package structure, not network isolation
- Scaling beyond 1 server requires re-architecture (acceptable — V1 is a pilot)

---

## ADR-002: RapidFuzz Over Vector Embeddings for Matching

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** Item description matching (invoice line → contract line) and vendor name matching require fuzzy string comparison. Two approaches were considered: deterministic string similarity (RapidFuzz) vs. ML-based semantic similarity (vector embeddings via sentence-transformers or similar).
**Decision:** Use RapidFuzz (`token_sort_ratio`) for all fuzzy matching tasks.
**Rejected Alternatives:**
- **Vector embeddings (sentence-transformers, OpenAI embeddings)** — Non-deterministic across model versions. Same inputs may produce different match scores after model updates. Requires GPU or large CPU allocation. Introduces opaque "black box" matching that cannot be explained to CFOs.
- **fuzzywuzzy / thefuzz** — Pure Python implementation, significantly slower than RapidFuzz. RapidFuzz is a drop-in replacement with C++ core.
- **Levenshtein distance** — Does not handle token reordering (e.g., "Steel TMT 12mm" vs "12mm TMT Steel").
**Consequences:**
- 100% deterministic: same inputs always produce same score
- Explainable: "matched with 87% string similarity" is understandable by non-technical users
- No GPU required — runs on CPU, fits within Hetzner CX41 constraints
- May miss semantically similar but lexically different items (e.g., "cement" vs "binding agent") — accepted trade-off for V1

---

## ADR-003: PaddleOCR Over Tesseract for Scanned PDF Processing

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** Scanned PDF invoices need OCR processing. The system must extract structured data (tables, line items) from scanned images, not just raw text.
**Decision:** Use PaddleOCR 2.9.x with PP-Structure for scanned PDF processing.
**Rejected Alternatives:**
- **Tesseract 5** — Good for raw text extraction but poor at table detection and layout analysis. Requires significant post-processing to reconstruct table structure. No built-in layout analysis.
- **Google Cloud Vision** — Excellent accuracy but requires outbound internet (violates ADR-006). Per-page pricing adds unpredictable cost. Vendor lock-in.
- **AWS Textract** — Same internet/cost/lock-in issues as Google Vision.
**Consequences:**
- Superior table and layout detection out of the box
- Runs fully offline — no internet required (critical for worker isolation)
- Mobile model variant keeps memory usage manageable (~500MB per page)
- Must use page-by-page processing with gc.collect() to avoid OOM on CX41
- ≥70% accuracy target for scanned PDFs (lower than digital PDFs — accepted)

---

## ADR-004: PostgreSQL RLS for Tenant Isolation

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** LeakSight is multi-tenant. Financial data must be strictly isolated between tenants. A data leak between tenants would be a critical security and trust failure.
**Decision:** Use PostgreSQL Row-Level Security (RLS) policies on all tenant-scoped tables. Application sets `app.current_tenant_id` via `SET LOCAL` at the start of each request.
**Rejected Alternatives:**
- **Schema-per-tenant** — Increases migration complexity (must run migrations N times). Connection pooling becomes harder. Doesn't scale well beyond ~10 tenants (acceptable for V1 but adds operational burden).
- **Application-level filtering only** — Single missing WHERE clause = data leak. Too fragile for financial data. Defence-in-depth demands database-level enforcement.
**Consequences:**
- Database-enforced isolation — even a buggy query cannot return another tenant's data
- Two database roles: `app_admin` (bypasses RLS for migrations) and `app_tenant_user` (subject to RLS)
- Every tenant-scoped table must include `tenant_id UUID NOT NULL` column
- Slight query performance overhead from RLS policy evaluation (negligible at pilot scale)

---

## ADR-005: No Real-Time Processing

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** LeakSight processes procurement documents in quarterly batches. The typical workflow is: upload a batch of invoices/contracts/POs → trigger analysis → review results days/weeks later.
**Decision:** All processing is batch-only. No WebSockets, SSE, streaming, or real-time push notifications.
**Rejected Alternatives:**
- **WebSocket-based live updates** — Adds frontend/backend complexity for a feature that provides minimal value in a quarterly-use product. Users can poll for status.
- **Server-Sent Events (SSE)** — Simpler than WebSockets but still adds unnecessary infrastructure. Nginx long-lived connection config adds risk.
**Consequences:**
- Simpler architecture — standard request/response HTTP only
- Status checking via polling (`GET /api/v1/ingest/runs/{run_id}/status`)
- Notifications stored in database, fetched on page load — not pushed
- If V2 requires real-time features, this decision can be revisited

---

## ADR-006: No Outbound Internet from Worker Containers

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** Celery workers process sensitive financial documents (invoices, contracts, POs). Data sovereignty and security require that processed data never leaves the server.
**Decision:** Worker containers are placed on an internal-only Docker network with no outbound internet access. All dependencies (OCR models, dictionaries, libraries) are baked into the Docker image at build time.
**Rejected Alternatives:**
- **Allow outbound for specific APIs only** — Creates firewall complexity. Risk of misconfiguration. "Allow-list" approach is fragile and requires ongoing maintenance.
- **Outbound with data redaction** — Adds another layer of complexity. Cannot guarantee 100% redaction of sensitive financial data.
**Consequences:**
- FX rates must be manually uploaded (cannot fetch from XE/ECB APIs)
- OCR models must be included in Docker image (increases image size by ~300MB)
- No auto-updating of any dependency at runtime
- Maximum data sovereignty — financial documents never leave the server

---

## ADR-007: WeasyPrint for PDF Report Generation

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** LeakSight generates evidence pack PDFs and CFO summary reports. The rendering engine must produce professional-quality PDFs with tables, headers, and branding.
**Decision:** Use WeasyPrint 62.x for all PDF generation. Reports are authored as HTML+CSS templates, then rendered to PDF.
**Rejected Alternatives:**
- **ReportLab** — Powerful but requires imperative Python code to position every element. HTML+CSS templating is faster to develop and easier to maintain.
- **wkhtmltopdf** — Requires headless browser binary. Security concern (running a browser engine on a server processing financial data). Deprecated upstream.
- **Puppeteer/Playwright** — Requires Chromium. Too heavy for a CX41 server. Overkill for structured reports.
**Consequences:**
- Reports authored as Jinja2 HTML templates with CSS styling
- Full CSS support (flexbox, grid, @page rules, headers/footers)
- No JavaScript execution in reports (WeasyPrint does not run JS — this is a feature, not a limitation)
- Pip install, no system binary dependencies (unlike wkhtmltopdf)

---

## ADR-008: Docker Compose Over Kubernetes

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** LeakSight V1 is a pilot deployment on a single Hetzner CX41 server. The target is 1–3 tenants with quarterly batch processing.
**Decision:** Deploy using Docker Compose on a single server. No container orchestration, no Kubernetes, no Swarm.
**Rejected Alternatives:**
- **Kubernetes (K3s, K8s)** — Massive operational overhead for a single-server deployment. Requires learning curve, YAML complexity, and ongoing maintenance. Unjustified for 1–3 tenants.
- **Docker Swarm** — Less complex than K8s but still adds unnecessary abstraction for single-server deployment.
- **Bare metal (no containers)** — Loses reproducibility, environment isolation, and easy deployment. Not acceptable.
**Consequences:**
- Simple `docker-compose up -d` deployment
- All services defined in a single `docker-compose.yml`
- Scaling requires either vertical scaling (bigger server) or re-architecture
- Cost: ~₹1,600/month for Hetzner CX41 (vs. ₹10,000+/month for managed K8s)

---

## ADR-009: Three-Layer Database Schema (RAW → Canonical → Derived)

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** Documents are uploaded in various formats with inconsistent data quality. The system needs to preserve original parsed data while maintaining clean, normalized data for analysis.
**Decision:** Three-layer database schema:
- **RAW layer** — Append-only storage of parsed document data exactly as extracted. Never modified.
- **Canonical layer** — Normalized, validated business entities (vendors, contracts, invoices). Mutable (can be updated with corrections).
- **Derived layer** — Analysis results (leakage records, audit logs, notifications). Conditionally immutable (accepted records cannot be modified).
**Rejected Alternatives:**
- **Single-layer (parse directly to final tables)** — Loses original data. Cannot re-analyze with different rules. Cannot debug parsing errors.
- **Two-layer (raw + final)** — No clear separation between business entities and analysis results. Harder to reason about data lifecycle.
**Consequences:**
- Full audit trail — can always trace a leakage record back to the original parsed data
- Re-parsing creates a new `raw_parses` row (append-only)
- Re-analysis can reference both current canonical data and historical raw data
- More tables and joins — acceptable complexity trade-off for data integrity

---

## ADR-010: Pydantic V2 for All Data Validation

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** FastAPI uses Pydantic for request/response validation. Pydantic V2 was released with significant performance improvements (5-50x faster) and a new Rust-based core.
**Decision:** Use Pydantic V2 for all request schemas, response schemas, internal data models, and configuration.
**Rejected Alternatives:**
- **Pydantic V1** — Slower, deprecated, will stop receiving security updates.
- **attrs + cattrs** — Less integrated with FastAPI. Would require custom serialization.
- **dataclasses** — No runtime validation. Would need separate validation layer.
**Consequences:**
- Must use Pydantic V2 syntax (`model_validator` instead of `validator`, `ConfigDict` instead of `Config`)
- FastAPI 0.110+ required for full Pydantic V2 compatibility
- All schemas must use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility

---

## ADR-011: Celery for Background Task Processing

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** Document parsing and analysis are CPU-intensive, long-running operations that cannot be performed in the API request/response cycle.
**Decision:** Use Celery 5.3.x with Redis as broker (DB 0) and result backend (DB 1).
**Rejected Alternatives:**
- **RQ (Redis Queue)** — Simpler but lacks task chaining, retries, and monitoring features needed for multi-step analysis pipelines.
- **Dramatiq** — Good alternative but smaller community and fewer monitoring tools.
- **asyncio background tasks** — No persistence, no retry, no monitoring. Tasks lost on server restart.
**Consequences:**
- Workers configured with `--max-tasks-per-child=50` (prevents memory leaks from PaddleOCR)
- `--concurrency=2` (matches CX41 CPU allocation strategy)
- Redis AOF persistence enabled — queued tasks survive Redis restart
- Flower or similar tool for task monitoring in production

---

## ADR-012: Immutability Trigger on Accepted Leakage Records

**Date:** 2026-02-21
**Status:** ACCEPTED — LOCKED
**Context:** Once a CFO or reviewer accepts a leakage finding, the financial data in that record must be immutable for audit purposes. Application-level enforcement is insufficient — a bug or direct SQL could modify accepted records.
**Decision:** PostgreSQL trigger function `prevent_accepted_leakage_modification()` that blocks `UPDATE` on protected columns (`amount`, `leakage_type`, `confidence`, `evidence_jsonb`, `rule_applied`) when `status = 'ACCEPTED'`.
**Rejected Alternatives:**
- **Application-level validation only** — A single missed check in any code path = audit integrity violation. Database-level enforcement is defence-in-depth.
- **Separate immutable audit table** — Adds complexity. The trigger approach achieves immutability in-place.
**Consequences:**
- Status can still be changed (e.g., an admin might need to change from ACCEPTED to another state in exceptional cases — the trigger only protects financial data columns)
- `review_notes`, `reviewed_by`, `reviewed_at` can still be updated
- Direct SQL `UPDATE` on protected columns also blocked — provides true database-level guarantee

---

## ADR-013: Manual Review for Overlapping Contract Versions (Replaces Auto-Resolution)

**Date:** 2026-03-01
**Status:** ACCEPTED — LOCKED
**Context:** When multiple contract versions are valid for a vendor on an invoice date (OVERLAP status from the contract resolver), the system must decide how to evaluate Rule 1 (Price Mismatch). A previous implementation (`_resolve_overlap_by_item()`) auto-resolved overlaps by selecting the contract version with the highest matching unit price. This was undocumented and not auditable.
**Decision:** When multiple contract versions cover the same invoice date, the system creates a leakage record with `status=PENDING`, `confidence=0.50`, and an explanation stating "Multiple contract versions valid on this date — manual review required to confirm correct pricing." The system does NOT auto-resolve by picking the highest price.
**Rejected Alternatives:**
- **Auto-resolve by highest price** — Silently picks the most vendor-favorable contract price. Not auditable. A CFO cannot verify why one version was chosen over another. Implemented previously under time pressure and removed in this session.
- **Auto-resolve by latest version** — Assumes the newest contract version is always correct. This is not true when backdated amendments exist.
- **Skip entirely (return None)** — Silently drops the comparison. Violates the principle that overlaps should be visible to reviewers.
**Consequences:**
- Overlapping contract versions are visible in the leakage dashboard at 0.50 confidence
- Reviewers can inspect the evidence (which includes all overlapping version IDs) and manually confirm the correct pricing
- May increase the number of PRICE_MISMATCH records that require review — acceptable trade-off for auditability
- `_resolve_overlap_by_item()` function is retained in rule1_price_mismatch.py for reference but no longer called
