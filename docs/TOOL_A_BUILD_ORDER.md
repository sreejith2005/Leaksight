# Tool A Build Order

## Build summary
- Scope completed: Phases 1 through 7
- Baseline before Phase 7: 663 passed, 0 failed (environment-only non-regression errors excluded)
- Post-Phase 7 validation target: 663+ passed, 0 failed
- Final objective delivered: Tool A extraction + review + LeakSight import + demo dataset + docs handoff

## Phase completion checklist
- [x] Phase 1 - Tool A schema and model foundation
- [x] Phase 2 - Extraction pipeline (PDF/DOCX/Excel) and normalization
- [x] Phase 3 - Structuring run lifecycle and Celery queue wiring
- [x] Phase 4 - Structuring API and review endpoints
- [x] Phase 5 - Frontend pages/components for Tool A workflow
- [x] Phase 6 - Stabilization and pre-Phase 7 fixes
- [x] Phase 7 - LeakSight import integration, deterministic demo, documentation completion

## Files created
- _generate_tool_a_demo_data.py
- _run_tool_a_demo.py
- TOOL_A_README.md
- TOOL_A_BUILD_ORDER.md

## Files modified
- backend/app/tools/contract_structuring/tasks.py: Implemented LEAKSIGHT_IMPORT write path to canonical contracts, vendor fuzzy resolution >= 85, document fallbacks, duplicate protection, and no-confirmed-item guard.
- DEPLOYMENT_RUNBOOK.md: Added Tool A deployment and worker/memory notes.
- HOW_TO_START.md: Confirmed structuring queue in worker startup command and queue purpose note.
- KNOWN_UX_ISSUES.md: Added Tool A limitations section for pilot transparency.
- DEMO_WALKTHROUGH.md: Added Tool A demo steps 12-19 with expected outcomes.
- TOOL_A_README.md: Rewritten as operational handoff guide.
- TOOL_A_BUILD_ORDER.md: Updated to completed build record.

## Database tables added
1. contract_structuring_runs
2. contract_structuring_run_documents
3. raw_contract_tables
4. extracted_line_items
5. extracted_clauses
6. contract_structuring_exports
7. extracted_line_items.contract_id (column addition)

## API endpoints added
1. POST /api/v1/structuring/runs
2. GET /api/v1/structuring/runs
3. GET /api/v1/structuring/runs/{run_id}/status
4. GET /api/v1/structuring/runs/{run_id}/results
5. PATCH /api/v1/structuring/line-items/{item_id}
6. POST /api/v1/structuring/line-items/{item_id}/confirm
7. POST /api/v1/structuring/line-items/{item_id}/reject
8. PATCH /api/v1/structuring/clauses/{clause_id}
9. POST /api/v1/structuring/runs/{run_id}/export/excel
10. POST /api/v1/structuring/runs/{run_id}/export/erp-json
11. POST /api/v1/structuring/runs/{run_id}/export/leaksight-import
12. GET /api/v1/structuring/runs/{run_id}/exports

## Known issues at completion
- PDF table edge cases with merged cells still require manual review.
- Handwritten scanned contracts remain low-confidence in V1.1.
- No direct ERP API push in V1.1 (manual import/export flow by design).
