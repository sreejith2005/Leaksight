# LeakSight V1 — Final Pre-Pilot Session Report

**Date:** 2025-07-02  
**Starting Readiness:** 49/52 YES  
**Final Readiness:** 52/52 YES  

---

## Task 1: Evidence Pack PDF (Item 5.2) ✅

**Objective:** Prove WeasyPrint renders the evidence_pack.html template to a valid PDF inside Docker.

**Result:**
- Built minimal Docker image (`Dockerfile.weasyprint-test`) with WeasyPrint + GTK dependencies
- Rendered `evidence_pack.html` with 5 sample findings → 26 KB valid PDF
- PDF contains correct header, summary table, and finding detail sections

**Artifact:** `Dockerfile.weasyprint-test`

---

## Task 2: Curated Demo Dataset (Item 8.4) ✅

**Objective:** Create a demo dataset with known, pre-calculated leakage that the system detects exactly.

**Result: 6/6 PASS** — All expected findings matched exactly.

### Dataset
| File | Records |
|------|---------|
| Contracts_Demo.xlsx | 8 contracts across 3 vendors |
| Invoices_Demo.xlsx | 20 invoices (single file) |
| PO_Demo.xlsx | 6 purchase orders |
| Demo_Expected_Output.xlsx | 6 expected findings (answer key) |

### Expected vs Detected Findings

| # | Type | Invoice | Vendor | Expected ₹ | Detected ₹ | Status |
|---|------|---------|--------|------------|------------|--------|
| 1 | PRICE_MISMATCH | INV-DEMO-004 | TechServ India | 7,000 | 7,000 | ✅ MATCH |
| 2 | PRICE_MISMATCH | INV-DEMO-012 | BuildRight Materials | 13,000 | 13,000 | ✅ MATCH |
| 3 | PRICE_MISMATCH | INV-DEMO-015 | Acme Supplies | 7,500 | 7,500 | ✅ MATCH |
| 4 | DUPLICATE_INVOICE | INV-DEMO-007 | Acme Supplies | 56,000 | 56,000 | ✅ MATCH |
| 5 | DUPLICATE_INVOICE | INV-DEMO-018 | BuildRight Materials | 76,000 | 76,000 | ✅ MATCH |
| 6 | QUANTITY_MISMATCH | INV-DEMO-019 | BuildRight Materials | 20,000 | 20,000 | ✅ MATCH |

**Total Leakage:** ₹179,500

**Artifacts:** `_generate_demo_data.py`, `_upload_demo_data.py`, `data/demo/`

---

## Task 3: Non-Builder Walkthrough (Item 8.7) ✅

**Objective:** Create a step-by-step guide a non-technical observer can follow to validate the system.

**Deliverables:**
1. **DEMO_WALKTHROUGH.md** — 11-step browser walkthrough covering:
   - Login → Dashboard → Upload → Leakage Review → Detail → Accept All → Vendors → Contracts → Reports → Admin → Notifications
   - Expected values table, troubleshooting guide, observer feedback form

2. **KNOWN_UX_ISSUES.md** — 10 documented UX limitations:
   - 2× P1 (no 404 route, USD currency fallback)
   - 6× P2 (hidden PENDING_FX, dashboard latest-only, no notification pagination, no admin guard, reports limited to 20, progress >100%)
   - 2× P3 (no WebSocket, no ERP integration)

---

## Task 4: Final Clean Run ✅

### 4a. Determinism Check

| Metric | Run 1 | Run 2 |
|--------|-------|-------|
| Run ID | 1fbd2a07-172b-4f57-91ef-a64c272974bd | 27e5a951-ec33-49b5-85e2-4cdc484ec5ef |
| Status | COMPLETE | COMPLETE |
| Record Count | 6 | 6 |
| PRICE_MISMATCH INV-DEMO-004 | ₹7,000 / conf=1.0 | ₹7,000 / conf=1.0 |
| PRICE_MISMATCH INV-DEMO-012 | ₹13,000 / conf=1.0 | ₹13,000 / conf=1.0 |
| PRICE_MISMATCH INV-DEMO-015 | ₹7,500 / conf=1.0 | ₹7,500 / conf=1.0 |
| DUPLICATE_INVOICE INV-DEMO-007 | ₹56,000 / conf=0.85 | ₹56,000 / conf=0.85 |
| DUPLICATE_INVOICE INV-DEMO-018 | ₹76,000 / conf=0.85 | ₹76,000 / conf=0.85 |
| QUANTITY_MISMATCH INV-DEMO-019 | ₹20,000 / conf=0.9 | ₹20,000 / conf=0.9 |

**DETERMINISM: PASS** — Identical records, amounts, and confidence scores across both runs.

### 4b. Test Suite

```
635 passed, 17 skipped, 0 failed (55.31s)
```

17 skipped tests are integration/fixture-dependent tests (marked `@pytest.mark.integration` or requiring real `.docx` fixture files). All 635 unit/functional tests pass.

---

## Pilot Readiness Summary

| Section | Items | YES |
|---------|-------|-----|
| 1. Data Pipeline | 8 | 8 |
| 2. Rules Engine | 6 | 6 |
| 3. FX & Units | 5 | 5 |
| 4. API & Auth | 5 | 5 |
| 5. Reporting | 5 | 5 |
| 6. Worker & Tasks | 5 | 5 |
| 7. Frontend | 5 | 5 |
| 8. Ops & Release | 7 | 7 |
| 9. Risk | 6 | 6 |
| **TOTAL** | **52** | **52** |

**Verdict: 52/52 YES — PILOT READY**

---

## Files Created/Modified This Session

| File | Action |
|------|--------|
| `PILOT_READINESS_ASSESSMENT.md` | Updated 49→52/52 YES |
| `Dockerfile.weasyprint-test` | Created (WeasyPrint PDF test) |
| `_generate_demo_data.py` | Created (demo dataset generator) |
| `_upload_demo_data.py` | Created (demo upload + verify) |
| `_determinism_run2.py` | Created (determinism comparison) |
| `DEMO_WALKTHROUGH.md` | Created (11-step observer guide) |
| `KNOWN_UX_ISSUES.md` | Created (10 UX issues documented) |
| `DEMO_RUN_ID.txt` | Created (run ID bookmark) |
| `data/demo/*.xlsx` | Created (4 demo data files) |
