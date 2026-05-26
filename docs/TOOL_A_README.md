# Tool A README

## 1. What Tool A does
Tool A converts contract files into structured pricing data that can be reviewed and used by LeakSight. It reads contract tables and key commercial clauses, then shows extracted line items in a review workflow so users can confirm what is correct and reject what is uncertain.

After review, confirmed line items can be exported in multiple formats, including LeakSight Import. This lets contract pricing become trusted reference data for the core leakage engine, so future invoice checks can compare billed prices against the contract baseline.

## 2. Supported input formats
- PDF (digital)
- PDF (scanned)
- DOCX
- XLSX/XLS
- CSV

## 3. How to run locally
1. Start Docker Desktop.
2. Start backend from project root:

```powershell
.venv\Scripts\Activate.ps1
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Start Celery worker with structuring queue:

```powershell
.venv\Scripts\Activate.ps1
.venv\Scripts\python.exe -m celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo -Q default,parse,analysis,structuring,revalidation
```

4. Start frontend:

```powershell
cd frontend
npm.cmd run dev
```

5. Open http://localhost:5173 and navigate to Contract Structuring from the sidebar.

## 4. How to run the demo
1. Generate Tool A demo files:

```powershell
.venv\Scripts\python.exe _generate_tool_a_demo_data.py
```

2. Run end-to-end Tool A demo verification:

```powershell
.venv\Scripts\python.exe _run_tool_a_demo.py
```

## 5. Extraction accuracy expectations
- Clean Excel contracts should extract at high reliability.
- Clean digital PDF contracts should be generally reliable, with edge cases flagged.
- Scanned contracts are more variable and may require manual review.
- High-confidence rows are intended for one-click confirmation.

## 6. Known limitations
1. P1 - PDF with complex merged cells: camelot may misread spanning cells, rows flagged as low confidence for manual review.
2. P1 - Scanned contracts with handwriting: PaddleOCR is trained on printed text, handwriting can produce garbled extraction output.
3. P2 - No direct ERP API push: by design in V1.1, Tool A produces export files and clients import manually. V2 planned: SAP BAPI and Tally API integration.
4. P2 - Escalation clause extraction is approximate: regex and keyword matching only. Complex conditional escalations may be missed. Confidence below 0.7 is flagged for manual review.
5. P2 - Large contracts are slow: 50-page batch processing adds latency, acceptable for periodic contract onboarding.
6. P3 - No ERP field mapping UI: generic JSON/CSV export schema only, client mapping is manual. V2 planned: ERP-specific mapping profiles.
7. P3 - No AI/LLM-assisted extraction: extraction is rule-based (regex, spaCy NER, camelot). V2 optional enhancement: local LLM via Ollama for ambiguous clause classification.

## 7. How Tool A output integrates with the Leakage Engine
LeakSight Import writes only CONFIRMED Tool A line items into canonical contract tables. Once imported, these contract versions and line items are visible through the Contracts API and Contracts UI.

The core leakage engine then uses that canonical contract data for Rule 1 price mismatch checks. This means future invoices from the same vendor can be validated against the imported contract prices.

## 8. Performance notes for large contracts
- Processing is asynchronous through Celery and can take longer for large or scanned contracts.
- OCR-heavy documents can increase CPU and memory usage.
- For production stability on large scans, monitor worker memory and use max-tasks-per-child recycling for workers.
